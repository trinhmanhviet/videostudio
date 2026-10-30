const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require('C:/Users/leath/AppData/Local/Programs/aicoworker/resources/openclaw/node_modules/playwright-core');
(async()=>{
 const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:390,height:844}});
  await page.route('**/*',route=>route.fulfill({contentType:'text/html',body:'<!doctype html><meta name="viewport" content="width=device-width"><main><header>Studio</header><form id="create"><select id="imageProvider"><option value="flow">Flow</option></select><button id="submit">Create</button></form><p id="submitError"></p></main><style>.row{display:flex;flex-wrap:wrap;gap:8px}*{box-sizing:border-box}button{min-height:34px}p{overflow-wrap:anywhere}</style>'}));
  await page.goto('http://localhost:8877/');
  await page.evaluate(()=>{
   window.calls=[];window.submitted=0;window.profile={mode:'closed',running:false,can_change:true,active_jobs:0,busy:false};
   document.querySelector('#create').addEventListener('submit',event=>{event.preventDefault();submitted++;});
   window.fetch=async(url,options={})=>{
    calls.push({url,method:options.method||'GET',body:options.body});
    if(url.endsWith('/open')){const mode=JSON.parse(options.body).mode;profile={...profile,mode,running:true,debug_ready:mode==='debug'};}
    if(url.endsWith('/stop'))profile={...profile,mode:'closed',running:false};
    return {ok:true,json:async()=>profile};
   };
  });
  await page.addScriptTag({path:path.join(__dirname,'../static/browser-profile.js')});
  const panel=page.locator('#chromeProfileControls');await panel.getByText('Chrome riêng đang tắt.',{exact:true}).waitFor();
  await panel.getByRole('button',{name:'Mở sạch',exact:true}).click();await panel.getByText(/Đang mở sạch/).waitFor();
  await page.locator('#submit').click();assert.equal(await page.evaluate(()=>submitted),0);assert.match(await page.locator('#submitError').innerText(),/Mở debug/);
  console.log('PASS clean mode prevents accidental Flow job submission');
  await panel.getByRole('button',{name:'Mở debug',exact:true}).click();await panel.getByText(/sẵn sàng cho tool/).waitFor();
  await page.locator('#submit').click();assert.equal(await page.evaluate(()=>submitted),1);
  await panel.getByRole('button',{name:'Tắt Chrome riêng',exact:true}).click();await panel.getByText('Chrome riêng đang tắt.',{exact:true}).waitFor();
  const posts=await page.evaluate(()=>calls.filter(c=>c.method==='POST'));assert.deepEqual(posts.map(c=>c.url),['/api/browser/profile/open','/api/browser/profile/open','/api/browser/profile/stop']);
  assert.deepEqual(posts.slice(0,2).map(c=>JSON.parse(c.body).mode),['clean','debug']);console.log('PASS clean/debug/stop routes use one fixed profile');
  await page.evaluate(()=>{profile.active_jobs=1;profile.can_change=false;});await panel.getByRole('button',{name:'Kiểm tra Chrome',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#chromeProfileControls [data-mode="clean"]').disabled);
  assert.equal(await panel.getByRole('button',{name:'Mở debug',exact:true}).isDisabled(),true);console.log('PASS active video disables mode changes');
  const rect=await panel.boundingBox();assert.ok(rect.x>=0&&rect.x+rect.width<=390);console.log('PASS controls fit mobile viewport');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
