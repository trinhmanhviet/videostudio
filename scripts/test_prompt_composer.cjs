/* Offline real-Chromium composer regressions. No account or model requests.
   The optional recorded prompt is read from SQLite in read-only mode and never logged. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {execFileSync}=require('node:child_process');
const {createHash}=require('node:crypto');
const {chromium}=require(process.env.VS_PLAYWRIGHT_PATH||'C:/Users/leath/AppData/Local/Programs/aicoworker/resources/openclaw/node_modules/playwright-core');
const root=path.resolve(__dirname,'..'),failures=[];
const expectedExchange='2094a37e-4aae-4fda-a650-c1f5198f87fd';
const normalise=value=>value.replace(/\u00a0/g,' ').replace(/\s+/g,' ').trim();
async function check(name,fn){try{await fn();console.log('PASS',name);}catch(error){failures.push(name);console.error('FAIL',name,error.message);}}
function recordedPrompt(){
  const db=path.join(root,'data/jobs.sqlite3');
  if(!fs.existsSync(db))return null;
  const source="import sqlite3,json,sys\nc=sqlite3.connect('file:'+sys.argv[1].replace('\\\\','/')+'?mode=ro',uri=True)\nr=c.execute('select prompt from connector_exchanges where id=?',(sys.argv[2],)).fetchone()\nprint(json.dumps(r[0] if r else None))";
  return JSON.parse(execFileSync(process.env.VS_PYTHON||'python',['-c',source,db,expectedExchange],{encoding:'utf8'}));
}
(async()=>{
  const actual=recordedPrompt();
  if(actual){
    assert.equal(createHash('sha256').update(actual).digest('hex'),'ed5187095e7eb04b25339bd9cd425c3443895e4f24f1a8246c373fd2afb79716');
    assert.equal(normalise(actual).length,6134);
    assert.equal(actual.indexOf('https://'),1591);
    assert.equal((actual.match(/https:\/\//g)||[]).length,7);
  }
  const browser=await chromium.launch({executablePath:process.env.VS_CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
  const context=await browser.newContext();
  await context.route('**/*',route=>route.fulfill({contentType:'text/html',body:'<!doctype html><html><body></body></html>'}));
  async function chat(options={}){
    const page=await context.newPage();await page.goto('https://chatgpt.com/');
    await page.setContent('<style>.ProseMirror{white-space:pre-wrap}.ProseMirror p{margin:1em 0}</style><div role="group" aria-label="Composer mode"><button aria-selected="true">Chat</button><button aria-selected="false">Work</button></div><form><div id="prompt-textarea" class="ProseMirror" contenteditable="true" role="textbox" aria-label="Message ChatGPT"><p><br class="ProseMirror-trailingBreak"></p></div><button type="button" aria-label="Send">Send</button></form>');
    await page.evaluate(options=>{
      window.messages=[];window.clicks=0;window.sentDraft=null;window.insertions=[];window.invalidInput=false;
      window.chrome={runtime:{sendMessage:async message=>{messages.push(message);return {ok:true};},onMessage:{addListener:listener=>window.extensionListener=listener}}};
      const input=document.querySelector('#prompt-textarea');
      if(options.draft)input.firstChild.textContent=options.draft;
      const original=document.execCommand.bind(document);
      document.execCommand=(command,show,value)=>{
        if(command==='insertText'){
          insertions.push(value.length);
          if(options.truncate&&value.length>1500)value=value.slice(0,80);
        }
        return original(command,show,value);
      };
      input.addEventListener('input',()=>{
        const value=input.textContent;
        if(typeof value.isWellFormed==='function'&&!value.isWellFormed())invalidInput=true;
        if(options.corrupt){
          for(const node of input.querySelectorAll('[data-corruption]'))node.remove();
          input.normalize();
          const walker=document.createTreeWalker(input,NodeFilter.SHOW_TEXT),nodes=[];let node;
          while(node=walker.nextNode())nodes.push(node);
          for(const node of nodes){
            const matches=[...node.data.matchAll(/https:\/\//g)];if(!matches.length)continue;
            const fragment=document.createDocumentFragment();let offset=0;
            for(const match of matches){
              fragment.append(node.data.slice(offset,match.index));
              const extra=document.createElement('span');extra.dataset.corruption='true';extra.textContent='\u200b';fragment.append(extra);offset=match.index;
            }
            fragment.append(node.data.slice(offset));node.replaceWith(fragment);
          }
          const range=document.createRange();range.selectNodeContents(input);range.collapse(false);const selection=getSelection();selection.removeAllRanges();selection.addRange(range);
        }
      });
      document.querySelector('button[aria-label="Send"]').onclick=()=>{
        clicks++;sentDraft=VideoStudioLogicalText.logicalText(input);
        const user=document.createElement('div');user.setAttribute('data-message-author-role','user');user.style.whiteSpace='pre-wrap';user.textContent=sentDraft;document.body.append(user);input.innerHTML='<p><br class="ProseMirror-trailingBreak"></p>';
        const reply=document.createElement('section');reply.setAttribute('data-talvt-turn-state','complete');reply.innerHTML='<div data-message-author-role="assistant"><pre><code>{"ok":true}</code></pre></div>';document.body.append(reply);
      };
    },options);
    for(const file of ['send-button.js','logical-text.js','chatgpt.js'])await page.addScriptTag({path:path.join(root,'extensions/videostudio-chatgpt',file)});
    return page;
  }
  async function deliver(page,prompt){
    const id=prompt.split('\n')[0].slice('YÊU CẦU STUDIO '.length);
    await page.evaluate(({id,prompt})=>extensionListener({kind:'deliver',id,attempt:1,prompt},null,()=>{}),{id,prompt});
    await page.waitForFunction(()=>messages.some(message=>['reply','uncertain'].includes(message.kind)),undefined,{timeout:14000});
    return page.evaluate(()=>({clicks,sentDraft,messages,insertions,invalidInput}));
  }
  try{
    await check('logical paragraphs read text independently of URL layout',async()=>{
      const page=await chat();
      const result=await page.evaluate(()=>{
        const input=document.querySelector('#prompt-textarea');
        input.innerHTML='<p>source: &quot;<a href="https://example.test" style="display:block">https://example.test</a>&quot;</p><p><br class="ProseMirror-trailingBreak"></p><p>Đoạn cuối 🐭</p>';
        return {logical:VideoStudioLogicalText.logicalText(input),rendered:input.innerText};
      });
      assert.equal(result.logical,'source: "https://example.test"\n\nĐoạn cuối 🐭');
      assert.notEqual(result.logical,result.rendered);await page.close();
    });
    await check('logical paragraph reader preserves intentional inline breaks and Unicode characters',async()=>{
      const page=await chat();
      const result=await page.evaluate(()=>{
        const input=document.querySelector('#prompt-textarea');
        input.innerHTML='<p>one<br>two<span>\u200b\u200d🐭</span><br class="ProseMirror-trailingBreak"></p><p><br></p>';
        return VideoStudioLogicalText.logicalText(input);
      });
      assert.equal(result,'one\ntwo\u200b\u200d🐭\n');await page.close();
    });
    await check('complete prompt text is independent of block and flex URL layout',async()=>{
      const prompt=actual||'YÊU CẦU STUDIO req\nsource: "https://example.test"';
      const page=await chat();
      const result=await page.evaluate(prompt=>{
        const input=document.querySelector('#prompt-textarea');input.replaceChildren();
        for(const line of prompt.split('\n')){
          const paragraph=document.createElement('p');let offset=0;
          for(const match of line.matchAll(/https:\/\/[^\s"]+/g)){
            paragraph.append(line.slice(offset,match.index));
            const link=document.createElement('a');link.href=match[0];link.textContent=match[0];link.style.display=offset?'flex':'block';paragraph.append(link);offset=match.index+match[0].length;
          }
          paragraph.append(line.slice(offset));input.append(paragraph);
        }
        return {logical:VideoStudioLogicalText.logicalText(input),rendered:input.innerText};
      },prompt);
      assert.ok(result.logical===prompt,'link layout changed logical immutable prompt text');
      assert.ok(normalise(result.logical)!==normalise(result.rendered),'link layout did not exercise rendered-text differences');await page.close();
    });
    await check('long Vietnamese paragraphs and blank lines survive native insertion and leftover draft clearing',async()=>{
      const prompt='YÊU CẦU STUDIO req\n\n'+('Đám cưới chuột, nhạc lễ và lời kể. 🐭\n\n'.repeat(110))+'Kết thúc.';
      const page=await chat({draft:'Old draft must be removed.\nAnother line.'});const result=await deliver(page,prompt);
      assert.equal(result.messages.at(-1).kind,'reply');assert.equal(result.clicks,1);assert.ok(result.sentDraft===prompt,'paragraphs, blank lines or Unicode changed');await page.close();
    });
    await check('chunk repair never emits a lone surrogate at its 1500-unit boundary',async()=>{
      const prefix='YÊU CẦU STUDIO req\n';
      const prompt=prefix+'a'.repeat(1499-prefix.length)+'🐭'+(' Việt Nam\n'.repeat(260));
      const page=await chat({truncate:true});const result=await deliver(page,prompt);
      assert.equal(result.messages.at(-1).kind,'reply');assert.equal(result.clicks,1);assert.ok(result.sentDraft===prompt,'chunk repair changed the prompt');assert.equal(result.invalidInput,false,'a repair input event contained a lone Unicode surrogate');await page.close();
    });
    await check('unexplained URL characters still block Send and expose bounded DOM evidence',async()=>{
      const prompt=actual||'YÊU CẦU STUDIO req\n'+('Tiếng Việt. '.repeat(145))+'source: "https://example.test/path"';
      const page=await chat({corrupt:true});const result=await deliver(page,prompt),message=result.messages.at(-1);
      assert.equal(message.kind,'uncertain');assert.equal(result.clicks,0);assert.equal(message.send_attempted,false);
      assert.match(message.reason,/Composer does not match/);
      assert.ok(message.composer_diagnostic,'mismatch has no bounded composer diagnostic');
      assert.equal(message.composer_diagnostic.expected_length,normalise(prompt).length);
      assert.equal(message.composer_diagnostic.actual_length,normalise(prompt).length+(actual?7:1));
      if(actual)assert.equal(message.composer_diagnostic.first_diff,1591);
      assert.ok(message.composer_diagnostic.actual_codepoints.includes('U+200B'));
      assert.ok(message.composer_diagnostic.editor_html_excerpt.includes('data-corruption'));
      assert.ok(JSON.stringify(message.composer_diagnostic).length<6000);await page.close();
    });
    if(actual){
      for(const truncate of [false,true])await check(`complete recorded 6134-character prompt survives native paragraphs (${truncate?'chunk repair':'full insert'})`,async()=>{
        const page=await chat({truncate,draft:'Leftover draft'});const result=await deliver(page,actual);
        assert.equal(result.messages.at(-1).kind,'reply');assert.equal(result.clicks,1);assert.ok(result.sentDraft===actual,'complete recorded immutable prompt changed');await page.close();
      });
    }else console.log('SKIP recorded prompt absent; set up the read-only local SQLite fixture for the complete real-prompt checks');
  }finally{await browser.close();}
  if(failures.length)throw Error(`${failures.length} composer checks failed: ${failures.join('; ')}`);
})().catch(error=>{console.error(error.message);process.exitCode=1;});
