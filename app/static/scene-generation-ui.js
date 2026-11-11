/* ChatGPT scene-image candidates. Creating is never the same action as applying. */
(() => {
  'use strict';
  const node=(tag,text,cls)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;};
  const labels={queued:'Đang chờ lượt',running:'Đang tạo / lấy ảnh trên ChatGPT',completed:'Ảnh ứng viên sẵn sàng, chưa thay ảnh cảnh',applied:'Bạn đã dùng ảnh này',uncertain:'Chưa xác nhận kết quả; không tự gửi lại',needs_auth:'Chrome riêng cần đăng nhập / xác minh',failed:'Không tạo hoặc lấy được ảnh',cancelled:'Đã dừng chờ trong tool; ChatGPT có thể vẫn tạo tiếp'};
  window.createSceneGenerationPanel=(scene,fit,ctx)=>{
    const root=node('details',undefined,'se-generation');const summary=node('summary','Tạo lại bằng ChatGPT');root.append(summary);
    const panel=node('div',undefined,'se-generation-body');root.append(panel);
    panel.append(node('p','Sửa mô tả sai trước khi tạo. Chỉ gửi mô tả bằng chữ tới ChatGPT qua Chrome riêng; ảnh cảnh không bị thay cho đến khi bạn chọn dùng.','muted'));
    const prompt=node('textarea');prompt.value=scene.visual_prompt||'';prompt.maxLength=12000;prompt.rows=4;prompt.setAttribute('aria-label',`Mô tả tạo lại ảnh cảnh ${scene.index+1}`);panel.append(prompt);
    const generate=node('button','Tạo ảnh ứng viên');generate.type='button';panel.append(generate);
    panel.append(node('small','Dùng hạn mức ảnh của tài khoản ChatGPT. Không dùng API trả phí. Google Flow chưa bật.','se-generation-note'));
    const status=node('div',undefined,'se-generation-status');status.setAttribute('role','status');panel.append(status);
    const list=node('div',undefined,'se-generation-list');panel.append(list);
    const path='/scenes/'+encodeURIComponent(scene.scene_id)+'/generations';const endpoint=ctx.base+path;
    let submitting=false,polling=false,timer=null,requestIdentity=null,loaded=false;
    const active=()=>root.isConnected&&ctx.isOpen();
    const later=()=>{clearTimeout(timer);if(active()&&root.open)timer=setTimeout(refresh,2500);};
    async function taskAction(task,action){
      if(!active()||submitting)return;submitting=true;
      try{await ctx.request(endpoint+'/'+encodeURIComponent(task.id)+'/'+action,{method:'POST',body:'{}'});if(active())await refresh();}
      catch(e){if(active())status.textContent=e.message;}finally{submitting=false;if(active())refresh();}
    }
    function draw(tasks){
      const pending=tasks.some(t=>['queued','running','uncertain','needs_auth'].includes(t.state));generate.disabled=pending||submitting||!ctx.editable();
      list.replaceChildren(...tasks.map(t=>{
        const card=node('section',undefined,'se-generation-result');card.append(node('strong',labels[t.state]||t.state));
        if(t.error)card.append(node('p',t.error,'error'));
        if(t.image_url){
          const image=node('img');image.src=t.image_url;image.alt=`Ảnh ứng viên ChatGPT cho cảnh ${scene.index+1}`;image.loading='lazy';image.className='se-generated-image';card.append(image);
          if(t.state==='completed'){
            const apply=node('button','Dùng ảnh ChatGPT này');apply.type='button';apply.onclick=()=>{if(active())ctx.apply(path+'/'+encodeURIComponent(t.id)+'/apply');};card.append(apply);
          }
        }
        if(['uncertain','needs_auth'].includes(t.state)){
          const resume=node('button','Kiểm tra lại yêu cầu cũ','secondary');resume.type='button';resume.onclick=()=>taskAction(t,'resume');card.append(resume);
          card.append(node('small','Đăng nhập/xác minh trong cửa sổ Chrome riêng nếu được yêu cầu. Nút này khôi phục mã yêu cầu cũ, không yêu cầu tạo ảnh mới.','se-generation-note'));
        }
        if(['queued','running','uncertain','needs_auth'].includes(t.state)){
          const cancel=node('button','Dừng chờ trong tool','secondary');cancel.type='button';cancel.onclick=()=>taskAction(t,'cancel');card.append(cancel);
        }
        return card;
      }));
      if(tasks.some(t=>['queued','running'].includes(t.state)))later();
    }
    async function refresh(){
      if(!active()||polling)return;polling=true;
      try{const d=await ctx.request(endpoint);if(active()){draw(d.items||[]);loaded=true;}}
      catch(e){if(active())status.textContent=e.message;}finally{polling=false;}
    }
    root.ontoggle=()=>{clearTimeout(timer);if(root.open){if(!loaded)status.textContent='Đang nạp các yêu cầu tạo ảnh...';refresh().then(()=>{if(active()&&loaded)status.textContent='Ảnh tạo lại là ứng viên; bạn quyết định có dùng hay không.';});}};
    generate.onclick=async()=>{
      if(submitting||!ctx.editable())return;const text=prompt.value.trim();if(!text){status.textContent='Nhập mô tả ảnh cần tạo trước.';return;}
      const version=ctx.version(),identity=JSON.stringify({prompt:text,version,scene:scene.scene_id});if(!requestIdentity||requestIdentity.identity!==identity)requestIdentity={identity,key:crypto.randomUUID()};
      submitting=true;generate.disabled=true;status.textContent='Đang xếp yêu cầu tạo ảnh...';
      try{
        await ctx.request(endpoint,{method:'POST',headers:{'Idempotency-Key':requestIdentity.key},body:JSON.stringify({prompt:text,provider:'chatgpt',version})});
        requestIdentity=null;
        if(active()){status.textContent='Đã lưu yêu cầu. Bạn có thể đóng cửa sổ và quay lại xem kết quả.';await refresh();}
      }catch(e){if(active()){status.textContent=e.message;await refresh();}}
      finally{submitting=false;if(active()){refresh();later();}}
    };
    return root;
  };
})();
