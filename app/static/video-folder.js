/* Shared by project cards, the video library and both editors. */
(function(global){
  'use strict';
  function videoTarget(value,base){
    try{
      const url=new URL(value,base),home=new URL(base);
      if(url.origin!==home.origin)return null;
      let match=url.pathname.match(/^\/api\/jobs\/([^/]+)\/files\/[^/]+\.mp4$/i);
      if(match)return {job_id:decodeURIComponent(match[1])};
      match=url.pathname.match(/^\/api\/factory\/videos\/([^/]+)\/versions\/([^/]+)\/file$/);
      return match?{job_id:decodeURIComponent(match[1]),version_id:decodeURIComponent(match[2])}:null;
    }catch{return null;}
  }
  global.VideoFolder={videoTarget};
  if(typeof document==='undefined')return;
  function attach(slot,target){
    let button=Array.from(slot.children).find(node=>node.classList?.contains('video-folder-button'));
    if(!button){
      button=document.createElement('button');button.type='button';button.className='button secondary btn btn-sm video-folder-button';button.textContent='Mở thư mục';button.style.margin='4px';
      button.onclick=async()=>{
        button.disabled=true;
        try{
          const response=await fetch('/api/jobs/'+encodeURIComponent(button.dataset.job)+'/open-folder',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(button.dataset.version?{version_id:button.dataset.version}:{})});
          if(!response.ok){const error=await response.json();throw Error(error.detail||'Không mở được thư mục');}
        }catch(error){button.title=error.message;button.textContent=error.message;setTimeout(()=>button.textContent='Mở thư mục',4000);}
        finally{button.disabled=false;}
      };
      slot.append(button);
    }
    button.dataset.job=target.job_id;button.dataset.version=target.version_id||'';
  }
  function scan(){
    for(const link of document.querySelectorAll('a[href]')){
      const target=videoTarget(link.href,location.href);if(target)attach(link.parentElement,target);
    }
    for(const video of document.querySelectorAll('video[src],video source[src]')){
      const target=videoTarget(video.getAttribute('src'),location.href);if(!target)continue;
      const player=video.tagName==='SOURCE'?video.parentElement:video;
      const figure=player.closest('figure');
      const slot=figure?.querySelector('figcaption')||player.parentElement;
      if(!slot.querySelector('.video-folder-button'))attach(slot,target);
    }
  }
  let pending=false;
  new MutationObserver(()=>{if(!pending){pending=true;queueMicrotask(()=>{pending=false;scan();});}}).observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['src','href']});
  scan();
})(globalThis);
