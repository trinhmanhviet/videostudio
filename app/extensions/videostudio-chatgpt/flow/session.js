// Observe only session metadata from the page's own RPCs. Never copy Cookie,
// authorization headers, browser-validation headers, or generation challenge tokens.
(() => {
  if (location.origin !== 'https://flow.google.com') return;
  const symbol=Symbol.for('videostudio.flow.session.v1');
  if(globalThis[symbol])return;
  const state={at:null,sid:null,build:null,language:'vi',nativeFetch:globalThis.fetch.bind(globalThis),observedAt:0};
  Object.defineProperty(globalThis,symbol,{value:state});
  function capture(url,body){
    try{
      const parsed=new URL(url,location.href);
      if(parsed.origin!==location.origin||parsed.pathname!=='/_/AiSandboxAngularFrontend/data/batchexecute')return;
      const form=typeof body==='string'||body instanceof URLSearchParams?new URLSearchParams(body):null;
      if(form?.get('at'))state.at=form.get('at');
      if(parsed.searchParams.get('f.sid'))state.sid=parsed.searchParams.get('f.sid');
      if(parsed.searchParams.get('bl'))state.build=parsed.searchParams.get('bl');
      if(parsed.searchParams.get('hl'))state.language=parsed.searchParams.get('hl');
      state.observedAt=Date.now();
    }catch{}
  }
  const original=globalThis.fetch;
  globalThis.fetch=function(input,init){
    try{
      const url=typeof input==='string'||input instanceof URL?String(input):input.url;
      if(init?.body!==undefined)capture(url,init.body);
      else if(typeof Request!=='undefined'&&input instanceof Request){
        const parsed=new URL(url,location.href);
        if(parsed.origin===location.origin&&parsed.pathname==='/_/AiSandboxAngularFrontend/data/batchexecute')input.clone().text().then(body=>capture(url,body)).catch(()=>{});
      }else capture(url,null);
    }catch{}
    return Reflect.apply(original,this,arguments);
  };
  const open=XMLHttpRequest.prototype.open,send=XMLHttpRequest.prototype.send;
  const urls=new WeakMap();
  XMLHttpRequest.prototype.open=function(method,url){urls.set(this,String(url));return Reflect.apply(open,this,arguments);};
  XMLHttpRequest.prototype.send=function(body){capture(urls.get(this),body);return Reflect.apply(send,this,arguments);};
})();
