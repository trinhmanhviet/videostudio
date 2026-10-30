(()=>{
  const header=document.querySelector('main > header');if(!header||document.getElementById('chromeProfileControls'))return;
  const panel=document.createElement('section');panel.id='chromeProfileControls';panel.className='card';panel.style.cssText='margin:12px 0;padding:14px';
  panel.innerHTML='<div class="row" style="justify-content:space-between"><strong>Chrome riêng · Google Flow</strong><button type="button" class="secondary" data-action="refresh">Kiểm tra Chrome</button></div><p data-role="state" role="status" aria-live="polite">Đang kiểm tra Chrome riêng…</p><div class="row"><button type="button" class="secondary" data-mode="clean">Mở sạch</button><button type="button" data-mode="debug">Mở debug</button><button type="button" class="secondary" data-action="stop">Tắt Chrome riêng</button></div><p class="notice" data-role="help">Sạch để đăng nhập Google; debug để tool tạo ảnh. Cùng một profile, giữ tài khoản và dữ liệu. Đổi chế độ sẽ đóng cửa sổ Chrome riêng hiện tại.</p><p class="error" data-role="error" role="alert" hidden></p>';
  header.after(panel);
  const q=selector=>panel.querySelector(selector),buttons=[...panel.querySelectorAll('[data-mode],[data-action="stop"]')];
  let state=null,busy=false;
  function render(){
    q('[data-role="state"]').textContent=busy?'Đang thay đổi Chrome riêng…':!state?'Chưa đọc được trạng thái Chrome riêng.':state.mode==='clean'?'Đang mở sạch để đăng nhập. Chọn Mở debug trước khi dùng Flow.':state.mode==='debug'?(state.debug_ready?'Đang mở debug · sẵn sàng cho tool điều khiển.':'Đang mở debug · chờ kết nối sẵn sàng.'):'Chrome riêng đang tắt.';
    for(const button of buttons)button.disabled=busy||!state||state.can_change===false||state.busy===true;
    q('[data-action="stop"]').disabled||=state?.running===false;
    q('[data-action="refresh"]').disabled=busy;
    if(state?.active_jobs)q('[data-role="state"]').textContent+=' Có video đang chạy; chờ xong hoặc hủy trước khi tắt/đổi chế độ.';
  }
  async function request(path,options={}){
    const response=await fetch(path,{...options,headers:{'Content-Type':'application/json'},signal:AbortSignal.timeout(45000)});
    const data=await response.json();if(!response.ok)throw Error(data.detail||'Không điều khiển được Chrome riêng.');return data;
  }
  function error(message){const node=q('[data-role="error"]');node.textContent=message||'';node.hidden=!message;}
  async function refresh(){
    if(busy)return;
    try{state=await request('/api/browser/profile');error('');}catch(e){error(e.message);}
    render();
  }
  async function control(mode){
    if(busy)return;busy=true;error('');render();
    try{state=await request('/api/browser/profile/'+(mode==='stop'?'stop':'open'),{method:'POST',body:mode==='stop'?'{}':JSON.stringify({mode})});}
    catch(e){error(e.message);}finally{busy=false;render();}
  }
  for(const button of buttons)button.addEventListener('click',()=>void control(button.dataset.mode||'stop'));
  q('[data-action="refresh"]').addEventListener('click',()=>void refresh());
  document.querySelector('#create')?.addEventListener('submit',event=>{
    const needsBrowser=['flow','chatgpt'].includes(document.querySelector('#imageProvider')?.value);
    if(!busy&&!state?.busy&&!(needsBrowser&&state?.mode==='clean'))return;
    event.preventDefault();event.stopImmediatePropagation();
    const message=busy||state?.busy?'Chờ Chrome riêng đổi chế độ xong rồi tạo video.':'Chrome riêng đang mở sạch. Bấm Mở debug trước khi tạo ảnh Flow/ChatGPT; tài khoản đã đăng nhập được giữ nguyên.';
    error(message);const notice=document.querySelector('#submitError');if(notice)notice.textContent=message;
    q('[data-mode="debug"]').focus();
  },true);
  void refresh();setInterval(()=>void refresh(),10000);
})();
