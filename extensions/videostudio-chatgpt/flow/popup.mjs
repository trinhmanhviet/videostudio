const $=id=>document.getElementById(id);
async function send(message){const response=await chrome.runtime.sendMessage(message);if(response?.error)throw Error(response.error);return response;}
async function status(){
  const result=await send({kind:'flow:status'});
  if(result.config){$('server').value=result.config.server;$('tab').value=String(result.config.tab);}
  const state=result.status;
  $('status').textContent=state?.error||(!result.config?'Chưa kết nối.':!result.config.enabled?'Đã ngừng nhận lệnh.':state?.session_ready?'Đã đọc được phiên Flow.':state?.tab_open?'Đã nối; chờ trang Flow phát request để đọc phiên.':'Không tìm thấy tab Flow đã chọn.');
}
async function action(kind){
  for(const button of document.querySelectorAll('button'))button.disabled=true;
  try{
    if(kind==='connect'){
      const origins=['https://flow.google.com/*'];
      if($('server').value!=='http://localhost:8877')origins.push($('server').value+'/*');
      const granted=await chrome.permissions.request({permissions:['scripting'],origins});
      if(!granted)throw Error('Cần cho phép VideoStudio truy cập Flow để gửi request.');
    }
    await send({kind:'flow:'+kind,...(kind==='connect'?{server:$('server').value,tab:Number($('tab').value),code:$('code').value.trim()}:{})});await status();
  }
  catch(error){$('status').textContent=error.message;}
  finally{for(const button of document.querySelectorAll('button'))button.disabled=false;}
}
let flowTabs=[];
try{flowTabs=await chrome.tabs.query({url:'https://flow.google.com/*'});}catch{}
for(const tab of flowTabs){
  const option=document.createElement('option');option.value=String(tab.id);option.textContent=tab.title||tab.url;$('tab').append(option);
}
// Before the optional host grant Chrome may conceal tab URLs. The user opens
// this popup from Flow; its current tab ID is available without broad tabs access.
if(!$('tab').options.length){
  const [tab]=await chrome.tabs.query({active:true,currentWindow:true});
  if(tab){const option=document.createElement('option');option.value=String(tab.id);option.textContent='Tab hiện tại (mở Flow trước khi kết nối)';$('tab').append(option);}
}
$('connect').onclick=()=>action('connect');$('sync').onclick=()=>action('sync');$('stop').onclick=()=>action('stop');
status().catch(error=>{$('status').textContent=error.message;});
