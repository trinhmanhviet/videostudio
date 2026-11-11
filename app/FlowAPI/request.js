const $=id=>document.getElementById(id);
let receiptId=sessionStorage.getItem('flow-request:last')||null;
let checking=false;
async function api(path,body){
  const response=await fetch('/api/flow-request'+path,{cache:'no-store',signal:AbortSignal.timeout(12000),...(body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})});
  const value=await response.json();if(!response.ok){const error=Error(value.detail||'Không nối được hệ thống');error.httpStatus=response.status;throw error;}return value;
}
function fields(){
  const op=$('operation').value;
  $('project-field').hidden=['list_projects','create_project'].includes(op);
  $('name-field').hidden=!['create_project','create_character','rename_character'].includes(op);
  $('character-field').hidden=op!=='rename_character';
  $('generation-fields').hidden=op!=='generate_image';
}
async function refresh(){
  try{
    const status=await api('/status');const old=$('client').value;
    $('client').replaceChildren();
    for(const client of status.clients){
      const item=document.createElement('option');item.value=client.client_id;item.textContent=`${client.session_ready?'Sẵn sàng':'Chờ phiên Flow'} · ${client.client_id.slice(0,8)} · ${client.age_seconds}s`;item.disabled=!client.connected||!client.enabled||!client.session_ready;$('client').append(item);
    }
    if([...$('client').options].some(x=>x.value===old&&!x.disabled))$('client').value=old;
    else $('client').value=[...$('client').options].find(x=>!x.disabled)?.value||'';
    const ready=status.clients.some(x=>x.connected&&x.enabled&&x.session_ready);
    $('connection').textContent=ready?'Đã nối extension với một phiên Flow.':'Chưa có phiên Flow sẵn sàng. Kết nối extension; nếu mới cài thì F5 tab Flow một lần để đọc phiên.';
  }catch(error){$('connection').textContent=error.message;}
}
function show(receipt){
  $('state').textContent=`${receipt.id} · ${receipt.state}`;
  $('result').textContent=receipt.result?JSON.stringify(receipt.result,null,2):'Đang chờ extension nhận request…';
  $('images').replaceChildren();
  for(const image of receipt.result?.images||[]){
    const link=document.createElement('a');link.href=image.url;link.target='_blank';link.rel='noopener noreferrer';link.textContent=`Mở ảnh ${image.width} × ${image.height}`;
    $('images').append(link,document.createElement('br'));
  }
  if(receipt.operation==='create_project'&&receipt.result?.project_id)$('project').value=receipt.result.project_id;
  if(receipt.operation==='create_character'&&receipt.result?.character_id)$('character').value=receipt.result.character_id;
  if(receipt.result?.projects?.length){
    const list=document.createElement('div');
    for(const project of receipt.result.projects){
      const button=document.createElement('button');button.type='button';button.textContent=project.name;
      button.onclick=()=>{$('project').value=project.project_id;};list.append(button);
    }
    $('images').append(list);
  }
  $('check').hidden=false;
  $('send').disabled=['queued','dispatching'].includes(receipt.state);
}
async function check(){
  if(!receiptId||checking)return;checking=true;
  try{show(await api('/commands/'+encodeURIComponent(receiptId)));}catch(error){$('error').textContent=error.message;if(error.httpStatus===404)$('send').disabled=false;}finally{checking=false;}
}
$('invite').onclick=async()=>{try{const invitation=await api('/invitation',{});$('code').textContent=invitation.code+' (5 phút)';}catch(error){$('error').textContent=error.message;}};
$('operation').onchange=fields;
$('check').onclick=check;
$('request-form').onsubmit=async event=>{
  event.preventDefault();$('error').textContent='';$('send').disabled=true;
  let posted=false;
  try{
    const op=$('operation').value;const args={};
    if(!['list_projects','create_project'].includes(op))args.project_id=$('project').value.trim();
    if(['create_project','create_character','rename_character'].includes(op))args.name=$('name').value.trim();
    if(op==='rename_character')args.character_id=$('character').value.trim();
    if(op==='generate_image'){
      if(!$('confirm').checked)throw Error('Hãy xác nhận tạo một ảnh thật trước khi gửi.');
      args.prompt=$('prompt').value;args.references=JSON.parse($('references').value||'[]');
      if($('target-character').value.trim())args.target_character_id=$('target-character').value.trim();
    }
    if(!$('client').value)throw Error('Chưa có extension Flow sẵn sàng.');
    const id=crypto.randomUUID();receiptId=id;sessionStorage.setItem('flow-request:last',id);
    // Save the ID before POST: a lost HTTP reply is reconciled through GET, never another POST.
    $('check').hidden=false;
    posted=true;
    show(await api('/commands',{id,client_id:$('client').value,operation:op,arguments:args,confirm_generation:$('confirm').checked}));
  }catch(error){
    const uncertain=posted&&!error.httpStatus;
    $('error').textContent=uncertain?'Mất phản hồi gửi lệnh. Đang đối chiếu cùng request ID; chưa gửi lệnh mới.':error.message;
    $('send').disabled=uncertain;
  }
};
fields();refresh();check();setInterval(()=>{refresh();check();},4000);
