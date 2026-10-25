/* Isolated UI regression. All generation/apply calls mocked, no account use. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require(process.env.VS_PLAYWRIGHT_PATH||'C:/Users/leath/AppData/Local/Programs/aicoworker/resources/openclaw/node_modules/playwright-core');
const root=path.resolve(__dirname,'..');const out=process.env.VS_GENERATION_EVIDENCE||path.join(root,'data/generation-ui-smoke');fs.mkdirSync(out,{recursive:true});
(async()=>{const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});try{
 for(const width of [390,1280]){
  const context=await browser.newContext({viewport:{width,height:800},isMobile:width<600,hasTouch:width<600});const page=await context.newPage();page.on('pageerror',e=>console.error('PAGE ERROR',e.message));page.on('response',r=>{if(r.url().includes('generations'))console.log('TASK HTTP',r.status(),r.url());});let submissions=0,applied=0,task=null;
  const view={job_id:'fixture',version:0,mode:'quick',editable:true,scenes:[{scene_id:'s-one',index:0,start:0,end:3,duration:3,narration:'Một cảnh mẫu, giữ lời đọc và thời lượng.',visual_prompt:'A red apple on a table, no text',image_url:'/original?edit=original',audio_url:'/audio',image_sha256:'original',edit_id:'original',fit:'original',review_status:'needs_review',history:[]}]};
  await page.route('http://localhost:9881/**',async route=>{const req=route.request(),u=new URL(req.url());
   if(u.pathname==='/')return route.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(root,'static/index.html'),'utf8').split('</head>')[0]+'</head><body></body></html>'});
   if(u.pathname==='/original'||u.pathname==='/candidate')return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="360" height="640"><rect width="360" height="640" fill="'+(u.pathname==='/original'?'#53664b':'#843b28')+'"/><text x="30" y="300" fill="white" font-size="28">'+(u.pathname==='/original'?'Original scene':'Candidate')+'</text></svg>'});
   if(u.pathname.endsWith('/scene-editor'))return route.fulfill({json:view});
   if(u.pathname.endsWith('/generations')){
    if(req.method()==='POST'){submissions++;const b=req.postDataJSON();assert.equal(b.provider,'chatgpt');assert.ok(b.prompt.includes('red apple'));task={id:'candidate-one',state:'queued',provider:'chatgpt',prompt:b.prompt};return route.fulfill({status:202,json:task});}
    if(task)task={...task,state:'completed',image_url:'/candidate'};return route.fulfill({json:{items:task?[task]:[]}});
   }
   if(u.pathname.endsWith('/candidate-one/apply')){applied++;assert.equal(req.postDataJSON().version,0);view.version=1;view.scenes[0]={...view.scenes[0],image_url:'/candidate?selected=true',edit_id:'generated-edit',image_sha256:'candidate'};return route.fulfill({json:view});}
   return route.fulfill({status:404,body:'fixture route unavailable'});
  });
  await page.goto('http://localhost:9881/');await page.addScriptTag({path:path.join(root,'static/scene-generation-ui.js')});await page.addScriptTag({path:path.join(root,'static/scene-editor.js')});await page.evaluate(()=>openSceneEditor('fixture'));await page.locator('.se-card').waitFor();
  await page.locator('.se-generation summary').click();const create=page.getByRole('button',{name:'Tạo ảnh ứng viên',exact:true});await create.click();const use=page.getByRole('button',{name:'Dùng ảnh ChatGPT này',exact:true});await use.waitFor();assert.equal(submissions,1);assert.equal(applied,0,'generating never applies implicitly');
  await page.screenshot({path:path.join(out,`candidate-${width}.png`)});await use.click();await page.waitForFunction(()=>document.querySelector('.se-image').getAttribute('src').includes('selected=true'));assert.equal(applied,1);assert.equal(view.scenes[0].duration,3);assert.equal(view.scenes[0].narration,'Một cảnh mẫu, giữ lời đọc và thời lượng.');
  const top=await page.locator('.se-top').boundingBox();assert.ok(top.height<150,'mobile header stays compact');console.log(JSON.stringify({width,submissions,applied,header:top.height,sceneDuration:view.scenes[0].duration}));await context.close();
 }
}finally{await browser.close()}})().catch(e=>{console.error(e);process.exitCode=1});
