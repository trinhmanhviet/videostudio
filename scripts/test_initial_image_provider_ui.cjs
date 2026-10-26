/* Isolated initial-video form test for image provider defaults and payload routing. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { chromium } = require(process.env.VS_PLAYWRIGHT_PATH || 'C:/Users/leath/AppData/Local/Programs/aicoworker/resources/openclaw/node_modules/playwright-core');
const root = path.resolve(__dirname, '..');

(async () => {
  const browser = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1000, height: 850 } });
    const submitted = [];
    let jobNumber = 0;
    await page.route('http://localhost:9882/**', async route => {
      const req = route.request();
      const url = new URL(req.url());
      if (url.pathname === '/') {
        return route.fulfill({ contentType: 'text/html', body: fs.readFileSync(path.join(root, 'static/index.html'), 'utf8') });
      }
      if (url.pathname === '/api/preflight') return route.fulfill({ json: { ready: true, checks: [] } });
      if (url.pathname === '/api/voices') return route.fulfill({ json: [{ id: 'preset:test', name: 'Test voice', available: true }] });
      if (url.pathname === '/api/projects') return route.fulfill({ json: { items: [{ name: 'Test project', created: 1 }], projects: ['Test project'] } });
      if (url.pathname === '/api/jobs' && req.method() === 'GET') return route.fulfill({ json: { items: [] } });
      if (url.pathname === '/api/browser/status') return route.fulfill({ json: { ok: true, connected: true, ready: true } });
      if (url.pathname === '/api/jobs' && req.method() === 'POST') {
        const payload = req.postDataJSON(); submitted.push(payload); jobNumber++;
        return route.fulfill({ status: 201, json: { id: `job-${jobNumber}`, job: { id: `job-${jobNumber}`, request: payload }, created: true } });
      }
      return route.fulfill({ status: 404, body: 'unmocked route: ' + url.pathname });
    });

    await page.goto('http://localhost:9882/');
    await page.locator('.project-card').waitFor();
    await page.locator('.project-card').click();
    await page.locator('#imageProvider').waitFor();
    await page.waitForFunction(() => !document.querySelector('#voice').disabled && document.querySelector('#voice').options.length > 1);

    const selector = page.locator('#imageProvider');
    assert.equal(await selector.inputValue(), 'flow', 'new video form defaults to Flow');
    assert.deepEqual(await selector.locator('option').evaluateAll(os => os.map(o => o.value)), ['flow', 'chatgpt', 'comfy']);

    for (const [index, provider] of ['flow', 'chatgpt', 'comfy'].entries()) {
      await selector.selectOption(provider);
      const note = await page.locator('#imageProviderNote').innerText();
      if (provider === 'flow') assert.match(note, /0 tín dụng/);
      if (provider === 'chatgpt') assert.match(note, /ChatGPT/i);
      if (provider === 'comfy') assert.match(note, /ComfyUI|Qwen/i);
      await page.locator('#idea').fill('Provider selection test: ' + provider);
      await page.locator('#voice').selectOption('preset:test');
      const [response] = await Promise.all([
        page.waitForResponse(r => new URL(r.url()).pathname === '/api/jobs' && r.request().method() === 'POST' && r.status() === 201),
        page.locator('#submit').click()
      ]);
      assert.equal(response.status(),201);
      assert.equal(submitted.length,index+1);
    }

    assert.deepEqual(submitted.map(x => x.image_provider), ['flow', 'chatgpt', 'comfy']);
    console.log(JSON.stringify({ default: 'flow', submitted: submitted.map(x => x.image_provider) }));
    console.log('Initial image provider form verified.');
  } finally {
    await browser.close();
  }
})().catch(e => { console.error(e); process.exitCode = 1; });
