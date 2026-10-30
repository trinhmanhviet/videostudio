/* Real Chromium recovery regression. Every API request is fulfilled locally;
   no service, account, GPU generation, or real job is touched. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { chromium } = require(process.env.VS_PLAYWRIGHT_PATH || 'C:/Users/leath/AppData/Local/Programs/aicoworker/resources/openclaw/node_modules/playwright-core');
const root = path.resolve(__dirname, '..');
const evidence = process.env.VS_RECOVERY_EVIDENCE || path.join(root, 'tmp', 'recovery-ui');
fs.mkdirSync(evidence, { recursive: true });
const source = name => fs.readFileSync(path.join(root, 'static', name), 'utf8');
const originalId = 'failed-music-fixture';
const originalIdea = 'Keep this original idea and its checkpoints';
const job = { id: originalId, status: 'running', state: 'running', stage: 'music', project: 'Recovery fixture', idea: originalIdea, created: 1, checkpoints: { speech: {}, images: {} }, error: null, diagnostics: null };
const scene = { scene_id: 's-one', index: 0, start: 0, end: 3, duration: 3, narration: 'Lời đọc đã hoàn tất.', image_url: '/fixture-image', audio_url: '/fixture-audio', image_sha256: 'fixture', edit_id: 'original', fit: 'original', review_status: 'needs_review', history: [] };
const view = { job_id: originalId, version: 0, mode: 'quick', state: 'failed', editable: true, can_export: false, missing_export_checkpoints: ['music'], export_unavailable_reason: 'Chưa thể xuất video vì còn thiếu bước: nhạc. Tiếp tục tác vụ gốc để hoàn tất.', recovery: { stage: 'music', label: 'Tiếp tục từ bước nhạc' }, scenes: [scene] };

(async () => {
  const browser = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true });
  try {
    for (const width of [390, 1280]) {
      const context = await browser.newContext({ viewport: { width, height: 900 } });
      const page = await context.newPage();
      const errors = [], mutations = [];
      let currentJob = { ...job }, currentView = structuredClone(view), exports = 0;
      page.on('pageerror', e => errors.push(e.message));
      await page.route('http://recovery.test/**', async route => {
        const req = route.request(), u = new URL(req.url());
        if (u.pathname === '/') return route.fulfill({ contentType: 'text/html', body: source('index.html') });
        if (u.pathname.endsWith('.js')) return route.fulfill({ contentType: 'application/javascript', body: source(u.pathname.slice(1)) });
        if (u.pathname === '/fixture-image' || u.pathname.includes('/image')) return route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="160"><rect width="100" height="160" fill="green"/></svg>' });
        if (req.method() === 'POST') {
          mutations.push({ path: u.pathname, body: req.postData() });
          if (u.pathname === '/api/jobs/' + originalId + '/retry') {
            currentJob = { ...currentJob, status: 'queued', state: 'queued', error: null, diagnostics: null };
            currentView = { ...currentView, state: 'queued', editable: false, can_export: false, recovery: null, export_unavailable_reason: 'Tác vụ đang chạy; chờ hoàn tất trước khi xuất video.' };
            return route.fulfill({ json: currentJob });
          }
          if (u.pathname.endsWith('/export')) { exports++; return route.fulfill({ json: { id: 'export-child-fixture' } }); }
          throw Error('Unexpected mutation: ' + u.pathname);
        }
        if (u.pathname === '/api/jobs') return route.fulfill({ json: { items: [currentJob] } });
        if (u.pathname.endsWith('/scene-editor')) return route.fulfill({ json: currentView });
        if (u.pathname.endsWith('/generations')) return route.fulfill({ json: { items: [], providers: ['chatgpt'] } });
        if (u.pathname === '/api/preflight') return route.fulfill({ json: { ready: false, checks: [] } });
        if (u.pathname === '/api/projects') return route.fulfill({ json: { items: [] } });
        if (u.pathname === '/api/voices') return route.fulfill({ json: { items: [] } });
        if (u.pathname === '/api/browser/status') return route.fulfill({ json: { connected: false } });
        return route.fulfill({ status: 404, json: { detail: 'Fixture route unavailable' } });
      });
      await page.goto('http://recovery.test/');
      await page.evaluate(j => {
        activeProject = j.project;
        document.querySelector('#viewGallery').hidden = true;
        document.querySelector('#viewWorkspace').hidden = false;
        document.querySelector('#idea').value = 'Leave this draft unchanged';
        document.querySelector('#projectJobsList').replaceChildren(renderJobCard(j));
      }, currentJob);
      const card = page.locator('#job-' + originalId);
      assert.equal(await card.locator('.job-cancel').count(), 1);
      currentJob = { ...currentJob, status: 'failed', state: 'failed', error: 'GPU VRAM unavailable' };
      await page.evaluate(j => updateJobCard(document.getElementById('job-' + j.id), j), currentJob);
      const resume = card.getByRole('button', { name: 'Tiếp tục từ bước nhạc', exact: true });
      assert.equal(await resume.count(), 1, 'running to failed exposes continuation without diagnostics');
      assert.equal(await resume.isVisible(), true);
      assert.equal(await card.locator('.job-cancel').count(), 0, 'failed state removes cancel');
      assert.match(await card.locator('.job-error').innerText(), /GPU VRAM/);
      assert.equal(await card.locator('.scene-editor-open').count(), 1);
      // A background poll can already be in flight when retry completes.
      await page.evaluate(() => { refreshing = true; });
      await resume.click();
      await page.waitForFunction(id => document.getElementById('job-' + id)?.dataset.status === 'queued', originalId, { timeout: 3000 });
      await page.evaluate(() => { refreshing = false; });
      assert.equal(await card.locator('.job-retry').count(), 0, 'queued state removes continuation');
      assert.equal(await card.locator('.scene-editor-open').count(), 0, 'active job removes stale editor action');
      assert.equal(await card.locator('.job-cancel').count(), 1);
      assert.equal(await card.locator('.job-error').isHidden(), true, 'retry clears stale failure');
      assert.deepEqual(mutations, [{ path: '/api/jobs/' + originalId + '/retry', body: null }]);
      assert.equal(await page.locator('#idea').inputValue(), 'Leave this draft unchanged');
      currentJob = { ...currentJob, status: 'running', state: 'running' };
      await page.evaluate(j => updateJobCard(document.getElementById('job-' + j.id), j), currentJob);
      assert.equal(await card.locator('.job-retry').count(), 0, 'running after retry has no stale recovery action');
      assert.equal(await card.locator('.job-cancel').isEnabled(), true);

      // Failed cards always derive their continuation label from the current stage.
      const labels = { plan: 'phân tích ý tưởng', research: 'tìm hiểu', script: 'viết kịch bản', speech: 'tạo lời đọc', images: 'tạo ảnh', subtitles: 'căn phụ đề', music: 'nhạc', render: 'dựng video', verify: 'kiểm tra thành phẩm', custom_stage: 'custom_stage' };
      for (const [stage, label] of Object.entries(labels)) {
        currentJob = { ...currentJob, status: 'failed', state: 'failed', stage, error: stage, diagnostics: { reason: 'Fixture failure', suggestion: 'Resume after checking prerequisites' } };
        await page.evaluate(j => updateJobCard(document.getElementById('job-' + j.id), j), currentJob);
        assert.equal(await card.getByRole('button', { name: 'Tiếp tục từ bước ' + label, exact: true }).count(), 1);
        assert.equal(await card.locator('.job-error').innerText(), stage);
      }
      currentView = structuredClone(view);
      await page.evaluate(id => window.openSceneEditor(id), originalId);
      await page.locator('.se-card').waitFor();
      assert.equal(await page.locator('#sePageExport').isDisabled(), true, 'missing music blocks export');
      assert.match(await page.locator('#seExportAvailability').innerText(), /thiếu bước: nhạc/);
      assert.equal(await page.getByRole('button', { name: 'Tiếp tục từ bước nhạc', exact: true }).isVisible(), true);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, 'recovery editor does not overflow');
      await page.screenshot({ path: path.join(evidence, 'missing-music-' + width + '.png') });
      await page.locator('#sePageExport').evaluate(el => el.click());
      assert.equal(exports, 0, 'disabled export never calls backend');
      await page.locator('#sePageResume').click();
      await page.waitForFunction(() => document.querySelector('#sePageResume').hidden);
      assert.equal(mutations.at(-1).path, '/api/jobs/' + originalId + '/retry');
      assert.equal(mutations.length, 2, 'both actions retry the original ID only');
      assert.equal(await page.locator('#sePageExport').isDisabled(), true);
      assert.equal(await page.locator('.se-history-select').isDisabled(), true, 'resumed source is read only');

      // Editor state changes do not bump edit version: refresh must still update availability.
      currentView = { ...view, state: 'completed', can_export: true, missing_export_checkpoints: [], export_unavailable_reason: null, recovery: null };
      await page.locator('#btnBackFromEditor').click();
      await page.locator('#viewSceneEditor').waitFor({ state: 'hidden' });
      await page.evaluate(id => window.openSceneEditor(id), originalId);
      await page.waitForFunction(() => !document.querySelector('#sePageExport').disabled, null, { timeout: 3000 });
      assert.equal(await page.locator('#seExportAvailability').isHidden(), true);
      assert.equal(await page.locator('#sePageResume').isHidden(), true);
      await page.locator('#sePageExport').click();
      await page.waitForFunction(() => document.querySelector('#sePageMessage').textContent.includes('export-c'));
      assert.equal(exports, 1, 'complete editor remains exportable');
      assert.deepEqual(errors, [], 'no page errors');
      console.log(JSON.stringify({ width, retryRequests: 2, exports, originalId, stages: Object.keys(labels).length }));
      await context.close();
    }
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
