/* Pure timeline edits: original media and measured narration are never rewritten. */
export const clone=value=>structuredClone(value);
export const clamp=(value,min,max)=>Math.min(Math.max(Number(value)||0,min),Math.max(min,max));
export function formatTime(value){
  const ms=Math.round(Math.max(0,Number.isFinite(value)?value:0)*1000),hours=Math.floor(ms/3600000);
  const minutes=Math.floor(ms/60000)%60,seconds=Math.floor(ms/1000)%60;
  return `${hours?String(hours).padStart(2,'0')+':':''}${String(minutes).padStart(2,'0')}:${String(seconds).padStart(2,'0')}.${String(ms%1000).padStart(3,'0')}`;
}
export function allClips(plan){return ['clips','music','sfx'].flatMap(collection=>(plan?.[collection]??[]).map(clip=>({...clip,collection})));}
export function prepareVisualClips(plan){
  const tracks=Object.fromEntries(plan.tracks.map((track,index)=>[track.id,{...track,order:index}]));
  const layers=plan.clips.filter(c=>['image','video','text'].includes(c.kind)&&c.enabled!==false&&tracks[c.track_id]?.visible!==false).sort((a,b)=>(tracks[a.track_id]?.order??0)-(tracks[b.track_id]?.order??0)||a.start-b.start||a.id.localeCompare(b.id));
  const grouped=new Map();for(const clip of layers){if(!grouped.has(clip.track_id))grouped.set(clip.track_id,[]);grouped.get(clip.track_id).push(clip);}
  return layers.map(clip=>{const group=grouped.get(clip.track_id);let left=0,right=group.length;while(left<right){const middle=(left+right)>>1;if(group[middle].start<=clip.end-.001)left=middle+1;else right=middle;}const next=group[left];return {...clip,preview_extension:next&&Math.abs(next.start-clip.end)<.001&&next.transition?.type==='dissolve'?next.transition.duration??0:0};});
}
export function activeVisualClips(plan,time,prepared=null){
  return (prepared??prepareVisualClips(plan)).filter(c=>time>=c.start&&(time<c.end+c.preview_extension||(time===plan.duration&&c.end+c.preview_extension>=plan.duration)));
}
export function transitionOpacity(clip,time){
  let alpha=clip.opacity??1;const mode=clip.transition?.type,duration=clip.transition?.duration??0;
  if(duration>0&&['fade','dissolve'].includes(mode))alpha*=clamp((time-clip.start)/duration,0,1);
  if(duration>0&&mode==='fade')alpha*=clamp((clip.end-time)/duration,0,1);
  if(clip.kind==='text'&&clip.preview_extension>0&&time>clip.end)alpha*=clamp((clip.end+clip.preview_extension-time)/clip.preview_extension,0,1);
  return alpha;
}
export function videoSourceTime(clip,time,fps=30){
  const finalFrame=Math.max(0,(Math.ceil((clip.end-clip.start)*fps)-1)/fps);
  return (clip.source_start??0)+clamp(time-clip.start,0,finalFrame);
}
export function findClip(plan,id){
  for(const collection of ['clips','music','sfx']){
    const index=(plan[collection]??[]).findIndex(clip=>clip.id===id);
    if(index>=0)return {clip:plan[collection][index],collection,index};
  }
  return null;
}
function editable(plan,id){
  const found=findClip(plan,id);if(!found)throw Error('Không tìm thấy clip.');
  const track=plan.tracks.find(item=>item.id===found.clip.track_id);
  if(track?.locked)throw Error('Lớp đang khóa; mở khóa trước khi chỉnh thời gian.');
  return found;
}
function changed(plan,id,change){
  editable(plan,id);const next=clone(plan),found=findClip(next,id);change(found.clip,found,next);return next;
}
function boundEffects(clip){
  const duration=clip.end-clip.start;
  if(clip.transition){const transition={...clip.transition};transition.duration=transition.type==='none'?0:Math.min(transition.duration??0,transition.type==='fade'?duration/2:duration);clip.transition=transition;}
  for(const key of ['fade_in','fade_out'])if(key in clip)clip[key]=Math.min(clip[key],duration);
  return clip;
}
export function updateClip(plan,id,patch){return changed(plan,id,clip=>Object.assign(clip,clone(patch)));}
export function moveClip(plan,id,delta,trackId=null){
  return changed(plan,id,(clip,_found,next)=>{
    const length=clip.end-clip.start;clip.start=clamp(clip.start+delta,0,next.duration-length);clip.end=clip.start+length;
    if(trackId){
      const target=next.tracks.find(t=>t.id===trackId);if(!target||target.locked)throw Error('Lớp đích không khả dụng.');
      const audio=['audio','narration','music','sfx'].includes(target.kind);
      if(audio!==(clip.kind==='audio'))throw Error('Clip không phù hợp với lớp đích.');
      clip.track_id=trackId;
    }
  });
}
export function trimClip(plan,id,side,time,assets={}){
  return changed(plan,id,clip=>{
    const source=Math.max(0,clip.source_start??0),timed=['audio','video'].includes(clip.kind);
    if(side==='left'){
      const start=clamp(time,timed?Math.max(0,clip.start-source):0,clip.end-.1);
      if(timed)clip.source_start=source+start-clip.start;
      clip.start=start;
    }else{
      const sourceLimit=clip.kind==='video'&&assets[clip.asset_id]?.duration?clip.start+assets[clip.asset_id].duration-source:plan.duration;
      clip.end=clamp(time,clip.start+.1,Math.min(plan.duration,sourceLimit));
    }
    boundEffects(clip);
  });
}
export function splitClip(plan,id,time,newId){
  return changed(plan,id,(clip,found,next)=>{
    if(time<=clip.start+.1||time>=clip.end-.1)throw Error('Đặt con trỏ vào bên trong clip để tách.');
    if(findClip(next,newId))throw Error('ID clip đã tồn tại.');
    const right={...clone(clip),id:newId,start:time};
    if(['audio','video'].includes(clip.kind))right.source_start=(clip.source_start??0)+time-clip.start;
    clip.end=time;boundEffects(clip);boundEffects(right);next[found.collection].splice(found.index+1,0,right);
  });
}
export function removeClip(plan,id){return changed(plan,id,(_clip,found,next)=>next[found.collection].splice(found.index,1));}
export function addClip(plan,clip,collection='clips'){
  if(!['clips','music','sfx'].includes(collection)||findClip(plan,clip.id))throw Error('Clip mới không hợp lệ.');
  const next=clone(plan);next[collection]??=[];next[collection].push(boundEffects(clone(clip)));return next;
}
export function moveTrack(plan,id,direction){
  const next=clone(plan),indexes=next.tracks.map((track,index)=>['image','video','text'].includes(track.kind)?index:-1).filter(i=>i>=0),position=indexes.findIndex(i=>next.tracks[i].id===id);
  if(position<0||next.tracks[indexes[position]].locked)throw Error('Mở khóa lớp hình/chữ trước khi đổi thứ tự.');
  const target=position+direction;if(target<0||target>=indexes.length)return next;
  [next.tracks[indexes[position]],next.tracks[indexes[target]]]=[next.tracks[indexes[target]],next.tracks[indexes[position]]];return next;
}
export function packTimelineRows(clips){
  const ends=[],items=[];
  for(const clip of [...clips].sort((a,b)=>a.start-b.start||a.end-b.end||a.id.localeCompare(b.id))){let lane=ends.findIndex(end=>end<=clip.start+.000001);if(lane<0)lane=ends.length;ends[lane]=clip.end;items.push({clip,lane});}
  return {items,count:Math.max(1,ends.length)};
}
export function snapTime(time,targets,threshold=.15){
  let best=time,distance=threshold;
  for(const target of targets){const delta=Math.abs(target-time);if(delta<distance){best=target;distance=delta;}}
  return best;
}
export class PlanHistory{
  constructor(plan,limit=60){this.current=clone(plan);this.past=[];this.future=[];this.limit=limit;}
  get canUndo(){return this.past.length>0;}
  get canRedo(){return this.future.length>0;}
  push(plan){
    if(JSON.stringify(plan)===JSON.stringify(this.current))return this.current;
    this.past.push(this.current);if(this.past.length>this.limit)this.past.shift();this.future=[];this.current=clone(plan);return this.current;
  }
  undo(){if(this.canUndo){this.future.push(this.current);this.current=this.past.pop();}return clone(this.current);}
  redo(){if(this.canRedo){this.past.push(this.current);this.current=this.future.pop();}return clone(this.current);}
  reset(plan){this.current=clone(plan);this.past=[];this.future=[];}
}
