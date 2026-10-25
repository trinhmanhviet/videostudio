/* Real Chromium layout regression, isolated context and mocked media/mutations.
   Uses the app's shipped playwright-core; never attaches to a user's Chrome. */
const fs=require('node:fs');const path=require('node:path');const assert=require('node:assert/strict');
const {chromium}=require(process.env.VS_PLAYWRIGHT_PATH||'C:/Users/leath/AppData/Local/Programs/aicoworker/resources/openclaw/node_modules/playwright-core');
const root=path.resolve(__dirname,'..');
const evidence=process.env.VS_LAYOUT_EVIDENCE||path.join(root,'data','mobile-layout');fs.mkdirSync(evidence,{recursive:true});
const fixture={job_id:'layout-fixture',version:0,mode:'quick',editable:true,state:'completed',scenes:[0,1,2].map(i=>({scene_id:'scene-'+i,index:i,start:i*3,end:(i+1)*3,duration:3,narration:'Lời đọc cảnh '+(i+1)+' được giữ nguyên khi thay ảnh.',image_url:'/fixture-image',audio_url:'/fixture-audio',image_sha256:'fixture',edit_id:'original',fit:'original',review_status:'needs_review',history:[]}))};
(async()=>{
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
try{
 const results=[];
 for(const [width,height] of [[390,740],[360,640],[480,800],[844,390],[1280,900]]){
  const context=await browser.newContext({viewport:{width,height},isMobile:width<900,deviceScaleFactor:1,hasTouch:width<900});const page=await context.newPage();
  const head=fs.readFileSync(path.join(root,'static/index.html'),'utf8').split('</head>')[0]+'</head>';
  await page.route('http://layout.test/**',async route=>{
   const url=new URL(route.request().url());
   if(url.pathname==='/')return route.fulfill({contentType:'text/html',body:head+'<body><main>Isolated editor layout fixture</main></body></html>'});
   if(url.pathname==='/fixture-image')return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="360" height="640"><rect width="360" height="640" fill="#42583a"/><text x="40" y="320" fill="white" font-size="28">Scene image</text></svg>'});
   if(url.pathname.endsWith('/scene-editor'))return route.fulfill({json:fixture});
   return route.fulfill({status:404,body:'fixture endpoint not implemented'});
  });
  await page.goto('http://layout.test/');await page.addScriptTag({path:path.join(root,'static/scene-editor.js')});await page.evaluate(()=>openSceneEditor('layout-fixture'));await page.locator('.se-card').first().waitFor();
  const measures=()=>page.evaluate(()=>{const rect=s=>{const r=document.querySelector(s).getBoundingClientRect();return {top:r.top,bottom:r.bottom,height:r.height,width:r.width}};const image=rect('.se-image'),top=rect('.se-top'),shell=rect('.se-shell');return {viewport:{width:innerWidth,height:innerHeight},image,top,shell,visibleImage:Math.max(0,Math.min(image.bottom,shell.bottom,innerHeight)-Math.max(image.top,top.bottom,shell.top,0)),overflow:document.querySelector('.se-shell').scrollWidth>document.querySelector('.se-shell').clientWidth};});
  let m=await measures();await page.screenshot({path:path.join(evidence,`layout-${width}x${height}.png`)});
  results.push(m);console.log(JSON.stringify(m));
  if(!process.env.VS_LAYOUT_OBSERVE){
   assert.equal(m.viewport.width,width,'must test actual mobile CSS width');assert.equal(m.overflow,false,'no horizontal overflow');
   assert.ok(m.top.height<=Math.max(150,height*.22),'editor controls must not dominate mobile viewport');
   assert.ok(m.visibleImage>=Math.min(240,height*.4),'first image must have useful visible area on opening');
   await page.locator('.se-shell').evaluate(el=>el.scrollTop=el.scrollHeight);
   const last=page.locator('.se-card').last();await last.locator('.se-image').scrollIntoViewIfNeeded();
   const visible=await last.locator('.se-image').evaluate(el=>{const r=el.getBoundingClientRect(),head=document.querySelector('.se-top').getBoundingClientRect();return Math.max(0,Math.min(r.bottom,innerHeight)-Math.max(r.top,head.bottom,0));});assert.ok(visible>=Math.min(220,height*.4),'later scene can be scrolled into usable view');
   await page.locator('#seOptionsToggle').click();assert.equal(await page.locator('#seSettings').isVisible(),true,'settings can be reached from any scroll position');
   await page.locator('#seMode').scrollIntoViewIfNeeded();assert.equal(await page.locator('#seMode').isVisible(),true);
   await page.locator('#seExport').scrollIntoViewIfNeeded();assert.equal(await page.locator('#seExport').isVisible(),true,'export remains reachable without covering scenes permanently');
   await page.locator('#seOptionsToggle').click();assert.equal(await page.locator('#seSettings').isVisible(),false);
   await page.locator('#seClose').click();assert.equal(await page.locator('.se-overlay').isVisible(),false,'close remains reachable');
   assert.equal(await page.evaluate(()=>document.body.style.overflow),'','background scroll is restored after closing');
  }
  await context.close();
 }
 fs.writeFileSync(path.join(evidence,'measurements.json'),JSON.stringify(results,null,2));
}finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
