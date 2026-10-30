/* Isolated real Chrome fixtures. Every request is intercepted; no personal profile. */
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const {chromium}=require(process.env.VS_PLAYWRIGHT_PATH||'C:/Users/leath/AppData/Local/Programs/aicoworker/resources/openclaw/node_modules/playwright-core');
const root=path.resolve(__dirname,'..');
const bridge='123e4567-e89b-42d3-a456-426614174000';
const child='123e4567-e89b-42d3-a456-426614174001';
const other='123e4567-e89b-42d3-a456-426614174002';
const job=(scope,job_id,state='queued',title=job_id)=>({scope,job_id,state,title,project:'Fixture',stage:state,error:'',created:1});
const failures=[];
async function check(name,fn){if(process.env.VS_MANAGER_TEST_FILTER&&!name.includes(process.env.VS_MANAGER_TEST_FILTER))return;try{await fn();console.log('PASS',name);}catch(error){failures.push(name);console.error('FAIL',name,error.message);}}
(async()=>{
  const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
  const context=await browser.newContext();
  context.setDefaultTimeout(2000);
  await context.route('**/*',route=>route.fulfill({contentType:'text/html',body:'<!doctype html><html><body></body></html>'}));
  async function fixture(config={}){
    const page=await context.newPage();
    page.bridgeCalls=[];page.apiCalls=[];
    await page.exposeFunction('recordBridgeTest',message=>page.bridgeCalls.push(message));
    await page.exposeFunction('recordApiTest',request=>page.apiCalls.push(request));
    await page.goto('http://localhost:8877'+(config.pagePath??`/story-video/projects/${bridge}/production`));
    await page.evaluate(({config,bridge})=>{
      localStorage.clear();
      const attach=Element.prototype.attachShadow;
      Element.prototype.attachShadow=function(options){return attach.call(this,{...options,mode:'open'});};
      window.fixture={active:true,sessions:[],pending:[],slots:[],calls:[],requests:[],events:[],...config};
      fixture.slots=fixture.slots.map(slot=>({ownedTabs:Number.isInteger(slot.job?.chatTab)?[slot.job.chatTab]:[],...slot}));
      window.chrome={runtime:{sendMessage:async message=>{
        const f=window.fixture;f.calls.push(message);f.events.push({kind:message.kind,scope:message.scope});
        await window.recordBridgeTest(message);
        if(f.invalidated)throw Error('Extension context invalidated');
        if(message.kind==='connection')return {ok:true,scope:f.savedScope||null,url:f.savedScope?`/story-video/projects/${f.savedScope}/production`:null};
        if(message.kind==='snapshot')return {ok:true,active:f.active,job:null,sessions:f.slots};
        if(message.kind==='recover_chat'){
          let status=f.repairStatus||'reply';if(status==='needs-chat-url'&&message.url)status='reply';
          if(status==='reply'){const slot=f.slots.find(s=>s.scope===message.scope);slot.job.phase='reply';slot.job.text='{"ok":true}';}
          return {ok:true,status};
        }
        if(message.kind==='stop')f.active=false;
        if(message.kind==='start')f.active=true;
        if(message.kind==='cancel_session'){
          if(f.cancelTransientLeft>0){f.cancelTransientLeft--;return {ok:false,error:'temporary worker disconnect',transient:true};}
          const slot=f.slots.find(slot=>slot.scope===message.scope);
          const video=slot?.is_smoke?slot.retained?.find(saved=>saved.job_id===message.job_id):slot;
          if(video){video.cancelled=true;video.active=false;video.ownedTabs=[];}
        }
        if(message.kind==='reconcile'&&f.workerTransient)return {ok:false,error:'Server receipt unavailable',transient:true};
        if(message.kind==='reconcile'&&f.recoverOnCheck&&message.inspect_only){f.slots.find(slot=>slot.scope===message.scope).job.phase='reply';return {ok:true,status:'reply'};}
        if(message.kind==='imported')f.slots=f.slots.filter(slot=>slot.scope!==message.scope);
        if(message.kind==='dismiss_session')f.slots=f.slots.filter(slot=>slot.job_id!==message.job_id);
        return {ok:true,phase:'sent',status:'pending'};
      },onMessage:{addListener(){},removeListener(){window.fixture.retired=true;}}}};
      window.fetch=async (input,options={})=>{
        const f=window.fixture;const url=String(input);f.requests.push({url,method:options.method||'GET',body:options.body});f.events.push({url});
        await window.recordApiTest({url,method:options.method||'GET'});
        if(url.startsWith('/api/browser/profile')){
          f.profile??={mode:'closed',running:false,can_change:true,active_jobs:0};
          if(url.endsWith('/open')){const mode=JSON.parse(options.body).mode;f.profile={...f.profile,mode,running:true,debug_ready:mode==='debug'};}
          if(url.endsWith('/stop'))f.profile={...f.profile,mode:'closed',running:false};
          return {ok:true,json:async()=>({...f.profile})};
        }
        if(url.includes('/flow-account')){
          if(f.holdFlowStatus&&!options.method)await new Promise(resolve=>window.releaseFlowStatus=resolve);
          f.flow??={phase:'idle',message:'Chuẩn bị đổi tài khoản cho video này.',cached_count:0,total:10,missing_count:10,can_prepare:true,can_continue:false};
          if(url.endsWith('/prepare')){
            if(f.rejectFlowPrepare)return {ok:false,status:409,json:async()=>({detail:'Một tác vụ ảnh khác đang chạy. Chờ xong rồi thử lại.'})};
            f.flow={...f.flow,phase:'pausing',message:'Đang chờ bước hiện tại kết thúc.',can_prepare:false};f.profile={...f.profile,can_change:false};
            f.sessions.find(item=>item.job_id===url.split('/')[3]).state='awaiting_flow_account';
          }
          if(url.endsWith('/continue'))f.flow={...f.flow,phase:'running',message:'Đã tiếp tục video này.',can_continue:false};
          if(f.rejectFlowStatus&&!options.method)return {ok:false,status:503,json:async()=>({detail:'Chưa đọc được trạng thái; kiểm tra lại.'})};
          return {ok:true,json:async()=>({...f.flow})};
        }
        if(url==='/api/connector/sessions'&&options.method==='POST')return {ok:true,json:async()=>({project_id:bridge,run_id:bridge,url:`/story-video/projects/${bridge}/production`})};
        if(url.endsWith('/sessions'))return {ok:true,json:async()=>({items:f.sessions})};
        if(url.endsWith('/pending')){
          f.pendingPolls=(f.pendingPolls||0)+1;
          if(f.httpTransient&&f.pendingPolls===1)return {ok:false,status:503};
          if(f.holdPending)await new Promise(resolve=>window.releasePending=resolve);
          return {ok:true,json:async()=>({items:f.pending})};
        }
        if(url.endsWith('/dismiss')){
          const payload=JSON.parse(options.body||'{}');
          if(f.rejectDelete&&payload.delete_files)return {ok:false,status:409,json:async()=>({detail:'Files are referenced by another video. Choose keep files.'})};
          const id=url.split('/').at(-2),item=f.sessions.find(row=>row.job_id===id);f.sessions=f.sessions.filter(row=>row.job_id!==id);f.dismissedIds??=[];f.dismissedIds.push(id);
          if(f.throwAfterDismiss)throw Error('Dismissal committed, connection lost');
          return {ok:true,json:async()=>({...item,dismissed:true,files_deleted:payload.delete_files===true,files_preserved:payload.delete_files!==true})};
        }
        if(f.dismissedIds?.includes(url.split('/').at(-1)))return {ok:true,json:async()=>({dismissed:true})};
        if(url.endsWith('/cancel')){
          if(f.rejectCancel)return {ok:false,status:403};
          const id=url.split('/').at(-2);const session=f.sessions.find(item=>item.job_id===id);session.cancel_requested=true;
          if(f.throwAfterCancel)throw Error('Cancellation committed, connection lost');
          return {ok:true,json:async()=>session};
        }
        if(url.includes('/chatgpt-exchanges/'))return {ok:true,json:async()=>({id:'receipt',version:3,accepted:options.method==='POST'})};
        return {ok:true,json:async()=>({})};
      };
    },{config,bridge});
    await page.addScriptTag({path:path.join(root,'extensions/videostudio-chatgpt/studio.js')});
    return page;
  }
  const card=(page,scope)=>page.locator(`[data-session-scope="${scope}"]`);
  try{
    await check('Flow account wizard pauses safely, uses shared Chrome controls and explicitly continues original job',async()=>{
      const page=await fixture({sessions:[{...job(child,'flow-one','running'),image_provider:'flow',stage:'images'},job(other,'untouched','running')]});
      await page.setViewportSize({width:390,height:844});
      const chrome=page.locator('[data-browser-profile]');await chrome.locator('summary').click();
      await chrome.getByRole('button',{name:'Mở sạch',exact:true}).waitFor();
      await card(page,child).getByRole('button',{name:'Đổi tài khoản Flow',exact:true}).click();
      const wizard=card(page,child).locator('[data-flow-account]');
      await wizard.getByRole('button',{name:'Chuẩn bị đổi tài khoản',exact:true}).click();
      await wizard.getByRole('status').getByText(/chờ bước hiện tại kết thúc/i).waitFor();
      assert.equal(await wizard.getByRole('button',{name:'Tiếp tục video này',exact:true}).isDisabled(),true);
      assert.equal(await chrome.getByRole('button',{name:'Mở sạch',exact:true}).isDisabled(),true);
      assert.doesNotMatch(await wizard.innerText(),/Đã giữ 0/);
      await page.evaluate(()=>{fixture.flow={...fixture.flow,phase:'reconciling',message:'Đang đối chiếu ảnh của video.'};});
      await wizard.getByText(/Đang đối chiếu ảnh/).waitFor({timeout:3500});
      await page.evaluate(()=>{fixture.flow={...fixture.flow,phase:'ready',message:'Đã đối chiếu; có thể đăng nhập tài khoản khác.',cached_count:7,missing_count:3,can_continue:true};fixture.profile.can_change=true;});
      await wizard.getByText(/Đã giữ 7\/10 ảnh/).waitFor({timeout:3500});
      if(process.env.VS_FLOW_UI_SCREENSHOT)await page.screenshot({path:process.env.VS_FLOW_UI_SCREENSHOT});
      await chrome.getByRole('button',{name:'Mở sạch',exact:true}).click();await chrome.getByText(/Đang mở sạch/).waitFor();
      assert.equal(await wizard.getByRole('button',{name:'Tiếp tục video này',exact:true}).isDisabled(),true);
      await chrome.getByRole('button',{name:'Mở debug',exact:true}).click();
      await wizard.getByRole('button',{name:'Tiếp tục video này',exact:true}).click();
      await wizard.getByText(/Đã tiếp tục video này/).waitFor();
      const f=await page.evaluate(()=>fixture);
      assert.deepEqual(f.requests.filter(r=>r.method==='POST'&&r.url.includes('/flow-account')).map(r=>r.url),['/api/jobs/flow-one/flow-account/prepare','/api/jobs/flow-one/flow-account/continue']);
      assert.equal(f.requests.some(r=>r.url==='/api/jobs'&&r.method==='POST'),false);
      assert.equal(f.calls.some(c=>['cancel_session','stop'].includes(c.kind)),false);
      assert.equal(await card(page,other).count(),1);
      const rect=await wizard.boundingBox();assert.ok(rect.x>=0&&rect.x+rect.width<=390);await page.close();
    });
    await check('Flow account wizard keeps preparation refusal actionable and is absent from other providers',async()=>{
      const page=await fixture({rejectFlowPrepare:true,sessions:[{...job(child,'flow-one','running'),image_provider:'flow'}, {...job(other,'other','running'),image_provider:'comfy'}]});
      assert.equal(await card(page,other).getByRole('button',{name:'Đổi tài khoản Flow',exact:true}).count(),0);
      await card(page,child).getByRole('button',{name:'Đổi tài khoản Flow',exact:true}).click();
      const wizard=card(page,child).locator('[data-flow-account]');await wizard.getByRole('button',{name:'Chuẩn bị đổi tài khoản',exact:true}).click();
      await wizard.getByRole('alert').getByText(/Một tác vụ ảnh khác/).waitFor();
      assert.equal(await wizard.getByRole('button',{name:'Chuẩn bị đổi tài khoản',exact:true}).isDisabled(),false);await page.close();
    });
    await check('awaiting Flow account remains cancellable and polls with connector stopped',async()=>{
      const page=await fixture({active:false,sessions:[{...job(child,'flow-one','awaiting_flow_account'),image_provider:'flow'}],flow:{phase:'ready',message:'Sẵn sàng đổi tài khoản.',cached_count:2,total:4,missing_count:2,can_prepare:false,can_continue:true}});
      await card(page,child).getByText(/Chờ đổi tài khoản Flow/).waitFor();
      await card(page,child).locator('[data-flow-account]').getByText(/Đã giữ 2\/4 ảnh/).waitFor();
      await card(page,child).getByRole('button',{name:'Hủy',exact:true}).click();await card(page,child).waitFor({state:'detached'});
      assert.deepEqual(page.bridgeCalls.filter(c=>c.kind==='cancel_session').map(c=>c.job_id),['flow-one']);await page.close();
    });
    await check('Chrome profile controls are collapsible in float and static page has no duplicate script',async()=>{
      assert.doesNotMatch(fs.readFileSync(path.join(root,'static/index.html'),'utf8'),/<script[^>]+src=["']\/browser-profile\.js/);
      const page=await fixture({pagePath:'/'}),panel=page.locator('[data-browser-profile]');
      assert.equal(await panel.getAttribute('open'),null);await panel.locator('summary').click();
      await panel.getByText('Chrome riêng đang tắt.',{exact:true}).waitFor();
      for(const name of ['Mở sạch','Mở debug','Tắt Chrome riêng'])await panel.getByRole('button',{name,exact:true}).click();
      const posts=await page.evaluate(()=>fixture.requests.filter(r=>r.method==='POST'));
      assert.deepEqual(posts.map(r=>r.url),['/api/browser/profile/open','/api/browser/profile/open','/api/browser/profile/stop']);await page.close();
    });
    await check('Flow account status recovers after a read error without another preparation',async()=>{
      const page=await fixture({rejectFlowStatus:true,sessions:[{...job(child,'flow-one','running'),image_provider:'flow'}]});
      await card(page,child).getByRole('button',{name:'Đổi tài khoản Flow',exact:true}).click();const wizard=card(page,child).locator('[data-flow-account]');
      await wizard.getByRole('alert').getByText(/Chưa đọc được trạng thái/).waitFor();
      await page.evaluate(()=>{fixture.rejectFlowStatus=false;});await wizard.getByRole('button',{name:'Kiểm tra trạng thái',exact:true}).click();
      await wizard.getByRole('button',{name:'Chuẩn bị đổi tài khoản',exact:true}).waitFor();
      await page.waitForFunction(()=>document.querySelector('[data-videostudio-manager]').shadowRoot.querySelector('[data-flow-account] [role="alert"]').hidden);
      assert.equal(page.apiCalls.some(c=>c.method==='POST'&&c.url.includes('/flow-account')),false);await page.close();
    });
    await check('Flow account opening twice while status is delayed does not strand the wizard',async()=>{
      const page=await fixture({holdFlowStatus:true,sessions:[{...job(child,'flow-one','running'),image_provider:'flow'}]});
      const button=card(page,child).getByRole('button',{name:'Đổi tài khoản Flow',exact:true});await button.click();
      await page.waitForFunction(()=>typeof window.releaseFlowStatus==='function');await button.click();
      await page.evaluate(()=>{fixture.holdFlowStatus=false;window.releaseFlowStatus();});
      const prepare=card(page,child).locator('[data-flow-account]').getByRole('button',{name:'Chuẩn bị đổi tài khoản',exact:true});
      await page.waitForFunction(()=>!document.querySelector('[data-videostudio-manager]').shadowRoot.querySelector('[data-flow-account] button').disabled);
      assert.equal(await prepare.isDisabled(),false);await page.close();
    });
    await check('self-service repair imports recovered reply and retries only the failed text step',async()=>{
      const session={...job(child,'stuck','failed'),stage:'script',error:'Chrome connector response unavailable; request retained'};
      const page=await fixture({sessions:[session],slots:[{scope:child,job_id:'stuck',job:{id:'receipt',version:3,phase:'sent',attempt:1,chatTab:22,prompt:'YÊU CẦU STUDIO receipt\nX'}}]});
      await card(page,child).getByRole('button',{name:'Khôi phục ChatGPT',exact:true}).click();
      await page.waitForFunction(()=>fixture.requests.some(r=>r.url==='/api/jobs/stuck/retry'));
      assert.equal(page.bridgeCalls.filter(c=>c.kind==='recover_chat').length,1);
      assert.equal(page.bridgeCalls.filter(c=>c.kind==='claim'||c.kind==='deliver').length,0);
      assert.ok(page.bridgeCalls.some(c=>c.kind==='imported'&&c.scope===child));await page.close();
    });
    await check('self-service repair guides missing URL and accepts pasted conversation without a new job',async()=>{
      const page=await fixture({repairStatus:'needs-chat-url',sessions:[{...job(child,'stuck','failed'),stage:'script'}],slots:[{scope:child,job_id:'stuck',job:{id:'receipt',version:3,phase:'sent',attempt:1,chatTab:22,prompt:'YÊU CẦU STUDIO receipt\nX'}}]});
      await page.setViewportSize({width:390,height:844});
      await card(page,child).getByRole('button',{name:'Khôi phục ChatGPT',exact:true}).click();
      const panel=card(page,child).locator('[data-chat-recovery]');await panel.getByText(/Dán URL/).waitFor();
      const bounds=await panel.boundingBox();assert.ok(bounds.x>=0&&bounds.x+bounds.width<=390,'recovery panel must fit mobile width');
      const screenshots=path.join(root,'data/extension-self-recovery');fs.mkdirSync(screenshots,{recursive:true});await page.screenshot({path:path.join(screenshots,'repair-url-mobile.png')});
      const url='https://chatgpt.com/c/123e4567-e89b-42d3-a456-426614174111';await panel.getByRole('textbox').fill(url);
      await panel.getByRole('button',{name:'Thử khôi phục',exact:true}).click();
      await page.waitForFunction(()=>fixture.calls.filter(c=>c.kind==='recover_chat').length===2);
      assert.equal(page.bridgeCalls.filter(c=>c.kind==='recover_chat')[1].url,url);
      assert.ok(!page.apiCalls.some(c=>c.url==='/api/jobs'&&c.method==='POST'));await page.close();
    });
    await check('self-service repair explains login instead of pretending to recover',async()=>{
      const page=await fixture({repairStatus:'open-chat',sessions:[{...job(child,'stuck','running'),stage:'script'}],slots:[{scope:child,job_id:'stuck',job:{id:'receipt',version:3,phase:'sent',attempt:1,chatTab:22,prompt:'YÊU CẦU STUDIO receipt\nX'}}]});
      await card(page,child).getByRole('button',{name:'Khôi phục ChatGPT',exact:true}).click();
      await card(page,child).locator('[data-chat-recovery]').getByText(/đăng nhập/).waitFor();
      assert.ok(!page.bridgeCalls.some(c=>c.kind==='imported'));await page.close();
    });
    await check('terminal video × asks first and keep-files confirmation releases only its exact job',async()=>{
      const page=await fixture({sessions:[job(child,'done','completed'),job(other,'live','running')],slots:[{scope:child,job_id:'done',job:null}]});
      await card(page,child).getByRole('button',{name:/Xóa phiên/}).click();
      const dialog=page.getByRole('dialog');await dialog.waitFor();assert.match(await dialog.innerText(),/done/);
      assert.equal(await dialog.getByRole('checkbox').isChecked(),false);
      assert.equal(await page.evaluate(()=>fixture.requests.some(row=>row.url.endsWith('/dismiss'))),false);
      assert.equal(page.bridgeCalls.some(call=>call.kind==='dismiss_session'),false);
      await dialog.getByRole('button',{name:'Xóa phiên, giữ file',exact:true}).click();await card(page,child).waitFor({state:'detached'});
      const f=await page.evaluate(()=>fixture);assert.deepEqual(JSON.parse(f.requests.find(row=>row.url.endsWith('/dismiss')).body),{delete_files:false,confirm:true});
      assert.ok(f.events.findIndex(event=>event.url?.endsWith('/done/dismiss'))<f.events.findIndex(event=>event.kind==='dismiss_session'));
      assert.equal(await card(page,other).count(),1);assert.deepEqual(page.bridgeCalls.filter(call=>call.kind==='dismiss_session'),[{kind:'dismiss_session',scope:child,job_id:'done'}]);await page.close();
    });
    await check('float delete-files choice requires explicit final confirmation and reports removed files',async()=>{
      const page=await fixture({sessions:[job(child,'done','completed','<img src=x>')],slots:[{scope:child,job_id:'done',job:null}]});
      await card(page,child).getByRole('button',{name:/Xóa phiên/}).click();const dialog=page.getByRole('dialog');
      await dialog.getByRole('checkbox').check();assert.match(await dialog.innerText(),/không thể hoàn tác/i);assert.equal(await dialog.locator('img').count(),0);
      assert.equal(await page.evaluate(()=>fixture.requests.some(row=>row.url.endsWith('/dismiss'))),false);
      await dialog.getByRole('button',{name:'Xóa phiên và file',exact:true}).click();await card(page,child).waitFor({state:'detached'});
      assert.deepEqual(await page.evaluate(()=>JSON.parse(fixture.requests.find(row=>row.url.endsWith('/dismiss')).body)),{delete_files:true,confirm:true});
      assert.match(await page.locator('#status').innerText(),/đã xóa.*file/i);await page.close();
    });
    await check('cancel and Escape close float choice without API or worker mutation',async()=>{
      const page=await fixture({sessions:[job(child,'done','completed')]});const trigger=card(page,child).getByRole('button',{name:/Xóa phiên/});
      await trigger.click();await page.keyboard.press('Tab');assert.equal(await page.getByRole('dialog').getByRole('checkbox').evaluate(node=>node===node.getRootNode().activeElement),true);
      await page.keyboard.press('Shift+Tab');assert.equal(await page.getByRole('button',{name:'Quay lại',exact:true}).evaluate(node=>node===node.getRootNode().activeElement),true);
      await page.getByRole('dialog').getByRole('checkbox').check();await page.getByRole('button',{name:'Quay lại',exact:true}).click();
      assert.equal(await page.getByRole('dialog').count(),0);assert.equal(await trigger.evaluate(node=>node===node.getRootNode().activeElement),true);
      await trigger.click();assert.equal(await page.getByRole('dialog').getByRole('checkbox').isChecked(),false);
      await page.keyboard.press('Escape');assert.equal(await page.getByRole('dialog').count(),0);assert.equal(await page.locator('#manager').isVisible(),true);
      assert.equal(await page.evaluate(()=>fixture.requests.some(row=>row.url.endsWith('/dismiss'))),false);assert.equal(page.bridgeCalls.some(call=>call.kind==='dismiss_session'),false);await page.close();
    });
    await check('shared-file refusal remains in float dialog and user can switch to keeping files',async()=>{
      const page=await fixture({rejectDelete:true,sessions:[job(child,'done','completed')],slots:[{scope:child,job_id:'done',job:null}]});
      await card(page,child).getByRole('button',{name:/Xóa phiên/}).click();const dialog=page.getByRole('dialog');await dialog.getByRole('checkbox').check();await dialog.getByRole('button',{name:'Xóa phiên và file',exact:true}).click();
      await page.waitForFunction(()=>fixture.requests.some(row=>row.url.endsWith('/dismiss')));
      await dialog.getByRole('alert').filter({hasText:/referenced by another video/}).waitFor();assert.equal(await dialog.getByRole('checkbox').isChecked(),true);
      assert.equal(page.bridgeCalls.some(call=>call.kind==='dismiss_session'),false);assert.equal(await card(page,child).count(),1);
      await dialog.getByRole('checkbox').uncheck();assert.match(await dialog.getByRole('alert').innerText(),/Choose keep files/);
      await dialog.getByRole('button',{name:'Xóa phiên, giữ file',exact:true}).click();await card(page,child).waitFor({state:'detached'});
      assert.deepEqual(await page.evaluate(()=>fixture.requests.filter(row=>row.url.endsWith('/dismiss')).map(row=>JSON.parse(row.body))),[{delete_files:true,confirm:true},{delete_files:false,confirm:true}]);await page.close();
    });
    await check('lost dismissal response still repairs orphan worker job from server attestation',async()=>{
      const page=await fixture({throwAfterDismiss:true,sessions:[job(child,'done','completed')],slots:[{scope:child,job_id:'done',job:null}]});
      await card(page,child).getByRole('button',{name:/Xóa phiên/}).click();await page.getByRole('dialog').getByRole('button',{name:'Xóa phiên, giữ file',exact:true}).click();
      await page.waitForFunction(()=>fixture.calls.some(call=>call.kind==='dismiss_session'),{},{timeout:3600});
      assert.ok(page.bridgeCalls.filter(call=>call.kind==='dismiss_session').every(call=>call.scope===child&&call.job_id==='done'));
      assert.equal(await card(page,child).count(),0);assert.equal(await page.getByRole('dialog').count(),0);await page.close();
    });
    await check('failed ChatGPT request is inspected and resumed after a recovered accepted response',async()=>{
      const page=await fixture({recoverOnCheck:true,sessions:[{...job(child,'stuck','failed'),stage:'script',error:'HTTP403 connector timeout'}],slots:[{scope:child,job:{id:'receipt',version:3,attempt:1,phase:'uncertain',text:'{"ok":true}'}}]});
      await page.waitForFunction(()=>fixture.requests.some(row=>row.url.endsWith('/stuck/retry')),undefined,{timeout:2500});
      assert.ok(page.bridgeCalls.some(call=>call.kind==='reconcile'&&call.inspect_only===true));assert.equal(page.apiCalls.filter(row=>row.url.endsWith('/stuck/retry')).length,1);await page.close();
    });
    await check('cancelled and cancel-requested videos disappear while live sessions remain',async()=>{
      const page=await fixture({sessions:[{...job(child,'cancelled','failed','Old cancelled'),cancel_requested:true},job(other,'live','running'),job(bridge,'cancelled2','cancelled','Old cancelled2')]});
      await card(page,other).waitFor();assert.equal(await card(page,child).count(),0);assert.equal(await card(page,bridge).count(),0);
      assert.equal(await page.locator('#count').innerText(),'1');assert.doesNotMatch(await page.locator('#manager').innerText(),/Old cancelled/);await page.close();
    });
    await check('Start on the homepage reconnects the saved bridge without allocating another scope',async()=>{
      const page=await fixture({pagePath:'/',active:false,savedScope:bridge});
      await page.getByRole('button',{name:'Start',exact:true}).click();
      await page.waitForURL(`http://localhost:8877/story-video/projects/${bridge}/production`,{timeout:2500});
      assert.ok(page.bridgeCalls.some(call=>call.kind==='start'&&call.scope===bridge&&call.reconnect===true));
      assert.equal(page.apiCalls.some(call=>call.url==='/api/connector/sessions'&&call.method==='POST'),false);await page.close();
    });
    await check('Start on another scoped page returns to the saved bridge without a foreign heartbeat',async()=>{
      const page=await fixture({pagePath:`/story-video/projects/${other}/production`,active:false,savedScope:bridge});
      await page.getByRole('button',{name:'Start',exact:true}).click();
      await page.waitForURL(`http://localhost:8877/story-video/projects/${bridge}/production`,{timeout:2500});
      assert.ok(page.bridgeCalls.some(call=>call.kind==='start'&&call.scope===bridge&&call.reconnect===true));
      assert.equal(page.apiCalls.some(call=>call.url===`/api/connector/status/${other}`),false);
      assert.equal(page.apiCalls.some(call=>call.url==='/api/connector/sessions'&&call.method==='POST'),false);await page.close();
    });
    await check('Start still creates the first connection when no saved bridge exists',async()=>{
      const page=await fixture({pagePath:'/',active:false});
      await page.getByRole('button',{name:'Start',exact:true}).click();
      await page.waitForURL(`http://localhost:8877/story-video/projects/${bridge}/production`,{timeout:2500});
      assert.equal(page.apiCalls.filter(call=>call.url==='/api/connector/sessions'&&call.method==='POST').length,1);await page.close();
    });
    await check('reload hydrates all video titles and authoritative queue states safely',async()=>{
      const page=await fixture({sessions:[job(child,'one','queued','<img src=x onerror=alert(1)>'),job(other,'two','running','Second')],slots:[{scope:child,job:{id:'old',phase:'failed',reason:'old error'}}]});
      await card(page,child).waitFor({timeout:2000});
      assert.match(await card(page,child).innerText(),/<img src=x onerror=alert\(1\)>/);
      assert.equal(await card(page,child).locator('img').count(),0);
      assert.match(await card(page,child).innerText(),/xếp hàng/i);
      assert.match(await card(page,other).innerText(),/đang xử lý/i);
      assert.match(await page.locator('#manager').innerText(),/sequential|lần lượt/i);
      await page.close();
    });
    await check('collapsed round manager persists and keeps polling within a mobile viewport',async()=>{
      const page=await fixture({sessions:[job(child,'one')]});await page.setViewportSize({width:320,height:480});
      await page.locator('#collapse').click();
      assert.equal(await page.locator('#manager').isVisible(),false);
      assert.equal(await page.locator('#badge').getAttribute('aria-expanded'),'false');
      await page.waitForTimeout(1400);
      assert.ok(await page.evaluate(()=>fixture.pendingPolls>=2));
      assert.equal(await page.evaluate(()=>fixture.calls.some(call=>call.kind==='stop')),false);
      assert.equal(await page.evaluate(()=>localStorage.getItem('videostudio_manager_collapsed')),'true');
      const bounds=await page.locator('#badge').boundingBox();assert.ok(bounds.x>=0&&bounds.x+bounds.width<=320);
      await page.evaluate(()=>{document.querySelector('[data-videostudio-manager]').remove();});
      await page.addScriptTag({path:path.join(root,'extensions/videostudio-chatgpt/studio.js')});
      assert.equal(await page.locator('#manager').isVisible(),false);
      await page.locator('#badge').click();assert.equal(await page.locator('#manager').isVisible(),true);
      const expanded=await page.locator('#manager').boundingBox();assert.ok(expanded.x>=0&&expanded.x+expanded.width<=320&&expanded.height<=480);
      if(process.env.VS_MANAGER_SCREENSHOT)await page.screenshot({path:process.env.VS_MANAGER_SCREENSHOT});
      await page.close();
    });
    await check('failed old slot cannot block a new scoped pending request',async()=>{
      const page=await fixture({sessions:[job(child,'failed','failed'),job(other,'next')],slots:[{scope:child,job:{id:'old',phase:'uncertain',reason:'old failure'}}],pending:[{scope:other,job_id:'next',id:'new',version:1,prompt:'Fixture only',attachments:[]}]});
      await page.waitForFunction(()=>fixture.calls.some(call=>call.kind==='claim'),{},{timeout:2000});
      const calls=await page.evaluate(()=>fixture.calls);assert.ok(calls.some(call=>call.kind==='claim'&&call.scope===other&&call.job_id==='next'));
      assert.equal(calls.some(call=>call.kind==='reconcile'&&call.scope===child),false);await page.close();
    });
    await check('per-video explicit controls route exact scope and cancel only after server acknowledgement',async()=>{
      const page=await fixture({sessions:[job(child,'one'),job(other,'two')],slots:[{scope:child,job:{id:'old',phase:'sent',chatTab:4}},{scope:other,job:{id:'second',phase:'sent',chatTab:5}}]});
      await card(page,child).getByRole('button',{name:'Mở chat',exact:true}).click();
      await card(page,child).getByRole('button',{name:'Kiểm tra lại',exact:true}).click();
      await card(page,child).getByRole('button',{name:'Hủy',exact:true}).click();
      const f=await page.evaluate(()=>fixture);
      assert.ok(f.calls.some(call=>call.kind==='open_chat'&&call.scope===child));
      assert.ok(f.calls.some(call=>call.kind==='reconcile'&&call.scope===child&&call.inspect_only===true));
      assert.ok(f.requests.some(request=>request.url===`/api/connector/bridges/${bridge}/jobs/one/cancel`&&request.method==='POST'));
      assert.deepEqual(f.calls.filter(call=>call.kind==='cancel_session').map(call=>call.scope),[child]);
      assert.ok(f.events.findIndex(event=>event.url?.endsWith('/one/cancel'))<f.events.findIndex(event=>event.kind==='cancel_session'));
      await card(page,child).waitFor({state:'detached'});assert.equal(await card(page,other).count(),1);await page.close();
    });
    await check('rejected server cancellation preserves every worker session',async()=>{
      const page=await fixture({rejectCancel:true,sessions:[job(child,'one')]});
      await card(page,child).getByRole('button',{name:'Hủy',exact:true}).click();
      assert.equal(await page.evaluate(()=>fixture.calls.some(call=>call.kind==='cancel_session')),false);await page.close();
    });
    await check('reply recovery uses child receipt endpoint and scoped acknowledgement',async()=>{
      const page=await fixture({sessions:[job(child,'one','running')],slots:[{scope:child,job:{id:'receipt',version:3,phase:'reply',text:'{"ok":true}'}}]});
      await page.waitForFunction(()=>fixture.calls.some(call=>call.kind==='imported'),{},{timeout:2000});
      const f=await page.evaluate(()=>fixture);
      assert.ok(f.requests.some(request=>request.url===`/api/v1/projects/${child}/runs/${child}/chatgpt-exchanges/receipt/response`));
      assert.ok(f.calls.some(call=>call.kind==='imported'&&call.scope===child&&call.id==='receipt'&&call.version===3));await page.close();
    });
    await check('direct and worker transient errors preserve automatic recovery',async()=>{
      for(const config of [{httpTransient:true},{workerTransient:true,slots:[{scope:child,job:{id:'old',phase:'sent'}}]}]){
        const page=await fixture({...config,sessions:[job(child,'one','running')]});await page.waitForTimeout(1500);
        const f=await page.evaluate(()=>fixture);assert.ok(f.pendingPolls>=2);assert.equal(f.calls.some(call=>call.kind==='stop'),false);
        if(config.workerTransient)assert.ok(f.calls.filter(call=>call.kind==='reconcile').length>=2);
        await page.close();
      }
    });
    await check('invalidated extension context retires timers and controls',async()=>{
      const page=await fixture({invalidated:true});await page.waitForTimeout(100);
      assert.match(await page.locator('#status').innerText(),/tải lại/i);
      const count=await page.evaluate(()=>fixture.calls.length);await page.waitForTimeout(1400);
      assert.equal(await page.evaluate(()=>fixture.calls.length),count);
      assert.equal(await page.locator('#start').isDisabled(),true);await page.close();
    });
    await check('paused failed video can inspect an old request without claim or retry',async()=>{
      const page=await fixture({active:false,recoverOnCheck:true,sessions:[job(child,'old','failed')],slots:[{scope:child,active:false,ownedTabs:[],job:{id:'old',phase:'uncertain',chatTab:4}}]});
      assert.equal(await card(page,child).getByRole('button',{name:'Mở chat',exact:true}).isDisabled(),true);
      await card(page,child).getByRole('button',{name:'Kiểm tra lại',exact:true}).click();
      await page.waitForFunction(()=>fixture.calls.filter(call=>call.kind==='snapshot').length>=2,{},{timeout:2000});
      assert.match(await card(page,child).innerText(),/ChatGPT: Đã có phản hồi/);
      const calls=await page.evaluate(()=>fixture.calls);
      assert.ok(calls.some(call=>call.kind==='reconcile'&&call.inspect_only===true&&call.scope===child));
      assert.equal(calls.some(call=>call.kind==='claim'||call.kind==='imported'||call.kind==='start'),false);await page.close();
    });
    await check('returning to visible Studio refreshes heartbeat and pending immediately',async()=>{
      const page=await fixture();await page.waitForFunction(()=>fixture.pendingPolls>=1);
      const before=await page.evaluate(()=>fixture.requests.length);
      await page.evaluate(()=>{Object.defineProperty(document,'visibilityState',{configurable:true,value:'visible'});document.dispatchEvent(new Event('visibilitychange'));});
      await page.waitForFunction(before=>fixture.requests.length>=before+3,before,{timeout:700});
      const requests=await page.evaluate(()=>fixture.requests);
      assert.ok(requests.slice(before).some(item=>item.url.endsWith('/status/'+bridge)));
      assert.ok(requests.some(item=>item.body&&JSON.parse(item.body).build==='videostudio-extension-0.3.0'));await page.close();
    });
    await check('Stop prevents a delayed pending poll from claiming a new request',async()=>{
      const page=await fixture({holdPending:true,sessions:[job(child,'one')],pending:[{scope:child,job_id:'one',id:'new',version:1,prompt:'Fixture only',attachments:[]}]});
      await page.waitForFunction(()=>typeof releasePending==='function');
      await page.locator('#stop').click();
      await page.evaluate(()=>{fixture.holdPending=false;releasePending();});
      await page.waitForTimeout(150);
      assert.equal(await page.evaluate(()=>fixture.calls.some(call=>call.kind==='claim')),false);await page.close();
    });
    await check('root control smoke bypasses a failed legacy video with explicit metadata',async()=>{
      const page=await fixture({sessions:[job(bridge,'legacy','failed')],pending:[{scope:bridge,job_id:null,is_smoke:true,id:'smoke',version:1,prompt:'Fixture only',attachments:[]}]});
      await page.waitForFunction(()=>fixture.calls.some(call=>call.kind==='claim'),{},{timeout:2000});
      const claim=await page.evaluate(()=>fixture.calls.find(call=>call.kind==='claim'));
      assert.equal(claim.scope,bridge);assert.equal(claim.is_smoke,true);assert.equal(claim.job_id,null);await page.close();
    });
    await check('verified current root smoke reply imports even when its legacy video failed',async()=>{
      const page=await fixture({sessions:[job(bridge,'legacy','failed')],slots:[{scope:bridge,is_smoke:true,job:{id:'receipt',version:3,phase:'reply',text:'{"ok":true}',is_smoke:true}}]});
      await page.waitForFunction(()=>fixture.calls.some(call=>call.kind==='imported'),{},{timeout:2000});
      assert.ok(await page.evaluate(({bridge})=>fixture.calls.some(call=>call.kind==='imported'&&call.scope===bridge),{bridge}));await page.close();
    });
    await check('legacy video card shows retained request and actions target its exact id',async()=>{
      const page=await fixture({sessions:[job(bridge,'legacy','failed')],slots:[{scope:bridge,is_smoke:true,job:{id:'current-smoke',version:2,phase:'sent',chatTab:6,is_smoke:true},retained:[{job_id:'legacy',job:{id:'retained-video',phase:'uncertain',chatTab:4,reason:'Retained error'},chatTab:4,ownedTabs:[4]}]}]});
      await card(page,bridge).waitFor();assert.equal(await card(page,bridge).getAttribute('data-request-id'),'retained-video');assert.doesNotMatch(await card(page,bridge).innerText(),/current-smoke|retained-video/);
      await card(page,bridge).getByRole('button',{name:'Mở chat',exact:true}).click();
      await card(page,bridge).getByRole('button',{name:'Kiểm tra lại',exact:true}).click();
      const calls=await page.evaluate(()=>fixture.calls);
      assert.ok(calls.some(call=>call.kind==='open_chat'&&call.scope===bridge&&call.id==='retained-video'));
      assert.ok(calls.some(call=>call.kind==='reconcile'&&call.scope===bridge&&call.id==='retained-video'&&call.inspect_only===true));
      assert.equal(calls.some(call=>call.kind==='imported'&&call.id==='retained-video'),false);await page.close();
    });
    await check('resumed legacy root video claims its retained request after smoke acknowledgement',async()=>{
      const page=await fixture({sessions:[job(bridge,'legacy','running')],slots:[{scope:bridge,is_smoke:true,job:null,retained:[{job_id:'legacy',job:{id:'old-video',version:1,phase:'uncertain',prompt:'Fixture only'},ownedTabs:[]}]}],pending:[{scope:bridge,job_id:'legacy',is_smoke:false,id:'old-video',version:1,prompt:'Fixture only',attachments:[]}]});
      await page.waitForFunction(()=>fixture.calls.some(call=>call.kind==='claim'),{},{timeout:2000});
      const claim=await page.evaluate(()=>fixture.calls.find(call=>call.kind==='claim'));
      assert.equal(claim.scope,bridge);assert.equal(claim.job_id,'legacy');assert.equal(claim.id,'old-video');assert.equal(claim.is_smoke,false);await page.close();
    });
    await check('collapsed error badge includes a root smoke without any video card',async()=>{
      const page=await fixture({workerTransient:true,slots:[{scope:bridge,is_smoke:true,job:{id:'control',version:1,phase:'sent',is_smoke:true}}]});
      await page.waitForFunction(()=>fixture.calls.some(call=>call.kind==='reconcile'),{},{timeout:2000});
      await page.locator('#collapse').click();assert.equal(await page.locator('#error-badge').isVisible(),true);await page.close();
    });
    await check('lost cancellation response recovers exact local video cancellation from server state',async()=>{
      const page=await fixture({throwAfterCancel:true,cancelTransientLeft:1,sessions:[job(child,'one','running'),job(other,'two','running')],slots:[{scope:child,job:{id:'first',phase:'sent',chatTab:4}},{scope:other,job:{id:'second',phase:'sent',chatTab:5}}]});
      await card(page,child).getByRole('button',{name:'Hủy',exact:true}).click();
      await page.waitForFunction(()=>fixture.slots.find(slot=>slot.scope.endsWith('001')).cancelled===true,{},{timeout:3600});
      const f=await page.evaluate(()=>fixture);
      assert.ok(f.calls.filter(call=>call.kind==='cancel_session').length>=2);
      assert.ok(f.calls.filter(call=>call.kind==='cancel_session').every(call=>call.scope===child&&call.job_id==='one'));
      assert.equal(f.slots.find(slot=>slot.scope===other).cancelled,undefined);assert.deepEqual(f.slots.find(slot=>slot.scope===other).ownedTabs,[5]);await page.close();
    });
    if(process.env.VS_MANAGER_DESKTOP_SCREENSHOT){
      const page=await fixture({sessions:[{...job(child,'one','running','Hành trình khám phá Đà Lạt'),stage:'script'},job(other,'two','queued','Những khu vườn yên bình')]});
      await page.setViewportSize({width:1280,height:800});await card(page,child).waitFor();
      await page.screenshot({path:process.env.VS_MANAGER_DESKTOP_SCREENSHOT});
      await page.setViewportSize({width:320,height:480});
      if(process.env.VS_MANAGER_SCREENSHOT)await page.screenshot({path:process.env.VS_MANAGER_SCREENSHOT});await page.close();
    }
  }finally{await browser.close();}
  if(failures.length)throw Error(`${failures.length} manager checks failed`);
})().catch(error=>{console.error(error);process.exitCode=1;});
