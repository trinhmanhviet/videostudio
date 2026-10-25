const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('C:/Users/leath/AppData/Local/Programs/aicoworker/resources/openclaw/node_modules/playwright-core');
const root=path.resolve(__dirname,'..');
const screenshot='C:/Users/leath/aicoworker/openclaw/workspace-main/tmp/editor-pagination-1280.png';
(async()=>{
 const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
 try{
 const page=await browser.newPage({viewport:{width:1280,height:900}});page.setDefaultTimeout(6000);
 let view={job_id:'fixture',version:0,editable:true,scenes:Array.from({length:196},(_,i)=>({scene_id:'s'+i,index:i,start:i*3,duration:3,narration:'Lời đọc mẫu được giữ nguyên.',visual_prompt:'Original prompt '+i,image_url:'/picture?edit=original',audio_url:'/audio',edit_id:'original',history:[{id:'old'+i,created:1,provider:'upload'}]}))};
 let posts=0,gets=0,fail=false,release=null,releasePoll=null,delayPoll=false,recovery=true,resumed=0,generations=0,submittedProvider=null;const errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',async route=>{const req=route.request(),u=new URL(req.url()),p=u.pathname;
 if(p==='/')return route.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(root,'static/index.html'),'utf8')});
 if(p.endsWith('.js'))return route.fulfill({contentType:'text/javascript',body:fs.readFileSync(path.join(root,'static',p.slice(1)),'utf8')});
 if(p==='/api/projects')return route.fulfill({json:{items:[]}});
 if(p==='/api/jobs')return route.fulfill({json:[]});
 if(p==='/api/voices')return route.fulfill({json:{items:[]}});
 if(p==='/api/preflight'||p==='/api/browser/status')return route.fulfill({json:{ready:false,checks:[]}});
 if(p.endsWith('/scene-editor'))return route.fulfill({json:view});
 if(p.endsWith('/resume')){resumed++;recovery=false;return route.fulfill({json:{id:'pending',state:'queued'}});}
 if(p.endsWith('/generations')){
  if(req.method()==='POST'){generations++;submittedProvider=req.postDataJSON().provider;return route.fulfill({status:202,json:{id:'new',state:'queued',provider:submittedProvider}});}
  gets++;if(recovery&&p.includes('/s1/'))return route.fulfill({json:{items:[{id:'pending',state:'uncertain',error:'Needs recovery'}]}});if(delayPoll&&p.includes('/s12/')){delayPoll=false;await new Promise(r=>releasePoll=r);return route.fulfill({json:{items:[{id:'late',state:'completed',image_url:'/late',created:1}]}});}
  return route.fulfill({json:{items:[{id:'cand',state:'completed',image_url:'/candidate',created:1}]}});
 }
 if(p.endsWith('/restore')||p.endsWith('/apply')){
  posts++;const b=req.postDataJSON(),sid=p.match(/scenes\/(s\d+)/)[1];assert.equal(b.version,view.version);
  await new Promise(r=>release=r);
  if(fail)return route.fulfill({status:409,json:{detail:'Stale editor version'}});
  const row=view.scenes.find(x=>x.scene_id===sid);row.edit_id=p.endsWith('/apply')?'applied':b.edit_id;row.image_url='/picture?edit='+row.edit_id;row.history.push({id:row.edit_id,created:2,provider:'chatgpt'});view.version++;
  return route.fulfill({json:view});
 }
 if(p==='/audio')return route.fulfill({body:''});
 return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="90" height="160"><rect width="90" height="160" fill="#406047"/></svg>'});
 });
 await page.goto('http://localhost:9881/');
 await page.evaluate(()=>{document.querySelector('#viewGallery').hidden=true;document.querySelector('#viewWorkspace').hidden=false;document.querySelector('#idea').value='workspace draft';window.scrollTo(0,150);});
 await page.evaluate(()=>openSceneEditor('fixture'));
 await page.waitForFunction(()=>document.querySelectorAll('.se-history-select option[value="candidate:cand"]').length===11);
 assert.equal(await page.locator('.se-card').count(),12);assert.equal(await page.locator('.se-thumb-wrap').count(),0);assert.equal(gets,12);
 await page.locator('.se-recovery').filter({hasText:'Kiểm tra yêu cầu cũ'}).click();await page.waitForFunction(()=>document.querySelectorAll('.se-recovery').length===0);assert.equal(resumed,1);
 let geometry=await page.evaluate(()=>({main:document.querySelector('main').getBoundingClientRect().width,columns:getComputedStyle(document.querySelector('.se-grid')).gridTemplateColumns.split(' ').length}));assert.equal(geometry.columns,4);assert.equal(Math.round(geometry.main),1024);
 const first=page.locator('.se-card').first(),select=first.locator('select.se-history-select');
 await first.locator('.se-prompt-toggle').click();await first.locator('textarea').fill('Saved draft');
 const before=await page.evaluate(()=>{window.__other=document.querySelectorAll('.se-card')[1];window.__first=document.querySelector('.se-card');return performance.now();});
 await select.selectOption('old0');
 await page.waitForFunction(()=>!!document.querySelector('.se-main-image').getAttribute('src').includes('edit=old0'));
 const feedbackMs=await page.evaluate(t=>performance.now()-t,before);assert.ok(feedbackMs<1000,'preview before server response');
 await page.waitForFunction(()=>document.querySelector('.se-card-status').textContent.includes('Đang lưu'));
 assert.equal(posts,1);release();await page.waitForFunction(()=>document.querySelector('#sePageMessage').textContent==='Đã lưu ảnh đã chọn.');
 assert.equal(await page.evaluate(()=>window.__other===document.querySelectorAll('.se-card')[1]&&window.__first===document.querySelector('.se-card')),true,'no card rebuild');
 fail=true;await select.selectOption('original');await page.waitForFunction(()=>document.querySelector('.se-main-image').src.includes('edit=original'));release();await page.waitForFunction(()=>document.querySelector('#sePageMessage').textContent.includes('Không lưu'));assert.equal(await select.inputValue(),'old0');assert.ok((await first.locator('img').first().getAttribute('src')).includes('old0'));
 fail=false;await select.selectOption('candidate:cand');await page.waitForFunction(()=>document.querySelector('.se-main-image').getAttribute('src')==='/candidate');await new Promise(r=>setImmediate(r));assert.equal(posts,3);release();await page.waitForFunction(()=>document.querySelector('#sePageMessage').textContent==='Đã lưu ảnh đã chọn.');assert.equal(posts,3);assert.equal(await select.inputValue(),'applied');
 delayPoll=true;await page.locator('#seNextPage').click();await page.waitForFunction(()=>document.querySelector('.se-card').dataset.sceneId==='s12');await page.waitForFunction(()=>document.querySelectorAll('.se-card').length===12);
 await page.locator('#sePrevPage').click();if(releasePoll)releasePoll();await page.waitForFunction(()=>document.querySelector('.se-card').dataset.sceneId==='s0');
 assert.equal(await page.locator('.se-card').first().locator('textarea').inputValue(),'Saved draft');assert.equal(await page.locator('.se-prompt-box').first().isVisible(),true);assert.equal(await page.locator('option[value="candidate:late"]').count(),0);
 await page.evaluate(()=>window.scrollTo(0,500));const editorScroll=await page.evaluate(()=>scrollY);
 await page.locator('#btnBackFromEditor').evaluate(e=>e.click());await page.waitForFunction(()=>document.querySelector('#viewSceneEditor').hidden);assert.equal(await page.locator('#viewWorkspace').isVisible(),true);assert.equal(await page.locator('#idea').inputValue(),'workspace draft');
 await page.evaluate(()=>openSceneEditor('fixture'));await page.waitForFunction(()=>scrollY>300);assert.ok(Math.abs((await page.evaluate(()=>scrollY))-editorScroll)<3);assert.equal(await page.locator('textarea.se-prompt-input').first().inputValue(),'Saved draft');
 await page.goBack();await page.waitForFunction(()=>document.querySelector('#viewSceneEditor').hidden);await page.goForward();await page.waitForFunction(()=>!document.querySelector('#viewSceneEditor').hidden);
 await page.locator('.se-card').first().locator('input[value="comfy"]').check();assert.equal(await page.locator('.se-card').first().locator('input[value="comfy"]').isChecked(),true);await page.locator('.se-card').first().locator('button').filter({hasText:'Vẽ lại'}).click();assert.equal(generations,1);assert.equal(submittedProvider,'comfy');await page.waitForFunction(()=>!document.querySelector('#sePageExport').disabled);
 for(let i=0;i<16;i++)await page.locator('#seNextPage').click();assert.equal(await page.locator('.se-card').count(),4);assert.ok((await page.locator('#sePageNumber').textContent()).includes('17 / 17'));
 for(let i=0;i<16;i++)await page.locator('#sePrevPage').click();
 await page.evaluate(()=>window.scrollTo(0,200));await page.screenshot({path:screenshot});
 for(const width of [390,768,1920]){await page.setViewportSize({width,height:900});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);}
 assert.deepEqual(errors,[]);console.log(JSON.stringify({passed:true,scenes:196,rendered:12,columns:geometry.columns,width:geometry.main,initialCandidateGets:12,mutationPosts:posts,previewFeedbackMs:Math.round(feedbackMs),screenshot}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
