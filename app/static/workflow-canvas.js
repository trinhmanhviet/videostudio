/* Functional dataflow editor. All execution goes through server compilation. */
export const NODE_TYPES = {
 input:{title:'Ý tưởng / lời đọc',icon:'01',ins:[],outs:['brief']},
 research:{title:'Nghiên cứu',icon:'02',ins:['brief'],outs:['brief'],optional:true},
 script:{title:'Kịch bản',icon:'03',ins:['brief'],outs:['script']},
 speech:{title:'Lời đọc',icon:'04',ins:['script'],outs:['speech']},
 references:{title:'Ảnh tham chiếu',icon:'REF',ins:['script'],outs:['references'],optional:true},
 images:{title:'Tạo hình ảnh',icon:'05',ins:['script','speech','references'],outs:['images']},
 captions:{title:'Phụ đề',icon:'CC',ins:['speech'],outs:['captions'],optional:true},
 music:{title:'Nhạc theo chương',icon:'♫',ins:['speech'],outs:['music'],optional:true},
 sfx:{title:'Hiệu ứng âm thanh',icon:'FX',ins:['speech'],outs:['sfx'],optional:true},
 render:{title:'Dựng video',icon:'06',ins:['images','speech','captions','music','sfx'],outs:['video']},
 output:{title:'Kết quả',icon:'MP4',ins:['video'],outs:[]}
};
const copy=v=>JSON.parse(JSON.stringify(v));
const uid=()=>globalThis.crypto?.randomUUID?.()||`n-${Date.now()}-${Math.random().toString(36).slice(2)}`;
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export class WorkflowModel {
 constructor(graph){this.load(graph);}
 load(graph){this.graph=copy(graph);this.dirty=false;}
 changed(){this.dirty=true;}
 move(id,x,y){const node=this.graph.nodes.find(n=>n.id===id);if(node){Object.assign(node,{x,y});this.changed();}}
 configure(id,key,value){const node=this.graph.nodes.find(n=>n.id===id);if(node){if(value===''||value===undefined)delete node.config[key];else node.config[key]=value;this.changed();}}
 connect(source,source_port,target,target_port){
  const a=this.graph.nodes.find(n=>n.id===source),b=this.graph.nodes.find(n=>n.id===target);
  if(!a||!b||source===target||!NODE_TYPES[a.type].outs.includes(source_port)||!NODE_TYPES[b.type].ins.includes(target_port)||source_port!==target_port)throw Error('Các cổng không tương thích / incompatible sockets');
  const reaches=(id,seen=new Set())=>{if(id===source)return true;if(seen.has(id))return false;seen.add(id);return this.graph.edges.filter(e=>e.source===id).some(e=>reaches(e.target,seen));};
  if(reaches(target))throw Error('Kết nối tạo vòng lặp');
  this.graph.edges=this.graph.edges.filter(e=>!(e.target===target&&e.target_port===target_port));
  this.graph.edges.push({id:uid(),source,source_port,target,target_port});this.changed();
 }
 disconnect(id){this.graph.edges=this.graph.edges.filter(e=>e.id!==id);this.changed();}
 add(type){
  if(!NODE_TYPES[type]?.optional)throw Error('Chỉ thêm bước tùy chọn');
  if(this.graph.nodes.some(n=>n.type===type))throw Error('Bước này đã có trong workflow');
  const node={id:type,type,x:700,y:250+this.graph.nodes.filter(n=>NODE_TYPES[n.type].optional).length*80,config:{enabled:true}};
  this.graph.nodes.push(node);
  const byType=t=>this.graph.nodes.find(n=>n.type===t)?.id;
  if(type==='research'){
   this.graph.edges=this.graph.edges.filter(e=>!(e.target===byType('script')&&e.target_port==='brief'));
   this.connect(byType('input'),'brief',node.id,'brief');this.connect(node.id,'brief',byType('script'),'brief');
  } else if(type==='references'){
   this.connect(byType('script'),'script',node.id,'script');if(byType('images'))this.connect(node.id,'references',byType('images'),'references');
  } else {
   if(byType('speech'))this.connect(byType('speech'),'speech',node.id,'speech');if(byType('render'))this.connect(node.id,type,byType('render'),type);
  }
  this.changed();return node;
 }
 remove(id){
  const node=this.graph.nodes.find(n=>n.id===id);if(!node)return;
  if(!NODE_TYPES[node.type].optional)throw Error('Đây là bước bắt buộc / required stage');
  this.graph.nodes=this.graph.nodes.filter(n=>n.id!==id);this.graph.edges=this.graph.edges.filter(e=>e.source!==id&&e.target!==id);
  if(node.type==='research'){
   const a=this.graph.nodes.find(n=>n.type==='input'),b=this.graph.nodes.find(n=>n.type==='script');if(a&&b)this.connect(a.id,'brief',b.id,'brief');
  }
  this.changed();
 }
 clone(){this.graph.id='';this.graph.revision=0;this.graph.name+=' copy';this.changed();}
}

export function mountWorkflowCanvas(container,{api,onRun,job=null}={}) {
 const request=async(path,options={})=>{
  if(typeof api==='function')return api(path,options);
  if(api?.request)return api.request(path,options);
  const response=await fetch(path,{...options,headers:{'Content-Type':'application/json',...options.headers}});
  const body=await response.json();if(!response.ok)throw Error(body.detail||`HTTP ${response.status}`);return body;
 };
 let model=null,library={items:[],templates:[]},selected=null,pending=null,drag=null,disposed=false,busy=false,voices=[],batchSizes=[1],currentJob=job;
 container.classList.add('wf-root');
 container.innerHTML=`<aside class="wf-library"><div class="wf-brand">WORKFLOWS <span>STUDIO</span></div><p class="wf-muted">Tự động hóa video bằng các bước có kết nối.</p><div class="wf-library-list"></div><label class="wf-add-label">Thêm bước tùy chọn<select class="wf-add"><option value="">Chọn bước…</option>${Object.entries(NODE_TYPES).filter(([,v])=>v.optional).map(([key,v])=>`<option value="${key}">${v.title}</option>`).join('')}</select></label><button data-action="import">Nhập JSON</button><input class="wf-file" type="file" accept="application/json,.json" hidden><div class="wf-legend"><i></i> Nhấp cổng ra rồi cổng vào để nối.<br>Nhấp dây để ngắt. Kéo nền để di chuyển.<br>Cuộn để phóng to / thu nhỏ.</div></aside><main class="wf-main"><header class="wf-toolbar"><input class="wf-name" aria-label="Tên workflow" maxlength="200"><span class="wf-revision"></span><div class="wf-toolbar-actions"><button data-action="fit">Vừa khung</button><button data-action="clone">Nhân bản</button><button data-action="export">Xuất JSON</button><button data-action="save">Lưu</button><button data-action="run" class="wf-run">▶ Chạy workflow</button></div></header><div class="wf-message" role="status" aria-live="polite">Đang tải workflow…</div><section class="wf-stage" aria-label="Workflow canvas" tabindex="0"><div class="wf-world"><svg class="wf-wires" aria-label="Connections"></svg><div class="wf-nodes"></div></div><div class="wf-zoom"></div></section></main><aside class="wf-inspector"><h3>Thiết lập bước</h3><p class="wf-muted">Chọn một bước trên canvas.</p></aside>`;
 const $=s=>container.querySelector(s),stage=$('.wf-stage'),world=$('.wf-world');
 const message=(text,error=false)=>{const el=$('.wf-message');el.textContent=text;el.classList.toggle('error',error);};
 const fail=error=>message(error?.message||String(error),true);
 const invoke=async fn=>{try{await fn();}catch(error){fail(error);}};
 const mutate=()=>{model.changed();$('.wf-revision').textContent=`r${model.graph.revision} · chưa lưu`;};
 const transform=()=>{if(!model)return;const v=model.graph.viewport;world.style.transform=`translate(${v.x}px,${v.y}px) scale(${v.zoom})`;$('.wf-zoom').textContent=`${Math.round(v.zoom*100)}%`;};
 const nodeStatus=node=>{
  if(node.config.enabled===false)return ['disabled','Đã tắt'];
  if(!currentJob)return ['idle','Sẵn sàng'];
  const key={input:'plan',references:'images',captions:'subtitles',sfx:'render',output:'verify'}[node.type]||node.type;
  if(currentJob.checkpoints?.[key]||currentJob.state==='completed')return ['done','Hoàn tất'];
  if(currentJob.stage===key)return [currentJob.state==='failed'?'failed':'running',currentJob.state==='failed'?'Lỗi':'Đang chạy'];
  return ['idle','Chờ'];
 };
 const drawWires=()=>{
  if(!model)return;const svg=$('.wf-wires');svg.innerHTML='';
  for(const edge of model.graph.edges){
   const a=model.graph.nodes.find(n=>n.id===edge.source),b=model.graph.nodes.find(n=>n.id===edge.target);if(!a||!b)continue;
   const ai=NODE_TYPES[a.type].outs.indexOf(edge.source_port),bi=NODE_TYPES[b.type].ins.indexOf(edge.target_port);
   const x1=a.x+232,y1=a.y+94+ai*26,x2=b.x,y2=b.y+94+bi*26,curve=Math.max(65,Math.abs(x2-x1)*0.45);
   const path=document.createElementNS('http://www.w3.org/2000/svg','path');path.setAttribute('d',`M ${x1} ${y1} C ${x1+curve} ${y1}, ${x2-curve} ${y2}, ${x2} ${y2}`);path.dataset.edge=edge.id;path.classList.add('wf-wire');path.setAttribute('tabindex','0');path.setAttribute('role','button');path.setAttribute('aria-label',`Ngắt ${a.type} → ${b.type}`);svg.append(path);
  }
 };
 const drawNodes=()=>{
  if(!model)return;
  $('.wf-nodes').innerHTML=model.graph.nodes.map(node=>{
   const type=NODE_TYPES[node.type],status=nodeStatus(node),rows=Math.max(type.ins.length,type.outs.length);
   return `<article class="wf-node ${selected===node.id?'selected':''} ${status[0]}" data-node="${esc(node.id)}" style="left:${node.x}px;top:${node.y}px" tabindex="0" aria-label="${type.title}"><div class="wf-node-head"><span class="wf-node-icon">${type.icon}</span><strong>${type.title}</strong><span class="wf-state-dot"></span></div><div class="wf-node-summary">${esc(node.config.provider||node.config.voice_id||node.config.preset_id||status[1])}</div><div class="wf-ports">${Array.from({length:rows},(_,i)=>`<div class="wf-port-row">${type.ins[i]?`<button class="wf-socket in ${pending?.target===node.id&&pending?.port===type.ins[i]?'pending':''}" data-direction="in" data-port="${type.ins[i]}" aria-label="${node.type} input ${type.ins[i]}"><i></i>${type.ins[i]}</button>`:'<span></span>'}${type.outs[i]?`<button class="wf-socket out ${pending?.source===node.id&&pending?.port===type.outs[i]?'pending':''}" data-direction="out" data-port="${type.outs[i]}" aria-label="${node.type} output ${type.outs[i]}">${type.outs[i]}<i></i></button>`:'<span></span>'}</div>`).join('')}</div>${node.type==='output'&&currentJob?.output_url?`<div class="wf-result"><video muted preload="metadata" src="${esc(currentJob.output_url)}#t=0.1" aria-label="Video kết quả"></video></div>`:''}<footer>${status[1]}${node.type==='output'&&currentJob?.output_url?` · <a href="${esc(currentJob.output_url)}" target="_blank" rel="noopener">Mở video ↗</a>`:''}</footer></article>`;
  }).join('');drawWires();
 };
 const renderLibrary=()=>{
  $('.wf-library-list').innerHTML=`<h4>MẪU</h4>${library.templates.map((g,i)=>`<button data-template="${i}"><span>◇</span> ${esc(g.name)}</button>`).join('')}<h4>ĐÃ LƯU</h4>${library.items.map(g=>`<div class="wf-saved-row"><button data-workflow="${esc(g.id)}">${esc(g.name)} <small>r${g.revision}</small></button><button data-delete="${esc(g.id)}" aria-label="Xóa ${esc(g.name)}">×</button></div>`).join('')||'<p class="wf-muted">Chưa có workflow đã lưu.</p>'}`;
 };
 const field=(key,label,type='text',options=null,placeholder='')=>{
  const node=model.graph.nodes.find(n=>n.id===selected),value=node.config[key]??'';
  if(type==='checkbox')return `<label class="wf-check"><input data-config="${key}" type="checkbox" ${value!==false?'checked':''}>${label}</label>`;
  if(type==='select')return `<label>${label}<select data-config="${key}" ${key==='batch_size'&&(node.config.provider??currentJob?.request?.image_provider??'flow')!=='flow'?'disabled':''}>${options.map(([v,name])=>`<option value="${v}" ${String(v)===String(value)?'selected':''}>${name}</option>`).join('')}</select></label>`;
  if(type==='textarea')return `<label>${label}<textarea data-config="${key}" rows="7" placeholder="${esc(placeholder)}">${esc(value)}</textarea></label>`;
  return `<label>${label}<input data-config="${key}" type="${type}" value="${esc(value)}" placeholder="${esc(placeholder)}" ${type==='number'?'step="any"':''}></label>`;
 };
 function inspector(){
  if(!model)return;const node=model.graph.nodes.find(n=>n.id===selected);if(!node){$('.wf-inspector').innerHTML='<h3>Thiết lập bước</h3><p class="wf-muted">Chọn một bước trên canvas.</p>';return;}
  let content='';const providerOptions=[['','Theo yêu cầu'],['chatgpt','ChatGPT'],['gemini','Gemini']];
  if(NODE_TYPES[node.type].optional)content+=field('enabled','Bật bước này','checkbox');
  if(node.type==='input')content+=field('workflow_mode','Chế độ','select',[['','Theo yêu cầu'],['research','Nghiên cứu ý tưởng'],['provided_narration','Dùng lời đọc có sẵn']])+field('idea','Ý tưởng / lời đọc','textarea',null,currentJob?.request?.idea||'Nhập ý tưởng hoặc lời đọc ở đây')+field('duration_seconds','Thời lượng (giây)','number',null,currentJob?.request?.duration_seconds||30);
  if(['research','script'].includes(node.type))content+=field('provider','Nhà cung cấp văn bản','select',providerOptions)+'<p class="wf-hint">Các bước văn bản dùng chung kết nối đang cài; chọn cùng nhà cung cấp cho nghiên cứu và kịch bản.</p>';
  if(node.type==='speech')content+=field('voice_id','Giọng đọc','select',[['','Theo yêu cầu'],...voices.map(v=>[v.id,v.name||v.id])])+field('pitch','Cao độ (-12 đến 12)','number',null,'0');
  if(node.type==='images')content+=field('provider','Nhà cung cấp hình ảnh','select',[['flow','Google Flow'],['chatgpt','ChatGPT'],['comfy','ComfyUI']])+field('batch_size','Số cảnh mỗi nhóm Flow','select',batchSizes.map(n=>[n,String(n)]))+field('quality_mode','Chế độ kiểm tra','select',[['','Theo yêu cầu'],['quick','Nhanh'],['careful','Cẩn thận']]);
  if(node.type==='music')content+=field('volume','Âm lượng nhạc (0–1)','number',null,'0.15');
  if(node.type==='render')content+=field('preset_id','Phong cách dựng','select',[['documentary','Tài liệu'],['science','Khoa học'],['everyday','Đời thường']]);
  if(node.type==='research')content+='<p class="wf-hint">Tắt / xóa nghiên cứu sẽ dùng nguyên văn lời đọc có sẵn. Nhập đầy đủ lời đọc, không chỉ ý tưởng.</p>';
  if(node.type==='references')content+='<p class="wf-hint">Tham chiếu nhân vật dùng luồng Google Flow. Nhà cung cấp ảnh khác tạo độc lập; Flow fallback sang Comfy vẫn dùng lại ref đã tải.</p>';
  if(node.type==='music')content+='<p class="wf-hint">Nhạc tạo theo chương. Tắt bước này để không gọi model tạo nhạc.</p>';
  if(node.type==='sfx')content+='<p class="wf-hint">Thư viện âm thanh cục bộ: whoosh, impact, chime, click. Điều chỉnh sự kiện trong Editor.</p>';
  if(node.type==='output'&&currentJob?.output_url)content+=`<video controls src="${esc(currentJob.output_url)}"></video>`;
  content+=`<h4>KẾT NỐI VÀO</h4><div class="wf-connections">${model.graph.edges.filter(e=>e.target===node.id).map(e=>`<button data-disconnect="${esc(e.id)}">${esc(e.source)} → ${esc(e.target_port)} <span>×</span></button>`).join('')||'<p class="wf-muted">Không có đầu vào.</p>'}</div>`;
  $('.wf-inspector').innerHTML=`<div class="wf-inspector-title"><h3>${NODE_TYPES[node.type].title}</h3><code>${esc(node.id)}</code></div>${content}${NODE_TYPES[node.type].optional?'<button data-action="remove" class="wf-danger">Xóa bước</button>':''}`;
 }
 function render(){if(!model)return;$('.wf-name').value=model.graph.name;$('.wf-revision').textContent=`r${model.graph.revision}${model.dirty?' · chưa lưu':''}`;drawNodes();transform();inspector();}
 function load(graph){model=new WorkflowModel(graph);selected=null;pending=null;render();message('Nối các bước và cấu hình, sau đó lưu hoặc chạy.');}
 async function refresh(){library=await request('/api/workflows');renderLibrary();}
 function baseRequest(){return {...(currentJob?.request||{}),idea:currentJob?.request?.idea||'',duration_seconds:currentJob?.request?.duration_seconds||30,voice_id:currentJob?.request?.voice_id||''};}
 async function compile(){const data=await request('/api/workflows/compile',{method:'POST',body:JSON.stringify({graph:model.graph,request:baseRequest()})});return data;}
 async function action(name){
  if(!model||busy)return;
  if(name==='fit'){
   const nodes=model.graph.nodes,minX=Math.min(...nodes.map(n=>n.x)),minY=Math.min(...nodes.map(n=>n.y)),maxX=Math.max(...nodes.map(n=>n.x+250)),maxY=Math.max(...nodes.map(n=>n.y+240));
   const zoom=Math.max(.15,Math.min(1,(stage.clientWidth-60)/(maxX-minX),(stage.clientHeight-60)/(maxY-minY)));model.graph.viewport={x:30-minX*zoom,y:30-minY*zoom,zoom};transform();mutate();return;
  }
  if(name==='clone'){model.clone();render();message('Bản sao mới. Bấm Lưu để thêm vào thư viện.');return;}
  if(name==='remove'){model.remove(selected);selected=null;render();return;}
  if(name==='import'){$('.wf-file').click();return;}
  if(name==='export'){
   const blob=new Blob([JSON.stringify(model.graph,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=(model.graph.name.replace(/[^\p{L}\p{N} _-]/gu,'').slice(0,80)||'workflow')+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),500);return;
  }
  busy=true;const run=$('[data-action="run"]');run.disabled=true;
  try{
   if(name==='save'){const saved=await request('/api/workflows',{method:'POST',body:JSON.stringify({graph:model.graph,revision:model.graph.revision})});model.load(saved);render();await refresh();message(`Đã lưu revision ${saved.revision}.`);}
   if(name==='run'){
    if(typeof onRun!=='function')throw Error('Chưa kết nối trình tạo video');
    const compiled=await compile();message('Graph hợp lệ. Đang tạo tác vụ video…');const result=await onRun(compiled.request);if(result?.id)currentJob=result;drawNodes();message(result?.id?`Đã tạo tác vụ ${result.id}.`:'Đã gửi workflow đến trình tạo video.');
   }
  }finally{busy=false;run.disabled=false;}
 }
 const onClick=event=>invoke(async()=>{
  const actionEl=event.target.closest('[data-action]');if(actionEl){await action(actionEl.dataset.action);return;}
  const template=event.target.closest('[data-template]');if(template){load(library.templates[Number(template.dataset.template)]);return;}
  const stored=event.target.closest('[data-workflow]');if(stored){load(await request('/api/workflows/'+stored.dataset.workflow));return;}
  const del=event.target.closest('[data-delete]');if(del){await request('/api/workflows/'+del.dataset.delete,{method:'DELETE'});await refresh();message('Đã xóa workflow khỏi thư viện.');return;}
  const disconnect=event.target.closest('[data-disconnect]'),wire=event.target.closest('[data-edge]');if(disconnect||wire){model.disconnect(disconnect?.dataset.disconnect||wire.dataset.edge);render();return;}
  const socket=event.target.closest('[data-port]');if(socket){
   const id=socket.closest('[data-node]').dataset.node,port=socket.dataset.port;
   if(socket.dataset.direction==='out'){pending={source:id,port};message(`Đang nối ${id}.${port} — chọn cổng vào cùng kiểu. Escape để hủy.`);}
   else if(pending){model.connect(pending.source,pending.port,id,port);pending=null;message('Đã kết nối.');}
   else {const edge=model.graph.edges.find(e=>e.target===id&&e.target_port===port);if(edge){pending={source:edge.source,port:edge.source_port};model.disconnect(edge.id);message('Chọn cổng vào mới để nối lại.');}}
   drawNodes();inspector();return;
  }
  const card=event.target.closest('[data-node]');if(card){selected=card.dataset.node;drawNodes();inspector();}
 });
 const onChange=event=>invoke(async()=>{
  const el=event.target;
  if(el.matches('.wf-name')){model.graph.name=el.value;mutate();}
  if(el.matches('.wf-add')&&el.value){selected=model.add(el.value).id;el.value='';render();}
  if(el.matches('[data-config]')){
   let value=el.type==='checkbox'?el.checked:el.value;if((el.type==='number'||el.dataset.config==='batch_size')&&value!=='')value=Number(value);
   model.configure(selected,el.dataset.config,value);
   if(el.dataset.config==='provider'&&selected&&model.graph.nodes.find(n=>n.id===selected)?.type==='images'&&value!=='flow'){model.configure(selected,'batch_size',1);const refs=model.graph.nodes.find(n=>n.type==='references');if(refs)model.configure(refs.id,'enabled',false);}
   drawNodes();mutate();if(el.dataset.config==='provider')inspector();
  }
  if(el.matches('.wf-file')&&el.files?.[0]){
   const file=el.files[0];if(file.size>1024*1024)throw Error('Workflow JSON tối đa 1 MB');
   const graph=JSON.parse(await file.text());graph.id='';graph.revision=0;
   // Import validates the graph server-side through the same save route. It does
   // not require a voice/idea, unlike the execution compiler.
   const saved=await request('/api/workflows',{method:'POST',body:JSON.stringify({graph,revision:0})});load(saved);await refresh();message('Đã nhập và lưu workflow.');el.value='';
  }
 });
 const onDown=event=>{
  if(event.button!==0||event.target.closest('button,a,video,input,textarea,select'))return;
  const card=event.target.closest('[data-node]'),rect=stage.getBoundingClientRect();if(!stage.contains(event.target))return;
  if(card){selected=card.dataset.node;const node=model.graph.nodes.find(n=>n.id===selected);drag={kind:'node',id:selected,x:event.clientX,y:event.clientY,startX:node.x,startY:node.y};card.classList.add('selected');inspector();}
  else drag={kind:'pan',x:event.clientX,y:event.clientY,startX:model.graph.viewport.x,startY:model.graph.viewport.y};
  stage.setPointerCapture(event.pointerId);stage.classList.add('dragging');event.preventDefault();
 };
 const onMove=event=>{
  if(!drag||!model)return;const zoom=model.graph.viewport.zoom,dx=event.clientX-drag.x,dy=event.clientY-drag.y;
  if(Math.abs(dx)+Math.abs(dy)<.5&&!drag.changed)return;drag.changed=true;
  if(drag.kind==='node'){model.move(drag.id,Math.round(drag.startX+dx/zoom),Math.round(drag.startY+dy/zoom));const card=Array.from(container.querySelectorAll('[data-node]')).find(el=>el.dataset.node===drag.id);const node=model.graph.nodes.find(n=>n.id===drag.id);if(card){card.style.left=node.x+'px';card.style.top=node.y+'px';}drawWires();}
  else{model.graph.viewport.x=drag.startX+dx;model.graph.viewport.y=drag.startY+dy;transform();}mutate();
 };
 const onUp=event=>{if(drag&&event&&event.type!=='pointercancel')onMove(event);drag=null;stage.classList.remove('dragging');};
 const onWheel=event=>{
  if(!model)return;event.preventDefault();const rect=stage.getBoundingClientRect(),v=model.graph.viewport,next=Math.max(.15,Math.min(2,v.zoom*Math.exp(-event.deltaY*.001))),x=event.clientX-rect.left,y=event.clientY-rect.top;
  v.x=x-(x-v.x)*next/v.zoom;v.y=y-(y-v.y)*next/v.zoom;v.zoom=next;transform();mutate();
 };
 const onKey=event=>{
  if(event.target.matches('input,textarea,select'))return;
  if(event.key==='Escape'){pending=null;drawNodes();message('Đã hủy kết nối.');}
  if((event.key==='Delete'||event.key==='Backspace')&&selected)invoke(()=>action('remove'));
  if(event.key==='Enter'&&event.target.matches('[data-edge]')){model.disconnect(event.target.dataset.edge);render();}
 };
 const onInput=event=>{if(event.target.matches('textarea,input[type=text],input[type=number],.wf-name'))onChange(event);};
 container.addEventListener('click',onClick);container.addEventListener('change',onChange);container.addEventListener('input',onInput);container.addEventListener('keydown',onKey);
 stage.addEventListener('pointerdown',onDown);stage.addEventListener('pointermove',onMove);stage.addEventListener('pointerup',onUp);stage.addEventListener('pointercancel',onUp);stage.addEventListener('wheel',onWheel,{passive:false});
 const ready=(async()=>{
  try{const results=await Promise.allSettled([request('/api/workflows'),request('/api/voices'),request('/api/health')]);if(disposed)return;
   if(results[0].status==='rejected')throw results[0].reason;library=results[0].value;
   if(results[1].status==='fulfilled')voices=results[1].value.voices||[];
   if(results[2].status==='fulfilled')batchSizes=results[2].value.flow_batch_sizes||[1];
   renderLibrary();const initial=job?.request?.workflow||library.templates[0];if(!initial)throw Error('Không có workflow template');load(initial);
  }catch(error){fail(error);}
 })();
 function setJob(value){
  const first=!currentJob;currentJob=value;
  if(first&&model&&!model.dirty&&value?.request){
   const req=value.request;
   if(req.workflow)load(req.workflow);
   else for(const node of model.graph.nodes){
    if(node.type==='input')Object.assign(node.config,{idea:req.idea??'',duration_seconds:req.duration_seconds??30,workflow_mode:req.workflow_mode??'research'});
    if(node.type==='speech')Object.assign(node.config,{voice_id:req.voice_id??'',pitch:req.pitch??0});
    if(node.type==='images')Object.assign(node.config,{provider:req.image_provider??'flow',batch_size:req.flow_batch_size??1});
    if(node.type==='render'&&req.edit_preset)node.config.preset_id=req.edit_preset;
    const flag=req[node.type+'_enabled'];if(typeof flag==='boolean'&&NODE_TYPES[node.type].optional)node.config.enabled=flag;
    if(node.type==='references'&&(req.image_provider??'flow')!=='flow')node.config.enabled=false;
   }
  }
  drawNodes();inspector();
 }
 return {ready,getGraph:()=>model?copy(model.graph):null,isDirty:()=>Boolean(model?.dirty),setJob,
  updateJob(value){currentJob=value;drawNodes();inspector();},load(graph){load(graph);},
  destroy(){disposed=true;container.removeEventListener('click',onClick);container.removeEventListener('change',onChange);container.removeEventListener('input',onInput);container.removeEventListener('keydown',onKey);stage.removeEventListener('pointerdown',onDown);stage.removeEventListener('pointermove',onMove);stage.removeEventListener('pointerup',onUp);stage.removeEventListener('pointercancel',onUp);stage.removeEventListener('wheel',onWheel);container.innerHTML='';}
 };
}
