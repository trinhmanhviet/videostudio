/* Read-only production verification: no generation, upload, apply or export. */
const fs=require('node:fs');const {chromium}=require('C:/Users/leath/AppData/Local/Programs/aicoworker/resources/openclaw/node_modules/playwright-core');
(async()=>{const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});try{
 const page=await browser.newPage({viewport:{width:1600,height:1000}});const mut=[];let lists=0,images=0;
 page.on('request',r=>{if(r.method()!=='GET')mut.push(r.url());if(new URL(r.url()).pathname.endsWith('/generations'))lists++;if(r.url().includes('/scene-editor/scenes/')&&r.url().includes('/image'))images++;});
 await page.goto('http://127.0.0.1:8877/#/editor/f9d386c3-ffef-4121-9e98-0b9caf4c4ddf');await page.locator('.se-card').first().waitFor({timeout:12000});
 await page.waitForFunction(()=>Array.from(document.querySelectorAll('.se-card')).every(c=>c.querySelector('.se-history-select').options.length>=1));
 const result=await page.evaluate(()=>({cards:document.querySelectorAll('.se-card').length,thumbnails:document.querySelectorAll('.se-thumb-wrap,.se-thumbs-grid').length,columns:getComputedStyle(document.querySelector('.se-grid')).gridTemplateColumns.split(' ').length,width:document.querySelector('main').getBoundingClientRect().width,viewport:innerWidth,page:document.querySelector('#sePageNumber').textContent,promptBelowDropdown:!!(document.querySelector('.se-history-select').compareDocumentPosition(document.querySelector('.se-prompt-toggle'))&Node.DOCUMENT_POSITION_FOLLOWING)}));
 if(result.cards!==12||result.columns!==4||result.thumbnails!==0||result.width!==1280||mut.length)throw Error(JSON.stringify({result,mut}));
 await page.evaluate(()=>document.querySelector('#viewSceneEditor').scrollIntoView());
 await page.waitForFunction(()=>Array.from(document.querySelectorAll('.se-main-image')).slice(0,4).every(i=>i.complete&&i.naturalWidth>0),{},{timeout:15000});
 const shot='C:/Users/leath/aicoworker/openclaw/workspace-main/tmp/editor-pagination-live.png';await page.screenshot({path:shot});
 const evidence={...result,lists,images,mutationRequests:mut.length,screenshot:shot};fs.writeFileSync('data/editor-pagination-verification.json',JSON.stringify(evidence,null,2));console.log(JSON.stringify(evidence));
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1});
