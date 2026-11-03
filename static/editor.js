import {PlanHistory,allClips,findClip,clone,clamp,formatTime,moveClip,trimClip,splitClip,removeClip,updateClip,addClip,snapTime,moveTrack,packTimelineRows} from './editor-model.mjs';
import {EditorPreview} from './editor-preview.mjs';
import {mountWorkflowCanvas} from './workflow-canvas.js';

const $=selector=>document.querySelector(selector);
const el=(tag,text='',className='')=>{const node=document.createElement(tag);node.textContent=text;if(className)node.className=className;return node;};
const uid=prefix=>prefix+'-'+crypto.randomUUID().slice(0,12);
const labels={image:'Hình ảnh',video:'Video',text:'Chữ',audio:'Âm thanh',narration:'Lời đọc',music:'Nhạc nền',sfx:'Hiệu ứng âm thanh',caption:'Phụ đề'};
const terminal=state=>['completed','failed','cancelled','canceled','awaiting_visual_review'].includes(state);
const stateOf=job=>job.status??job.state;

export class EditingWorkspace{
  constructor(){
    const query=new URLSearchParams(location.search);this.jobId=query.get('job');this.scope=query.get('scope')??location.pathname.match(/\/story-video\/projects\/([0-9a-f-]+)\/production/)?.[1];this.project=query.get('project')??'';
    this.panel='media';this.filter='all';this.selected=null;this.revision=0;this.dirty=false;this.zoom=35;this.snapping=true;this.playhead=0;this.assets={};this.waveforms=new Map();this.dragging=false;this.exportState=null;
    this.preview=new EditorPreview($('#previewCanvas'),{onTime:time=>this.updateTime(time),onState:playing=>{$('#playPause').textContent=playing?'❚❚':'▶';$('#playPause').setAttribute('aria-label',playing?'Tạm dừng preview':'Phát preview');},onError:message=>this.toast(message,true)});
    this.bind();this.initialize().catch(error=>this.showError(error));
  }
  get plan(){return this.history?.current;}
  async api(path,options={}){
    const headers={...options.headers};if(options.body&&typeof options.body==='object'&&!(options.body instanceof Blob)){options={...options,body:JSON.stringify(options.body)};headers['Content-Type']='application/json';}
    else if(typeof options.body==='string'&&!headers['Content-Type'])headers['Content-Type']='application/json';
    const response=await fetch(path,{...options,headers,credentials:'same-origin',signal:options.signal??AbortSignal.timeout(60000)});
    if(!response.ok){let detail;try{detail=(await response.json()).detail;}catch{}throw Object.assign(Error(typeof detail==='string'?detail:detail?JSON.stringify(detail):'Không hoàn tất yêu cầu ('+response.status+').'),{status:response.status});}
    return response.status===204?null:response.json();
  }
  async initialize(){
    try{this.health=await this.api('/api/health');}catch{}
    this.workflow=mountWorkflowCanvas($('#workflowWorkspace'),{api:this.api.bind(this),onRun:request=>this.runWorkflow(request),job:null});
    if(!this.jobId){$('#saveState').textContent='Không gian mới';$('#savePlan').disabled=true;$('#exportVideo').disabled=true;this.renderInspector();if(new URLSearchParams(location.search).get('view')==='workflow')this.switchView('workflow');return;}
    const [view,job]=await Promise.all([this.api(`/api/jobs/${encodeURIComponent(this.jobId)}/edit-plan`),this.api(`/api/jobs/${encodeURIComponent(this.jobId)}`)]);
    this.job=job;this.history=new PlanHistory(view.plan);this.applyView(view);this.renderAll();
    const title=job.title??job.idea??job.request?.idea??'Video của bạn';$('#projectTitle').textContent=title;$('#projectTitle').title=title;
    $('#projectSubtitle').textContent='Bản dựng độc lập · nguồn gốc được giữ nguyên';$('#legacyEditor').href='/?editor='+encodeURIComponent(this.jobId);
    await this.workflow.ready;this.workflow.setJob({...job,request:job.request??{idea:job.idea,voice_id:job.voice_id,duration_seconds:view.duration,project:job.project}});
    try{this.exportState=JSON.parse(sessionStorage.getItem('vs-edit-export:'+this.jobId)??'null');}catch{}
    if(this.exportState?.jobId)this.pollExport(this.exportState.jobId,false);
    if(new URLSearchParams(location.search).get('view')==='workflow')this.switchView('workflow');
  }
  applyView(view){
    this.view=view;this.revision=view.revision;this.assets=Object.fromEntries(view.assets.map(asset=>[asset.id,asset]));
    $('#savePlan').disabled=!view.editable;$('#exportVideo').disabled=!view.can_export;
    $('#importMedia').disabled=!view.editable;
    if(view.parent_job)this.notice('Đây là bản xuất đã đóng băng. Mở bản dựng gốc ở bảng Thuộc tính để tiếp tục chỉnh sửa.');
    if(view.warnings?.length)this.notice(view.warnings.join(' · '));
    this.preview.load(this.plan,view.assets,view.utterances??[]);$('#previewEmpty').hidden=true;
    $('#previewCanvas').style.aspectRatio=`${this.plan.canvas.width}/${this.plan.canvas.height}`;
    $('#canvasRatio').textContent=this.plan.canvas.width===this.plan.canvas.height?'1:1':this.plan.canvas.width<this.plan.canvas.height?'9:16':'16:9';
    this.updateSaveState();
  }
  bind(){
    $('#editorTab').onclick=()=>this.switchView('editor');$('#workflowTab').onclick=()=>this.switchView('workflow');
    $('#savePlan').onclick=()=>this.save().catch(e=>this.showError(e));$('#undo').onclick=()=>this.undo();$('#redo').onclick=()=>this.redo();
    $('#playPause').onclick=()=>this.preview.toggle();$('#previousScene').onclick=()=>this.jump(-1);$('#nextScene').onclick=()=>this.jump(1);
    $('#playbackRate').onchange=e=>this.preview.setRate(Number(e.target.value));$('#previewMute').onclick=()=>{this.preview.setMuted(!this.preview.muted);$('#previewMute').classList.toggle('active',this.preview.muted);};
    $('#fullPreview').onclick=()=>$('#previewStage').requestFullscreen?.();$('#previewFit').onclick=()=>{$('#previewCanvas').style.maxWidth='100%';$('#previewCanvas').style.maxHeight='100%';};
    $('#splitClip').onclick=()=>this.perform(()=>splitClip(this.plan,this.selected,this.playhead,uid('clip')));
    $('#deleteClip').onclick=()=>this.perform(()=>removeClip(this.plan,this.selected));$('#duplicateClip').onclick=()=>this.duplicate();
    $('#addLayer').onclick=()=>this.addLayer();$('#snapToggle').onclick=()=>{this.snapping=!this.snapping;$('#snapToggle').classList.toggle('active',this.snapping);$('#snapToggle').setAttribute('aria-pressed',String(this.snapping));};
    $('#timelineZoom').oninput=e=>this.setZoom(Number(e.target.value));$('#zoomOut').onclick=()=>this.setZoom(this.zoom/1.4);$('#zoomIn').onclick=()=>this.setZoom(this.zoom*1.4);$('#fitTimeline').onclick=()=>this.fitTimeline();
    $('#assetSearch').oninput=()=>this.renderLibrary();document.querySelectorAll('[data-filter]').forEach(button=>button.onclick=()=>{this.filter=button.dataset.filter;document.querySelectorAll('[data-filter]').forEach(b=>b.classList.toggle('active',b===button));this.renderLibrary();});
    document.querySelectorAll('[data-panel]').forEach(button=>button.onclick=()=>{this.panel=button.dataset.panel;document.querySelectorAll('[data-panel]').forEach(b=>b.classList.toggle('active',b===button));$('.asset-panel').classList.toggle('mobile-open',true);this.renderLibrary();if(this.panel==='captions'){this.selected='captions';this.renderInspector();}});
    $('#importMedia').onclick=()=>$('#mediaFile').click();$('#mediaFile').onchange=async e=>{const file=e.target.files[0];if(!file)return;try{await this.importMedia(file);}catch(error){this.showError(error);}finally{e.target.value='';}};
    $('#exportVideo').onclick=()=>this.openExport();$('#cancelExport').onclick=()=>$('#exportDialog').close();$('#confirmExport').onclick=()=>this.export().catch(e=>this.showError(e));
    $('#rulerTicks').onpointerdown=e=>this.scrub(e,$('#rulerTicks'));
    $('#previewCanvas').onpointerdown=e=>this.dragVisual(e);
    document.addEventListener('keydown',event=>this.keydown(event));
    window.addEventListener('beforeunload',event=>{if(this.dirty||this.workflow?.isDirty()){event.preventDefault();event.returnValue='';}this.preview.pause();});
    window.addEventListener('resize',()=>this.plan&&this.renderTimeline());
  }
  switchView(name){const workflow=name==='workflow';$('#editingWorkspace').hidden=workflow;$('#workflowWorkspace').hidden=!workflow;$('.top-actions').hidden=workflow;$('#editorTab').classList.toggle('active',!workflow);$('#workflowTab').classList.toggle('active',workflow);if(workflow)this.preview.pause();}
  toast(message,error=false){const box=$('#toast');box.textContent=message;box.classList.toggle('error',error);box.hidden=false;clearTimeout(this.toastTimer);this.toastTimer=setTimeout(()=>box.hidden=true,error?6500:3000);}
  notice(message){$('#notice').textContent=message;$('#notice').hidden=!message;}
  showError(error){this.toast(error.message??String(error),true);if(error.status===409)this.notice('Bản dựng đã thay đổi ở cửa sổ khác. Tải lại trang để nhận phiên bản mới; thay đổi chưa lưu chưa bị ghi đè.');}
  updateSaveState(){if(!this.plan)return;$('#saveState').textContent=this.applyingPreset?'Đang áp dụng phong cách…':this.dirty?'Có thay đổi chưa lưu':'Đã lưu · v'+this.revision;$('#undo').disabled=this.applyingPreset||!this.history.canUndo;$('#redo').disabled=this.applyingPreset||!this.history.canRedo;}
  commit(plan){
    if(this.applyingPreset){this.toast('Đang áp dụng phong cách, vui lòng chờ.');return;}
    if(!this.view?.editable){this.toast(this.view?.parent_job?'Bản xuất đã đóng băng. Mở bản dựng gốc để sửa tiếp.':'Chờ tác vụ hoàn tất hoặc tiếp tục tác vụ gốc trước khi chỉnh sửa.',true);return;}
    const keepInspector=Boolean(document.activeElement?.closest('#inspectorContent'))&&document.activeElement.matches('textarea,input[type=text],input[type=number]');
    this.history.push(plan);this.dirty=true;this.renderAll({keepInspector});
  }
  perform(action){if(!this.plan||!this.selected){this.toast('Chọn một clip trên timeline trước.');return;}try{this.commit(action());}catch(error){this.showError(error);}}
  undo(){if(this.applyingPreset||!this.history?.canUndo)return;this.history.undo();this.dirty=true;this.renderAll();}
  redo(){if(this.applyingPreset||!this.history?.canRedo)return;this.history.redo();this.dirty=true;this.renderAll();}
  renderAll({keepInspector=false}={}){if(!this.plan)return;this.updateSaveState();this.preview.load(this.plan,this.view.assets,this.view.utterances??[]);this.renderLibrary();this.renderTimeline();if(!keepInspector)this.renderInspector();this.updateTime(this.playhead);}
  updateTime(time){this.playhead=time;$('#timeDisplay').replaceChildren(document.createTextNode(formatTime(time)),el('span','/ '+formatTime(this.plan?.duration??0)));$('#playhead').style.left=(this.headerWidth()+time*this.zoom)+'px';}
  select(id){this.selected=id;document.querySelectorAll('.timeline-clip').forEach(node=>node.classList.toggle('selected',node.dataset.clip===id));this.renderInspector();const clip=findClip(this.plan,id)?.clip,track=id?.startsWith('track:')?this.plan.tracks.find(t=>t.id===id.slice(6)):null;$('#timelineSelection').textContent=clip?this.clipName(clip):track?track.name:id==='captions'?'Phụ đề':'Chưa chọn clip';}
  clipName(clip){return ['text','caption'].includes(clip.kind)?clip.text:this.assets[clip.asset_id]?.name??labels[clip.kind]??clip.id;}
  async save(){if(!this.saving)this.saving=this.saveOnce().finally(()=>this.saving=null);return this.saving;}
  async saveOnce(){
    if(!this.plan||!this.view.editable)return;const button=$('#savePlan');button.disabled=true;$('#saveState').textContent='Đang lưu…';
    const submitted=JSON.stringify(this.plan);
    try{const plan=clone(this.plan);plan.revision=this.revision;const view=await this.api(`/api/jobs/${this.jobId}/edit-plan`,{method:'PUT',body:{revision:this.revision,plan}});const newer=JSON.stringify(this.plan)!==submitted;this.history.current=newer?{...clone(this.plan),revision:view.revision}:clone(view.plan);this.dirty=newer;this.applyView(view);this.toast(newer?'Đã lưu bản trước; thay đổi mới vẫn ở bản nháp.':'Đã lưu kế hoạch dựng.');return view;}
    finally{button.disabled=this.applyingPreset||!this.view?.editable;this.updateSaveState();}
  }
  async importMedia(file){
    if(!this.jobId||!this.view?.editable)throw Error('Mở một video có thể chỉnh sửa trước khi nhập media.');
    $('#importMedia').disabled=true;try{const result=await this.api(`/api/jobs/${this.jobId}/edit-plan/assets?name=${encodeURIComponent(file.name)}`,{method:'POST',headers:{'Content-Type':file.type||'application/octet-stream'},body:file});this.revision=result.revision;this.view.assets.push(result.asset);this.assets[result.asset.id]=result.asset;this.view.revision=this.revision;this.updateSaveState();this.renderLibrary();this.toast('Đã nhập '+file.name);}finally{$('#importMedia').disabled=false;}
  }
  renderLibrary(){
    const library=$('#library');library.replaceChildren();$('#libraryTitle').textContent={media:'Media của video',text:'Chữ & nhãn',audio:'Âm thanh',sfx:'Hiệu ứng âm thanh',presets:'Phong cách dựng',captions:'Phụ đề'}[this.panel];$('#libraryFilters').hidden=!['media','audio'].includes(this.panel);
    if(this.panel==='text'){
      for(const [name,sample,size] of [['Tiêu đề','CÂU CHUYỆN BẮT ĐẦU',68],['Nhãn thông tin','Một góc nhìn mới',44],['Mốc thời gian','Năm 1840',58]]){const button=el('button','','text-template');button.append(el('strong',sample),el('small',name+' · bấm để thêm'));button.onclick=()=>this.addText(sample,size);library.append(button);}return;
    }
    if(this.panel==='presets'){
      for(const preset of this.view?.presets??[]){const card=el('button','','preset-card');card.append(el('strong',preset.name??preset.id),el('p',preset.description??''));const palette=el('div','','palette');for(const color of [preset.accent_color??preset.captions?.accent_color??'#68e4d7',preset.captions?.color??'#ffffff','#242935']){const dot=el('i');dot.style.backgroundColor=color;palette.append(dot);}card.append(palette);card.onclick=()=>this.applyPreset(preset.id);library.append(card);}return;
    }
    if(this.panel==='captions'){const box=el('div','','empty-library');box.append(el('strong','Phụ đề theo lời đọc thật'),el('p','Mỗi câu giữ mốc thời gian đã đo. Chọn kiểu chữ và vị trí ở bảng thuộc tính.'));library.append(box);return;}
    const search=$('#assetSearch').value.toLocaleLowerCase('vi');
    const assets=(this.view?.assets??[]).filter(asset=>{
      const sfx=asset.id.startsWith('sfx-')||asset.source==='procedural';
      return (!search||asset.name.toLocaleLowerCase('vi').includes(search))&&(this.panel==='sfx'?sfx:this.panel==='audio'?asset.kind==='audio'&&!sfx:this.filter==='all'||asset.kind===this.filter);
    });
    for(const asset of assets){
      const tile=el('button','','asset-tile');tile.title=asset.name+' · bấm để thêm vào timeline';tile.draggable=true;
      if(asset.kind==='image'||asset.thumbnail_url){const image=el('img');image.loading='lazy';image.alt=asset.name;image.src=asset.thumbnail_url??asset.url;tile.append(image);}else tile.append(el('span',asset.kind==='video'?'▶':'♫','media-symbol'));
      tile.append(el('span',labels[asset.kind]??asset.kind,'asset-kind'),el('span',asset.name,'asset-name'),el('span','＋','asset-add'));tile.onclick=()=>this.addAsset(asset);tile.ondragstart=e=>e.dataTransfer.setData('application/x-videostudio-asset',asset.id);library.append(tile);
    }
    if(!assets.length)library.append(el('div',this.jobId?'Chưa có media phù hợp. Bấm ＋ để nhập ảnh, video hoặc âm thanh.':'Mở video từ Studio để dùng lại media đã tạo.','empty-library'));
    $('#assetCount').textContent=(this.view?.assets.length??0)+' media';
  }
  trackFor(kind){
    const kinds=kind==='audio'?['audio','music']:kind==='sfx'?['sfx']:kind==='text'?['text']:['image','video'];
    const selected=findClip(this.plan,this.selected)?.clip,selectedTrack=this.plan.tracks.find(t=>t.id===(this.selected?.startsWith('track:')?this.selected.slice(6):selected?.track_id));
    return selectedTrack&&!selectedTrack.locked&&kinds.includes(selectedTrack.kind)?selectedTrack:this.plan.tracks.find(t=>!t.locked&&kinds.includes(t.kind));
  }
  addAsset(asset,time=this.playhead,trackId=null){
    if(!this.plan)return this.toast('Mở video để thêm media.');let plan=clone(this.plan),sfx=asset.id.startsWith('sfx-'),track=trackId?plan.tracks.find(t=>t.id===trackId):this.trackFor(sfx?'sfx':asset.kind);
    if(!trackId&&['image','video'].includes(asset.kind))track=[...plan.tracks].reverse().find(t=>!t.locked&&['image','video'].includes(t.kind)&&!allClips(plan).some(c=>c.track_id===t.id));
    if(!track){track={id:uid('track'),name:sfx?'SFX mới':asset.kind==='audio'?'Âm thanh thêm':'Lớp hình ảnh',kind:sfx?'sfx':asset.kind==='audio'?'audio':asset.kind,muted:false,visible:true,locked:false};plan.tracks.push(track);}
    if(track.locked)return this.toast('Lớp đang khóa.',true);
    const audioTrack=['audio','narration','music','sfx'].includes(track.kind);if(audioTrack!==(asset.kind==='audio'))return this.toast('Media không phù hợp với lớp đích.',true);
    const desired=asset.kind==='image'?4:asset.duration??4;let start=clamp(time,0,plan.duration-.1);if(plan.duration-start<Math.min(.5,desired/2))start=Math.max(0,plan.duration-Math.min(desired,plan.duration));
    const length=Math.min(plan.duration-start,desired),id=uid('clip');
    const clip={id,track_id:track.id,kind:asset.kind,asset_id:asset.id,start,end:start+Math.max(.05,length),source_start:0,enabled:true};
    if(asset.kind==='audio')Object.assign(clip,{volume:sfx?.5:.35,fade_in:sfx?0:.2,fade_out:sfx?.1:.4});else Object.assign(clip,{fit:'cover',x:.5,y:.5,width:1,height:1,opacity:1,motion:{type:'none',amount:.06},transition:{type:'none',duration:.3}});
    plan=addClip(plan,clip,sfx?'sfx':asset.kind==='audio'?'music':'clips');this.selected=id;this.commit(plan);this.preview.seek(start);
  }
  addText(text='Nhập tiêu đề',size=58){
    if(!this.plan)return this.toast('Mở video để thêm chữ.');let plan=clone(this.plan),track=this.trackFor('text');
    const start=this.playhead>plan.duration-.5?Math.max(0,plan.duration-3):this.playhead;
    const highest=Math.max(-1,...plan.tracks.map((t,i)=>['image','video','text'].includes(t.kind)?i:-1));
    if(track&&(plan.tracks.indexOf(track)<highest||plan.clips.some(c=>c.track_id===track.id&&c.start<start+3&&c.end>start)))track=null;
    if(!track){track={id:uid('text'),name:'Chữ & nhãn',kind:'text',muted:false,visible:true,locked:false};plan.tracks.push(track);}
    const id=uid('text');this.selected=id;this.commit(addClip(plan,{id,track_id:track.id,kind:'text',start,end:Math.min(plan.duration,start+3),text,size,color:'#ffffff',background:null,x:.5,y:.18,width:.86,height:.2,enabled:true,opacity:1,transition:{type:'fade',duration:.25}}));this.preview.seek(Math.min(plan.duration,start+.3));
  }
  addLayer(){if(!this.plan)return;const plan=clone(this.plan);plan.tracks.push({id:uid('visual'),name:'Lớp hình '+(plan.tracks.filter(t=>['image','video'].includes(t.kind)).length+1),kind:'image',muted:false,visible:true,locked:false});this.commit(plan);}
  duplicate(){this.perform(()=>{const found=findClip(this.plan,this.selected);if(!found)throw Error('Chọn clip để nhân bản.');const clip=clone(found.clip),length=clip.end-clip.start;clip.id=uid('clip');clip.start=Math.min(this.plan.duration-.1,clip.end);clip.end=Math.min(this.plan.duration,clip.start+length);return addClip(this.plan,clip,found.collection);});}
  headerWidth(){return innerWidth<=650?120:152;}
  setZoom(value){this.zoom=clamp(value,3,160);$('#timelineZoom').value=this.zoom;this.renderTimeline();this.updateTime(this.playhead);}
  fitTimeline(){if(this.plan)this.setZoom(($('#timelineScroll').clientWidth-this.headerWidth()-50)/this.plan.duration);}
  renderTimeline(){
    if(!this.plan)return;const width=Math.max(this.plan.duration*this.zoom+70,$('#timelineScroll').clientWidth-this.headerWidth()),ruler=$('#rulerTicks');ruler.replaceChildren();ruler.style.width=width+'px';
    const step=this.zoom<5?30:this.zoom<15?10:this.zoom<35?5:this.zoom<80?2:1;
    for(let time=0;time<=this.plan.duration+step;time+=step){const tick=el('span',formatTime(time).replace(/\.\d+$/,''),'ruler-tick');tick.style.left=time*this.zoom+'px';ruler.append(tick);}
    const rows=$('#timelineRows');rows.replaceChildren();const clips=allClips(this.plan),tracks=[...this.plan.tracks.filter(t=>['image','video','text'].includes(t.kind)).reverse(),...this.plan.tracks.filter(t=>!['image','video','text'].includes(t.kind))];
    if(this.view.utterances?.length)tracks.unshift({id:'__captions',kind:'caption',name:'Phụ đề',locked:true,visible:this.plan.captions.enabled!==false});
    for(const track of tracks){
      const row=el('div','','track-row'),header=el('div','','track-header'),lane=el('div','','track-lane');lane.dataset.track=track.id;lane.style.width=width+'px';lane.style.backgroundSize=(step*this.zoom)+'px 100%';
      const trackName=el('button',track.name,'track-name');trackName.title='Thuộc tính lớp '+track.name;trackName.setAttribute('aria-label',trackName.title);trackName.onclick=()=>this.select(track.kind==='caption'?'captions':'track:'+track.id);
      header.append(el('span',track.kind==='text'?'T':['audio','music','narration','sfx'].includes(track.kind)?'♫':track.kind==='caption'?'▤':'▧','track-icon'),trackName);
      const toggle=el('button',['audio','music','narration','sfx'].includes(track.kind)?(track.muted?'⊘':'♫'):(track.visible===false?'○':'◉'));toggle.title='Ẩn/hiện hoặc tắt tiếng lớp';toggle.setAttribute('aria-label',toggle.title+' '+track.name);toggle.classList.toggle('on',track.visible!==false&&!track.muted);toggle.onclick=()=>{
        const plan=clone(this.plan);if(track.kind==='caption')plan.captions.enabled=plan.captions.enabled===false;else{const target=plan.tracks.find(t=>t.id===track.id);if(['audio','music','narration','sfx'].includes(track.kind))target.muted=!target.muted;else target.visible=!target.visible;}this.commit(plan);
      };header.append(toggle);
      if(track.kind!=='caption'){const lock=el('button',track.locked?'▣':'◇');lock.title=track.locked?'Mở khóa lớp':'Khóa lớp';lock.setAttribute('aria-label',lock.title+' '+track.name);lock.onclick=()=>{const plan=clone(this.plan);plan.tracks.find(t=>t.id===track.id).locked=!track.locked;this.commit(plan);};header.append(lock);}
      row.append(header,lane);rows.append(row);
      const items=track.kind==='caption'?(this.view.utterances??[]).map((cue,i)=>({id:'cue-'+i,kind:'caption',track_id:track.id,start:cue.start,end:cue.end,text:cue.narration??cue.text})):clips.filter(c=>c.track_id===track.id);
      const packed=packTimelineRows(items);lane.style.height=(packed.count*43+12)+'px';
      for(const {clip,lane:subLane} of packed.items){
        const node=el('div','','timeline-clip '+(track.kind==='music'?'music':track.kind==='sfx'?'sfx':clip.kind));node.dataset.clip=clip.id;node.dataset.track=track.id;node.tabIndex=0;node.title=this.clipName(clip)+' · '+formatTime(clip.start)+' — '+formatTime(clip.end);node.setAttribute('role','button');node.setAttribute('aria-label',node.title);node.style.left=clip.start*this.zoom+'px';node.style.width=Math.max(3,(clip.end-clip.start)*this.zoom)+'px';node.classList.toggle('selected',clip.id===this.selected);node.classList.toggle('locked',track.locked);node.classList.toggle('disabled',clip.enabled===false||track.muted||track.visible===false);
        if(clip.kind==='image'&&this.assets[clip.asset_id]){const thumbs=el('div','','clip-thumbs');for(let i=0;i<Math.min(8,Math.ceil((clip.end-clip.start)*this.zoom/58));i++){const image=el('img');image.loading='lazy';image.alt='';image.src=this.assets[clip.asset_id].thumbnail_url??this.assets[clip.asset_id].url;thumbs.append(image);}node.append(thumbs);}
        node.style.top=(6+subLane*43)+'px';node.append(el('span',clip.text??this.clipName(clip),'clip-label'));
        if(clip.kind==='audio')this.drawWaveform(node,clip);
        if(!track.locked){for(const side of ['left','right']){const handle=el('span','','trim-handle '+side);handle.dataset.edge=side;node.append(handle);}}
        node.onpointerdown=e=>{if(clip.kind==='caption'){e.stopPropagation();this.select('captions');this.preview.seek(clip.start);}else this.dragClip(e,node,clip,track);};node.onkeydown=e=>{if(e.key==='Enter'){this.select(clip.kind==='caption'?'captions':clip.id);this.preview.seek(clip.start);}};lane.append(node);
      }
      lane.onpointerdown=e=>{if(e.target===lane){this.select(null);this.scrub(e,lane);}};
      lane.ondragover=e=>{e.preventDefault();};lane.ondrop=e=>{e.preventDefault();const id=e.dataTransfer.getData('application/x-videostudio-asset');if(this.assets[id])this.addAsset(this.assets[id],(e.clientX-lane.getBoundingClientRect().left)/this.zoom,track.id);};
    }
    $('#playhead').style.height=(rows.offsetHeight+27)+'px';$('#playhead').style.bottom='auto';$('#timelineStats').textContent=this.plan.clips.filter(c=>['image','video'].includes(c.kind)).length+' clip hình · '+tracks.length+' lớp';this.updateTime(this.playhead);
  }
  async drawWaveform(node,clip){
    let bins=this.waveforms.get(clip.asset_id),loadedNow=false;
    if(!bins){this.waveforms.set(clip.asset_id,[]);try{const data=await this.api(`/api/jobs/${this.jobId}/edit-plan/waveform?asset_id=${encodeURIComponent(clip.asset_id)}`);bins=data.bins??data.peaks??[];this.waveforms.set(clip.asset_id,bins);loadedNow=true;}catch{return;}}
    if(!bins?.length)return;
    if(loadedNow&&!node.isConnected){if(!this.waveDrawQueued){this.waveDrawQueued=true;requestAnimationFrame(()=>{this.waveDrawQueued=false;this.renderTimeline();});}return;}
    const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('class','waveform');svg.setAttribute('viewBox','0 0 400 20');svg.setAttribute('preserveAspectRatio','none');const path=document.createElementNS(svg.namespaceURI,'path');
    const duration=this.assets[clip.asset_id]?.duration??0;
    const samples=Array.from({length:100},(_,i)=>{const position=duration>0?(((clip.source_start??0)+(clip.end-clip.start)*i/100)%duration)/duration:i/100;return bins[Math.min(bins.length-1,Math.floor(position*bins.length))]??0;});path.setAttribute('d',samples.map((peak,i)=>`M${i*4} ${10-clamp(Math.abs(peak),0,1)*9}v${clamp(Math.abs(peak),0,1)*18}`).join(''));path.setAttribute('stroke','#d7f6dd');path.setAttribute('stroke-width','1.4');svg.append(path);node.append(svg);
  }
  scrub(event,lane){
    event.preventDefault();this.preview.pause();const seek=e=>this.preview.seek((e.clientX-lane.getBoundingClientRect().left)/this.zoom);seek(event);const finish=()=>{window.removeEventListener('pointermove',seek);window.removeEventListener('pointerup',finish);};window.addEventListener('pointermove',seek);window.addEventListener('pointerup',finish,{once:true});
  }
  dragClip(event,node,clip,track){
    if(event.button!==0)return;event.stopPropagation();this.select(clip.id);if(track.locked||!this.view.editable)return;
    event.preventDefault();const base=clone(this.plan),startX=event.clientX,edge=event.target.dataset.edge;let next=base,moved=false;this.preview.pause();
    const move=e=>{const delta=(e.clientX-startX)/this.zoom;if(Math.abs(delta)<.02&&!moved)return;moved=true;this.dragging=true;
      try{let targetTime=(edge==='right'?clip.end:clip.start)+delta;
        if(this.snapping){const targets=[0,this.playhead,this.plan.duration,...allClips(base).filter(c=>c.id!==clip.id).flatMap(c=>[c.start,c.end])];targetTime=snapTime(targetTime,targets,6/this.zoom);}
        next=edge?trimClip(base,clip.id,edge,targetTime,this.assets):moveClip(base,clip.id,targetTime-clip.start);
        const updated=findClip(next,clip.id).clip;node.style.left=updated.start*this.zoom+'px';node.style.width=Math.max(3,(updated.end-updated.start)*this.zoom)+'px';this.preview.load(next,this.view.assets,this.view.utterances??[]);
      }catch(error){this.toast(error.message,true);}
    };
      const finish=e=>{if(moved)move(e);window.removeEventListener('pointermove',move);this.dragging=false;if(moved){if(!edge){const lane=document.elementFromPoint(e.clientX,e.clientY)?.closest('.track-lane'),target=base.tracks.find(t=>t.id===lane?.dataset.track);if(target&&!target.locked&&target.kind===track.kind)findClip(next,clip.id).clip.track_id=target.id;}this.commit(next);}else this.preview.seek(clamp(clip.start+(event.clientX-node.getBoundingClientRect().left)/this.zoom,clip.start,clip.end-.001));};
    window.addEventListener('pointermove',move);window.addEventListener('pointerup',finish,{once:true});
  }
  dragVisual(event){
    const found=this.plan&&findClip(this.plan,this.selected);if(!found||!['image','video','text'].includes(found.clip.kind)||this.plan.tracks.find(t=>t.id===found.clip.track_id)?.locked)return;
    event.preventDefault();const base=clone(this.plan),rect=event.target.getBoundingClientRect(),x=event.clientX,y=event.clientY,original=found.clip;let next=null;
    const move=e=>{next=updateClip(base,original.id,{x:clamp((original.x??.5)+(e.clientX-x)/rect.width,0,1),y:clamp((original.y??.5)+(e.clientY-y)/rect.height,0,1)});this.preview.load(next,this.view.assets,this.view.utterances??[]);};
    window.addEventListener('pointermove',move);window.addEventListener('pointerup',e=>{if(next)move(e);window.removeEventListener('pointermove',move);if(next)this.commit(next);},{once:true});
  }
  jump(direction){if(!this.plan)return;const starts=this.plan.clips.filter(c=>['image','video'].includes(c.kind)).map(c=>c.start).sort((a,b)=>a-b);this.preview.seek(direction<0?[...starts].reverse().find(t=>t<this.playhead-.05)??0:starts.find(t=>t>this.playhead+.05)??this.plan.duration);}
  group(title){const group=el('section','','inspector-group');group.append(el('h3',title));return group;}
  field(group,label,value,{type='number',min=0,max=100,step=.1,options=null,onChange}={}){
    const wrap=el('label','','field');wrap.append(el('span',label));let input;
    if(options){input=el('select');for(const option of options){const pair=Array.isArray(option)?option:[option,option];input.append(new Option(pair[1],pair[0]));}input.value=value??'';}
    else if(type==='textarea'){input=el('textarea');input.value=value??'';}
    else{input=el('input');input.type=type;if(['number','range'].includes(type)){input.min=min;input.max=max;input.step=step;}input.value=value??'';}
    input.setAttribute('aria-label',label);input.disabled=!this.view?.editable;const apply=()=>{if(!options&&['number','range'].includes(type)&&(!input.value||!input.validity.valid))return;onChange?.(!options&&['number','range'].includes(type)?Number(input.value):input.value);};
    if(!options&&['textarea','text','number'].includes(type))input.oninput=apply;else input.onchange=apply;
    wrap.append(input);group.append(wrap);return input;
  }
  checkbox(group,label,checked,onChange){const wrap=el('label','','checkbox-row'),input=el('input');input.type='checkbox';input.checked=checked;input.disabled=!this.view?.editable;input.onchange=()=>onChange(input.checked);wrap.append(el('span',label),input);group.append(wrap);}
  renderInspector(){
    const content=$('#inspectorContent');content.replaceChildren();const found=this.plan&&findClip(this.plan,this.selected);
    if(!this.plan){content.append(el('div','Tạo video mới ở tab Workflow, hoặc mở một video đã tạo từ Studio.','inspector-empty'));return;}
    if(this.view.parent_job){const group=this.group('Bản xuất giữ nguyên');group.append(el('p','Kế hoạch và media của bản xuất này đã đóng băng. Bạn có thể sửa bản dựng gốc và xuất thành một video mới.'));const link=el('a','Mở bản dựng gốc','secondary full-width');const url=new URL(location.href);url.searchParams.set('job',this.view.parent_job);url.searchParams.set('view','editor');link.href=url.href;group.append(link);content.append(group);}
    if(this.selected?.startsWith('track:')){
      const id=this.selected.slice(6),track=this.plan.tracks.find(t=>t.id===id);if(!track){this.selected=null;return this.renderInspector();}
      $('#selectedType').textContent='Lớp';const group=this.group('Thiết lập lớp');
      const patch=change=>{const plan=clone(this.plan);Object.assign(plan.tracks.find(t=>t.id===id),change);this.commit(plan);};
      this.field(group,'Tên lớp',track.name,{type:'text',onChange:value=>patch({name:value.slice(0,120)})});this.checkbox(group,'Khóa chỉnh clip',track.locked,value=>patch({locked:value}));
      if(['audio','narration','music','sfx'].includes(track.kind))this.checkbox(group,'Tắt tiếng lớp',track.muted,value=>patch({muted:value}));else this.checkbox(group,'Hiện lớp',track.visible,value=>patch({visible:value}));
      if(['image','video','text'].includes(track.kind))for(const [label,direction] of [['Đưa lớp lên trên',1],['Đưa lớp xuống dưới',-1]]){const button=el('button',label,'secondary full-width');button.disabled=track.locked||!this.view.editable;button.onclick=()=>{try{this.commit(moveTrack(this.plan,id,direction));}catch(error){this.showError(error);}};group.append(button);}
      group.append(el('p','Lớp nằm trên trong timeline sẽ che lớp hình/chữ nằm dưới. Media nguồn không bị xóa khi bỏ lớp.'));
      const remove=el('button','Xóa lớp khỏi bản dựng','secondary full-width');remove.disabled=track.locked||this.plan.tracks.length<=1||!this.view.editable;remove.onclick=()=>{const plan=clone(this.plan);plan.tracks=plan.tracks.filter(t=>t.id!==id);for(const key of ['clips','music','sfx'])plan[key]=plan[key].filter(c=>c.track_id!==id);this.selected=null;this.commit(plan);};group.append(remove);content.append(group);return;
    }
    if(this.selected==='captions'){
      $('#selectedType').textContent='Phụ đề';const group=this.group('Phụ đề theo lời đọc');const patch=change=>{const plan=clone(this.plan);Object.assign(plan.captions,change);this.commit(plan);};
      this.checkbox(group,'Hiện phụ đề',this.plan.captions.enabled!==false,value=>patch({enabled:value}));this.field(group,'Cỡ chữ',this.plan.captions.font_size,{min:8,max:160,step:1,onChange:value=>patch({font_size:value})});this.field(group,'Màu chữ',this.plan.captions.color,{type:'color',onChange:value=>patch({color:value})});this.field(group,'Màu nhấn',this.plan.captions.accent_color,{type:'color',onChange:value=>patch({accent_color:value})});this.field(group,'Khoảng cách từ đáy (px)',this.plan.captions.bottom_margin,{min:0,max:this.plan.canvas.height*.6,step:10,onChange:value=>patch({bottom_margin:value})});
      const cueIndex=(this.view.utterances??[]).findIndex(c=>this.playhead>=c.start&&this.playhead<c.end),cue=this.view.utterances?.[cueIndex];
      if(cue){group.append(el('p',cue.narration));this.field(group,'Nhấn cụm từ trong câu đang xem',(this.plan.captions.emphasis??[]).filter(c=>c.utterance_index===cueIndex).map(c=>c.text).join(', '),{type:'text',onChange:value=>{const words=value.split(',').map(s=>s.trim()).filter(Boolean);if(words.some(word=>!cue.narration.includes(word)))return this.toast('Chọn cụm từ có nguyên văn trong câu đang xem.',true);patch({emphasis:[...(this.plan.captions.emphasis??[]).filter(c=>c.utterance_index!==cueIndex),...words.map(text=>({utterance_index:cueIndex,start:cue.start,end:cue.end,text}))]});}});}
      group.append(el('p','Timing giữ theo câu lời đọc đã đo; màu nhấn hiện trong khoảng câu, không giả định timing từng từ.'));content.append(group);return;
    }
    if(!found){
      $('#selectedType').textContent='Dự án';const info=this.group('Kế hoạch dựng');info.append(el('p',`${formatTime(this.plan.duration)} · ${this.plan.canvas.width} × ${this.plan.canvas.height} · ${this.plan.canvas.fps} fps`));
      this.field(info,'Phong cách',this.plan.preset_id,{options:(this.view.presets??[]).map(p=>[p.id,p.name??p.id]),onChange:value=>this.applyPreset(value)});info.append(el('p','Chọn một clip để chỉnh chữ, chuyển động, khung hình hoặc âm thanh.'));content.append(info);
      const audio=this.group('Lời đọc');this.field(audio,'Âm lượng lời đọc',this.plan.narration?.volume??1,{type:'range',min:0,max:2,step:.05,onChange:value=>{const plan=clone(this.plan);plan.narration={...plan.narration,volume:value};this.commit(plan);}});this.checkbox(audio,'Tắt tiếng lời đọc',this.plan.narration?.muted??false,value=>{const plan=clone(this.plan);plan.narration={...plan.narration,muted:value};this.commit(plan);});content.append(audio);
      const tools=this.group('Thao tác nhanh');for(const [label,fn] of [['Thêm tiêu đề',()=>this.addText()],['Kiểu phụ đề',()=>{this.select('captions');}],['Thư viện SFX',()=>{this.panel='sfx';this.renderLibrary();}]]){const button=el('button',label,'secondary full-width');button.onclick=fn;tools.append(button);}content.append(tools);return;
    }
    const clip=found.clip,track=this.plan.tracks.find(t=>t.id===clip.track_id),asset=this.assets[clip.asset_id];$('#selectedType').textContent=labels[track.kind]??labels[clip.kind];
    const info=this.group(this.clipName(clip));info.append(el('p',`${formatTime(clip.start)} → ${formatTime(clip.end)} · ${formatTime(clip.end-clip.start)}`));if(track.locked){info.append(el('p','Lớp đang khóa thời gian. Bấm biểu tượng khóa ở timeline để chỉnh.'));content.append(info);return;}
    const patch=change=>this.perform(()=>updateClip(this.plan,clip.id,change));
    this.field(info,'Bắt đầu (giây)',clip.start,{max:this.plan.duration-.1,step:.05,onChange:value=>this.perform(()=>moveClip(this.plan,clip.id,value-clip.start))});this.field(info,'Kết thúc (giây)',clip.end,{min:clip.start+.1,max:this.plan.duration,step:.05,onChange:value=>this.perform(()=>trimClip(this.plan,clip.id,'right',value,this.assets))});this.checkbox(info,'Bật clip',clip.enabled!==false,value=>patch({enabled:value}));content.append(info);
    if(clip.kind==='audio'){
      const group=this.group('Âm thanh');this.field(group,'Âm lượng',clip.volume??1,{type:'range',min:0,max:2,step:.05,onChange:value=>patch({volume:value})});this.checkbox(group,'Tắt tiếng',clip.muted??false,value=>patch({muted:value}));this.field(group,'Vị trí trong nguồn (giây)',clip.source_start??0,{max:asset?.duration??14400,onChange:value=>patch({source_start:value})});this.field(group,'Fade in (giây)',clip.fade_in??0,{max:Math.min(10,clip.end-clip.start),onChange:value=>patch({fade_in:value})});this.field(group,'Fade out (giây)',clip.fade_out??0,{max:Math.min(10,clip.end-clip.start),onChange:value=>patch({fade_out:value})});content.append(group);return;
    }
    if(['image','video'].includes(clip.kind)){
      const cropGroup=this.group('Cắt ảnh nguồn'),crop=clip.crop??{x:0,y:0,width:1,height:1};
      for(const [key,label] of [['x','Cắt: mép trái (%)'],['y','Cắt: mép trên (%)'],['width','Cắt: chiều rộng (%)'],['height','Cắt: chiều cao (%)']])this.field(cropGroup,label,Math.round(crop[key]*100),{min:key==='width'||key==='height'?1:0,max:100,step:1,onChange:value=>{const next={...crop,[key]:clamp(value/100,key==='width'||key==='height'?.01:0,1)};next.width=Math.max(.01,Math.min(next.width,1-next.x));next.height=Math.max(.01,Math.min(next.height,1-next.y));next.x=Math.min(next.x,1-next.width);next.y=Math.min(next.y,1-next.height);patch({crop:next});}});
      content.append(cropGroup);
    }
    if(clip.kind==='text'){
      const group=this.group('Nội dung & kiểu chữ');this.field(group,'Nội dung chữ',clip.text,{type:'textarea',onChange:value=>value.trim()&&patch({text:value})});this.field(group,'Cỡ chữ',clip.size??48,{min:8,max:300,step:1,onChange:value=>patch({size:value})});this.field(group,'Màu chữ',clip.color??'#ffffff',{type:'color',onChange:value=>patch({color:value})});this.checkbox(group,'Nền nhãn',Boolean(clip.background),value=>patch({background:value?'#202732':null}));if(clip.background)this.field(group,'Màu nền',clip.background,{type:'color',onChange:value=>patch({background:value})});content.append(group);
    }else{
      const group=this.group('Khung hình & chuyển động');this.field(group,'Cách hiển thị',clip.fit??'cover',{options:[['cover','Phủ kín'],['contain','Giữ toàn ảnh']],onChange:value=>patch({fit:value})});this.field(group,'Chuyển động',clip.motion?.type??'none',{options:[['none','Tĩnh'],['zoom_in','Zoom vào'],['zoom_out','Zoom ra'],['pan_left','Lướt trái'],['pan_right','Lướt phải'],['pan_up','Lướt lên'],['pan_down','Lướt xuống']],onChange:value=>patch({motion:{type:value,amount:clip.motion?.amount??.06}})});this.field(group,'Mức chuyển động',clip.motion?.amount??.06,{type:'range',min:0,max:.3,step:.01,onChange:value=>patch({motion:{type:clip.motion?.type??'none',amount:value}})});if(clip.kind==='video')this.field(group,'Vị trí trong nguồn (giây)',clip.source_start??0,{max:asset?.duration??14400,onChange:value=>patch({source_start:value})});content.append(group);
    }
    const transform=this.group('Vị trí & lớp');for(const [key,label,defaultValue,min,max] of [['x','Vị trí ngang',.5,0,1],['y','Vị trí dọc',.5,0,1],['opacity','Độ rõ',1,0,1],...(clip.kind==='text'?[]:[['width','Chiều rộng',1,.05,1],['height','Chiều cao',1,.05,1]])])this.field(transform,label,clip[key]??defaultValue,{type:'range',min,max,step:.01,onChange:value=>patch({[key]:value})});content.append(transform);
    const transition=this.group('Chuyển cảnh');this.field(transition,'Hiệu ứng',clip.transition?.type??'none',{options:[['none','Cắt thẳng'],['fade','Mờ dần'],['dissolve','Hoà tan'],['slide_left','Trượt trái'],['slide_right','Trượt phải']],onChange:value=>patch({transition:{type:value,duration:clip.transition?.duration??.3}})});this.field(transition,'Thời gian (giây)',clip.transition?.duration??.3,{min:0,max:Math.min(2,(clip.end-clip.start)/2),step:.05,onChange:value=>patch({transition:{type:clip.transition?.type??'none',duration:value}})});content.append(transition);
  }
  async applyPreset(id){
    if(!this.plan||this.applyingPreset)return;this.applyingPreset=true;$('#editingWorkspace').inert=true;$('#savePlan').disabled=true;$('#exportVideo').disabled=true;this.updateSaveState();
    try{while(this.dirty)await this.save();const view=await this.api(`/api/jobs/${this.jobId}/edit-plan/preset`,{method:'POST',body:{revision:this.revision,preset_id:id}});this.history.push(view.plan);this.dirty=false;this.applyView(view);this.renderAll();this.toast('Đã áp dụng phong cách dựng.');}
    catch(error){this.showError(error);}
    finally{this.applyingPreset=false;$('#editingWorkspace').inert=false;$('#savePlan').disabled=!this.view?.editable;$('#exportVideo').disabled=!this.view?.can_export;this.updateSaveState();}
  }
  keydown(event){
    if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='s'&&$('#workflowWorkspace').hidden){event.preventDefault();if(!this.applyingPreset)this.save().catch(e=>this.showError(e));return;}
    if(event.target.closest('input,textarea,select,[contenteditable=true]')||$('#workflowWorkspace').hidden===false||$('#exportDialog').open)return;
    const mod=event.ctrlKey||event.metaKey;if(mod&&event.key.toLowerCase()==='s'){event.preventDefault();this.save().catch(e=>this.showError(e));}
    else if(mod&&event.key.toLowerCase()==='z'){event.preventDefault();event.shiftKey?this.redo():this.undo();}
    else if(mod&&event.key.toLowerCase()==='y'){event.preventDefault();this.redo();}
    else if(event.code==='Space'){event.preventDefault();this.preview.toggle();}
    else if(event.key==='Delete'||event.key==='Backspace'){event.preventDefault();this.perform(()=>removeClip(this.plan,this.selected));}
    else if(event.key.toLowerCase()==='s'&&!mod)this.perform(()=>splitClip(this.plan,this.selected,this.playhead,uid('clip')));
    else if(event.key==='ArrowLeft'||event.key==='ArrowRight'){event.preventDefault();this.preview.seek(this.playhead+(event.key==='ArrowRight'?1:-1)*(event.shiftKey?1:.1));}
    else if(event.key==='Escape')this.select(null);
  }
  openExport(){if(!this.plan)return;const details=$('#exportDetails');details.replaceChildren(el('div',`Độ phân giải: ${this.plan.canvas.width} × ${this.plan.canvas.height} · ${this.plan.canvas.fps} fps`),el('div','Thời lượng: '+formatTime(this.plan.duration)),el('div','Phong cách: '+this.plan.preset_id),el('div','Ảnh, lời đọc và nhạc đã có sẽ được dùng lại.'));$('#exportDialog').showModal();}
  async export(){
    $('#confirmExport').disabled=true;try{while(this.dirty)await this.save();if(!this.exportState||this.exportState.revision!==this.revision||terminal(this.exportState.state))this.exportState={revision:this.revision,key:crypto.randomUUID()};
      sessionStorage.setItem('vs-edit-export:'+this.jobId,JSON.stringify(this.exportState));
      const job=await this.api(`/api/jobs/${this.jobId}/edit-plan/export`,{method:'POST',headers:{'Idempotency-Key':this.exportState.key},body:{revision:this.revision}});Object.assign(this.exportState,{jobId:job.id,state:stateOf(job)});sessionStorage.setItem('vs-edit-export:'+this.jobId,JSON.stringify(this.exportState));$('#exportResult').replaceChildren();$('#exportProgress').hidden=false;this.pollExport(job.id,true);
    }catch(error){$('#confirmExport').disabled=false;throw error;}
  }
  async pollExport(id,open){
    clearTimeout(this.exportTimer);try{const job=await this.api(`/api/jobs/${id}`),state=stateOf(job);if(this.exportState){this.exportState.state=state;sessionStorage.setItem('vs-edit-export:'+this.jobId,JSON.stringify(this.exportState));}
      $('#exportProgressText').textContent=state==='queued'?'Đang chờ bộ dựng…':state==='completed'?'Video mới đã hoàn tất.':state==='failed'?'Xuất chưa hoàn tất: '+(job.error??'kiểm tra chi tiết trong Studio'):'Đang dựng '+(job.stage==='verify'?'và kiểm tra thành phẩm…':'video…');
      if(terminal(state)){ $('#confirmExport').disabled=false;$('#exportProgress').hidden=true;
        const result=$('#exportResult');result.replaceChildren();if(state==='completed'){const link=el('a','Tải video mới ↗');link.href=job.video_url??`/api/jobs/${id}/files/video.mp4`;link.target='_blank';link.rel='noopener';link.download='video.mp4';result.append(el('p','Đã hoàn tất. Video cũ được giữ nguyên.'),link);if(!open)this.toast('Bản xuất mới đã hoàn tất.');}
        else{result.append(el('p',job.error??'Tác vụ chưa hoàn tất.'));const retry=el('button','Tiếp tục xuất','secondary');retry.onclick=async()=>{try{await this.api(`/api/jobs/${id}/retry`,{method:'POST'});$('#exportProgress').hidden=false;this.pollExport(id,true);}catch(error){this.showError(error);}};result.append(retry);}return;
      }
    }catch(error){$('#exportProgressText').textContent='Đang nối lại để kiểm tra bản xuất…';}
    this.exportTimer=setTimeout(()=>this.pollExport(id,open),1800);
  }
  async runWorkflow(request){
    if(!this.scope&&this.health?.text_transport==='extension')throw Error('Mở Workflow từ trang dự án Studio đã kết nối ChatGPT để chạy video.');
    const payload={...request,project:request.project||this.project||this.job?.project||'Dự án mặc định'};
    const identity=JSON.stringify(payload);let pending=this.pendingWorkflowRun;
    if(!pending)try{pending=JSON.parse(sessionStorage.getItem('vs-workflow-pending')??'null');}catch{}
    if(pending?.identity!==identity)pending={identity,key:crypto.randomUUID()};
    this.pendingWorkflowRun=pending;sessionStorage.setItem('vs-workflow-pending',JSON.stringify(pending));
    const job=await this.api('/api/jobs',{method:'POST',headers:{...(this.scope?{'X-Connector-Scope':this.scope}:{}),'Idempotency-Key':pending.key},body:payload});this.pendingWorkflowRun=null;sessionStorage.removeItem('vs-workflow-pending');this.toast('Đã nhận video mới. Bạn có thể theo dõi ở Studio.');this.pollWorkflow(job.id);return {...job,request:payload};
  }
  async pollWorkflow(id){clearTimeout(this.workflowTimer);try{const job=await this.api(`/api/jobs/${id}`);this.workflow.updateJob(job);if(terminal(stateOf(job)))return;}catch{}this.workflowTimer=setTimeout(()=>this.pollWorkflow(id),2500);}
}

if(typeof window!=='undefined'&&typeof document!=='undefined')window.videoEditingWorkspace=new EditingWorkspace();
