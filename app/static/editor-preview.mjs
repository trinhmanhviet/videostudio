import {allClips,clamp,activeVisualClips,prepareVisualClips,transitionOpacity,videoSourceTime} from './editor-model.mjs';

const validUrl=value=>{const url=new URL(value,location.href);if(url.origin!==location.origin||!['http:','https:'].includes(url.protocol))throw Error('Media không cùng nguồn.');return url.href;};
export class EditorPreview{
  constructor(canvas,{onTime=()=>{},onState=()=>{},onError=()=>{}}={}){
    this.canvas=canvas;this.ctx=canvas.getContext('2d');this.onTime=onTime;this.onState=onState;this.onError=onError;
    this.plan=null;this.assets={};this.cues=[];this.media=new Map();this.audios=new Map();this.time=0;this.playing=false;this.muted=false;this.rate=1;this.frame=null;
  }
  load(plan,assets,cues=[]){
    this.plan=plan;this.assets=Object.fromEntries(assets.map(a=>[a.id,a]));this.cues=cues;
    this.visualClips=prepareVisualClips(plan);
    this.canvas.width=plan.canvas.width;this.canvas.height=plan.canvas.height;
    this.time=clamp(this.time,0,plan.duration);this.draw();this.syncAudio();
  }
  element(asset,clipId=null){
    if(!asset?.url)return null;
    const key=asset.kind==='video'?'video:'+clipId:'image:'+asset.id;
    const cached=this.media.get(key);if(cached?.url===asset.url)return cached.element;
    if(cached?.element instanceof HTMLVideoElement){cached.element.pause();cached.element.removeAttribute('src');cached.element.load();}
    try{
      const element=asset.kind==='video'?document.createElement('video'):new Image();
      if(asset.kind==='video'){element.muted=true;element.preload='auto';element.playsInline=true;element.addEventListener('loadeddata',()=>this.draw());element.addEventListener('seeked',()=>!this.playing&&this.draw());}
      else element.onload=()=>this.draw();
      element.onerror=()=>this.onError('Không đọc được media: '+asset.name);
      element.src=validUrl(asset.url);this.media.set(key,{url:asset.url,element});return element;
    }catch(error){this.onError(error.message);return null;}
  }
  seek(time){this.time=clamp(time,0,this.plan?.duration??0);this.clock=performance.now();this.anchor=this.time;this.draw();this.syncAudio();this.onTime(this.time);}
  play(){
    if(!this.plan||this.playing)return;if(this.time>=this.plan.duration-.02)this.time=0;
    this.playing=true;this.clock=performance.now();this.anchor=this.time;this.syncAudio();this.onState(true);this.tick();
  }
  pause(){this.playing=false;if(this.frame)cancelAnimationFrame(this.frame);this.frame=null;for(const audio of this.audios.values())audio.pause();for(const entry of this.media.values())if(entry.element instanceof HTMLVideoElement)entry.element.pause();this.onState(false);}
  toggle(){this.playing?this.pause():this.play();}
  setRate(value){this.rate=value;this.clock=performance.now();this.anchor=this.time;this.syncAudio();}
  setMuted(value){this.muted=value;this.syncAudio();}
  tick(){
    if(!this.playing)return;this.time=Math.min(this.plan.duration,this.anchor+(performance.now()-this.clock)/1000*this.rate);
    this.draw();this.syncAudio();this.onTime(this.time);
    if(this.time>=this.plan.duration){this.pause();return;}
    this.frame=requestAnimationFrame(()=>this.tick());
  }
  syncAudio(){
    if(!this.plan)return;const tracks=Object.fromEntries(this.plan.tracks.map(t=>[t.id,t])),active=new Set();
    const speechActive=allClips(this.plan).some(c=>tracks[c.track_id]?.kind==='narration'&&c.enabled!==false&&!c.muted&&this.time>=c.start&&this.time<c.end&&!tracks[c.track_id]?.muted&&!this.plan.narration?.muted);
    for(const clip of allClips(this.plan)){
      if(clip.kind!=='audio')continue;const track=tracks[clip.track_id],asset=this.assets[clip.asset_id];
      if(!asset?.url||clip.enabled===false||clip.muted||clip.mute||track?.muted||this.time<clip.start||this.time>=clip.end)continue;
      if(track?.kind==='narration'&&this.plan.narration?.muted)continue;
      let audio=this.audios.get(clip.id);const mediaUrl=validUrl(asset.url);
      if(audio&&audio.src!==mediaUrl){audio.pause();audio.removeAttribute('src');audio.load();audio=null;}
      if(!audio){audio=new Audio(mediaUrl);audio.preload='auto';audio.addEventListener('error',()=>this.onError('Không đọc được âm thanh: '+asset.name));this.audios.set(clip.id,audio);}
      const raw=(clip.source_start??0)+this.time-clip.start;
      const duration=Number.isFinite(audio.duration)?audio.duration:asset.duration;
      const position=duration>0?raw%duration:raw;
      if(Number.isFinite(position)&&Math.abs(audio.currentTime-position)>.18)try{audio.currentTime=position;}catch{}
      let gain=clip.volume??1;
      if(track?.kind==='narration')gain*=this.plan.narration?.volume??1;
      if(['music','sfx'].includes(track?.kind)&&speechActive)gain*=track.kind==='music'?.55:.85;
      if(clip.fade_in>0)gain*=Math.min(1,(this.time-clip.start)/clip.fade_in);
      if(clip.fade_out>0)gain*=Math.min(1,(clip.end-this.time)/clip.fade_out);
      audio.volume=this.muted?0:clamp(gain,0,1);audio.playbackRate=this.rate;active.add(clip.id);
      if(this.playing&&audio.paused)audio.play().catch(()=>{});else if(!this.playing)audio.pause();
    }
    for(const [id,audio] of this.audios)if(!active.has(id)){audio.pause();audio.removeAttribute('src');audio.load();this.audios.delete(id);}
  }
  draw(){
    const ctx=this.ctx,W=this.canvas.width,H=this.canvas.height;ctx.clearRect(0,0,W,H);ctx.fillStyle='#090b10';ctx.fillRect(0,0,W,H);if(!this.plan)return;
    const tracks=Object.fromEntries(this.plan.tracks.map((t,i)=>[t.id,{...t,order:i}]));
    const active=activeVisualClips(this.plan,this.time,this.visualClips);
    const activeVideos=new Set(active.filter(c=>c.kind==='video').map(c=>'video:'+c.id));
    for(const [key,entry] of this.media)if(entry.element instanceof HTMLVideoElement&&!activeVideos.has(key)){entry.element.pause();entry.element.removeAttribute('src');entry.element.load();this.media.delete(key);}
    for(const clip of active){
      const progress=clamp((this.time-clip.start)/(clip.end-clip.start),0,1),transition=clip.transition??{},fade=transition.duration??0;
      ctx.save();ctx.globalAlpha=transitionOpacity(clip,this.time);
      let cx=(clip.x??.5)*W,cy=(clip.y??.5)*H;
      if(fade>0&&transition.type?.startsWith('slide_'))cx+=(transition.type==='slide_left'?1:-1)*W*Math.max(0,1-(this.time-clip.start)/fade);
      if(clip.kind==='text')this.text(clip.text,cx,cy,clip.size??48,clip.color??'#ffffff',clip.background,W*.86);
      else{
        const asset=this.assets[clip.asset_id],element=this.element(asset,clip.id);
        if(element){
          if(clip.kind==='video'){
            const sourceTime=videoSourceTime(clip,this.time,this.plan.canvas.fps),hold=this.time>=clip.end;
            if(Math.abs(element.currentTime-sourceTime)>(hold?.005:.18))try{element.currentTime=sourceTime;}catch{}
            element.playbackRate=this.rate;if(this.playing&&!hold&&element.paused)element.play().catch(()=>{});else if(!this.playing||hold)element.pause();
          }
          const iw=element.naturalWidth||element.videoWidth,ih=element.naturalHeight||element.videoHeight;
          if(iw&&ih){
            const crop=clip.crop??{x:0,y:0,width:1,height:1};let sw=iw*crop.width,sh=ih*crop.height,sx=iw*crop.x,sy=ih*crop.y;
            if((asset.provider??asset.source)==='flow'&&!clip.crop)sh*=.94;
            const bw=W*(clip.width??1),bh=H*(clip.height??1),amount=clip.motion?.amount??.06,type=clip.motion?.type??'none';
            let scale=clip.fit==='contain'?Math.min(bw/sw,bh/sh):Math.max(bw/sw,bh/sh);
            if(type==='zoom_in')scale*=1+amount*progress;else if(type==='zoom_out')scale*=1+amount*(1-progress);
            else if(type.startsWith('pan_')){scale*=1+amount;const delta=(progress-.5)*amount;if(type==='pan_left')cx+=bw*delta;if(type==='pan_right')cx-=bw*delta;if(type==='pan_up')cy+=bh*delta;if(type==='pan_down')cy-=bh*delta;}
            ctx.beginPath();ctx.rect((clip.x??.5)*W-bw/2,(clip.y??.5)*H-bh/2,bw,bh);ctx.clip();
            try{ctx.drawImage(element,sx,sy,sw,sh,cx-sw*scale/2,cy-sh*scale/2,sw*scale,sh*scale);}catch{}
          }
        }
      }
      ctx.restore();
    }
    const captions=this.plan.captions??{};
    const activeMedia=new Set(active.map(c=>c.kind==='video'?'video:'+c.id:'image:'+c.asset_id));
    for(const key of this.media.keys()){if(this.media.size<=32)break;if(!activeMedia.has(key))this.media.delete(key);}
    if(captions.enabled!==false){const cue=this.cues.find(c=>this.time>=c.start&&(this.time<c.end||(this.time===this.plan.duration&&c.end===this.plan.duration)));if(cue){
      const size=Math.max(8,Math.round((captions.font_size??52)*W/1080)),bottom=Math.round((captions.bottom_margin??576)*H/1920);
      const emphasis=(captions.emphasis??[]).filter(c=>c.utterance_index===this.cues.indexOf(cue)&&this.time>=c.start&&this.time<=c.end);
      this.text(cue.narration??cue.text??'',W/2,H-bottom-size*.35,size,captions.color??'#ffffff',null,W*.83,true,{...captions,emphasis});
    }}
  }
  text(text,x,y,size,color,background,maxWidth,bottomAligned=false,captions={}){
    const ctx=this.ctx;ctx.font=`normal ${size}px Arial`;ctx.textAlign='center';ctx.textBaseline='middle';
    const words=String(text).split(/\s+/),lines=[];let line='';
    for(const word of words){const next=line?line+' '+word:word;if(line&&ctx.measureText(next).width>maxWidth){lines.push(line);line=word;}else line=next;}if(line)lines.push(line);
    const leading=size*1.3,height=lines.length*leading,start=bottomAligned?y-height+leading/2:y-height/2+leading/2;
    if(background){ctx.fillStyle=background;ctx.fillRect(x-Math.min(maxWidth,Math.max(...lines.map(l=>ctx.measureText(l).width)))/2-20,start-leading*.6,maxWidth+40,height+12);}
    ctx.lineJoin='round';ctx.lineWidth=Math.max(2,size*.065);ctx.strokeStyle='#0a0c12dd';ctx.shadowColor='#0008';ctx.shadowBlur=6;ctx.shadowOffsetY=2;
    lines.forEach((value,i)=>{ctx.strokeText(value,x,start+i*leading);ctx.fillStyle=color;ctx.fillText(value,x,start+i*leading);
      for(const cue of captions.emphasis??[]){const at=value.indexOf(cue.text);if(at<0)continue;const left=x-ctx.measureText(value).width/2+ctx.measureText(value.slice(0,at)).width;ctx.save();ctx.textAlign='left';ctx.fillStyle=captions.accent_color??color;ctx.strokeText(cue.text,left,start+i*leading);ctx.fillText(cue.text,left,start+i*leading);ctx.restore();}
    });
    ctx.shadowBlur=0;ctx.shadowOffsetY=0;
  }
  destroy(){this.pause();for(const audio of this.audios.values()){audio.removeAttribute('src');audio.load();}for(const {element} of this.media.values())if(element instanceof HTMLVideoElement){element.removeAttribute('src');element.load();}this.media.clear();this.audios.clear();}
}
