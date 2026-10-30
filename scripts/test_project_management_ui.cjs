/* Isolated Chrome regression: every request, including every mutation, is mocked.
   No local service, real projects, accounts, or output files are touched. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { chromium } = require(process.env.VS_PLAYWRIGHT_PATH || 'C:/Users/leath/AppData/Local/Programs/aicoworker/resources/openclaw/node_modules/playwright-core');
const root = path.resolve(__dirname, '..');
const evidence = path.join(root, 'tmp', 'project-management-ui');
fs.mkdirSync(evidence, { recursive: true });

(async () => {
  const browser = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true });
  try {
    for (const width of [320, 1280]) {
      const context = await browser.newContext({ viewport: { width, height: 900 } });
      const page = await context.newPage();
      const errors = [], queries = [], mutations = [];
      let conflict = false, heldResponse = null;
      let projects = Array.from({ length: 35 }, (_, i) => ({ name: 'Dự án ' + String(i + 1).padStart(2, '0'), idea: 'Hà Nội lịch sử', count: 1, latest_state: 'completed', archived: false }));
      projects.push({ name: '<img src=x onerror=alert(1)>', idea: 'literal markup', count: 0, archived: false });
      projects.push({ name: 'Lưu trữ Hà Nội', idea: 'Dự án đã lưu', count: 1, archived: true });
      page.on('pageerror', e => errors.push(e.message));
      await page.route('**/*', async route => {
        const req = route.request(), u = new URL(req.url());
        if (u.origin !== 'http://projects.test') return route.abort();
        if (u.pathname === '/') return route.fulfill({ contentType: 'text/html', body: fs.readFileSync(path.join(root, 'static/index.html'), 'utf8') });
        if (/^\/[\w-]+\.js$/.test(u.pathname)) return route.fulfill({ contentType: 'application/javascript', body: fs.readFileSync(path.join(root, 'static', u.pathname.slice(1)), 'utf8') });
        if (req.method() === 'POST') {
          const body = req.postDataJSON();
          mutations.push({ path: u.pathname, body });
          if (u.pathname === '/api/projects/archive') {
            projects.find(p => p.name === body.name).archived = body.archived;
            return route.fulfill({ json: { ok: true } });
          }
          if (u.pathname === '/api/projects/delete') {
            if (conflict) return route.fulfill({ status: 409, json: { detail: 'Tệp đang được dự án khác tham chiếu. Hãy chọn giữ tệp.' } });
            projects = projects.filter(p => p.name !== body.name);
            return route.fulfill({ json: { ok: true } });
          }
          if (u.pathname === '/api/projects') return route.fulfill({ status: 409, json: { detail: 'Tên dự án đã tồn tại' } });
          throw Error('Unexpected mutation: ' + u.pathname);
        }
        if (u.pathname === '/api/projects') {
          const q = Object.fromEntries(u.searchParams); queries.push(q);
          const archived = q.archived === 'true', pageSize = Number(q.page_size || 10);
          const items = projects.filter(p => p.archived === archived && (p.name + ' ' + p.idea).toLocaleLowerCase().includes((q.q || '').toLocaleLowerCase()));
          const totalPages = Math.max(1, Math.ceil(items.length / pageSize)), pageNo = Math.min(Number(q.page || 1), totalPages);
          const payload = { items: items.slice((pageNo - 1) * pageSize, pageNo * pageSize), total: items.length, total_pages: totalPages, page: pageNo, page_size: pageSize };
          if (q.q === 'slow') { heldResponse = () => route.fulfill({ json: { ...payload, items: [{ name: 'STALE RESPONSE', count: 0 }] } }); return; }
          return route.fulfill({ json: payload });
        }
        if (u.pathname === '/api/preflight') return route.fulfill({ json: { ready: false, checks: [] } });
        if (u.pathname === '/api/browser/status') return route.fulfill({ json: { connected: false } });
        if (u.pathname === '/api/jobs' || u.pathname === '/api/voices') return route.fulfill({ json: { items: [] } });
        return route.fulfill({ json: {} });
      });
      await page.goto('http://projects.test/');
      await page.locator('#projectSearch').waitFor({ timeout: 2500 });
      await page.waitForFunction(() => document.querySelectorAll('.project-card').length === 10);
      assert.deepEqual(queries[0], { archived: 'false', q: '', page: '1', page_size: '10' });
      await page.locator('#projectNextPage').click();
      await page.waitForFunction(() => document.querySelector('#projectPageStatus').textContent.includes('2 / 4'));
      assert.equal(queries.at(-1).page, '2');
      await page.locator('#projectPrevPage').click();
      await page.waitForFunction(() => document.querySelector('#projectPageStatus').textContent.includes('1 / 4'));
      for (const size of ['20', '30', '10']) {
        await page.locator('#projectPageSize').selectOption(size);
        await page.waitForFunction(n => document.querySelectorAll('.project-card').length === n, Number(size));
        assert.equal(queries.at(-1).page_size, size); assert.equal(queries.at(-1).page, '1');
      }
      await page.locator('#projectSearch').fill('HÀ NỘI');
      await page.waitForFunction(() => document.querySelector('#projectPageStatus').textContent.includes('35 dự án'));
      assert.equal(queries.at(-1).q, 'HÀ NỘI');
      const firstName = await page.locator('.project-title').first().innerText();
      await page.locator('.project-archive').first().click();
      await page.waitForFunction(() => document.querySelector('#projectPageStatus').textContent.includes('34 dự án'));
      assert.deepEqual(mutations.at(-1), { path: '/api/projects/archive', body: { name: firstName, archived: true } });
      assert.equal(await page.locator('#viewWorkspace').isHidden(), true, 'archive never opens workspace');
      await page.locator('#projectViewArchive').click();
      await page.waitForFunction(() => document.querySelectorAll('.project-card').length === 2);
      assert.equal(queries.at(-1).archived, 'true'); assert.equal(queries.at(-1).q, 'HÀ NỘI');
      const restoreCard = page.locator('.project-card').filter({ has: page.locator('.project-title', { hasText: firstName }) });
      await restoreCard.locator('.project-archive').click();
      await page.waitForFunction(() => document.querySelectorAll('.project-card').length === 1);
      assert.deepEqual(mutations.at(-1).body, { name: firstName, archived: false });
      await page.locator('.project-delete').click();
      await page.locator('#projectDeleteModal').waitFor({ state: 'visible' });
      assert.equal(await page.locator('#projectDeleteKeepFiles').isChecked(), true);
      let before = mutations.length;
      await page.locator('#projectDeleteCancel').click();
      assert.equal(mutations.length, before, 'cancel sends no mutation');
      await page.locator('.project-delete').click();
      await page.locator('#projectDeleteConfirm').click();
      await page.locator('#projectDeleteModal').waitFor({ state: 'hidden' });
      assert.deepEqual(mutations.at(-1).body, { name: 'Lưu trữ Hà Nội', delete_files: false, confirm: true });
      await page.locator('#projectViewActive').click();
      await page.waitForFunction(() => document.querySelectorAll('.project-card').length === 10);
      await page.locator('.project-delete').first().click();
      await page.locator('#projectDeleteFiles').check();
      conflict = true;
      await page.locator('#projectDeleteConfirm').click();
      await page.waitForFunction(() => document.querySelector('#projectDeleteError').textContent.includes('tham chiếu'));
      assert.equal(await page.locator('#projectDeleteModal').isVisible(), true);
      assert.deepEqual(mutations.at(-1).body, { name: firstName, delete_files: true, confirm: true });
      conflict = false;
      await page.locator('#projectDeleteKeepFiles').check();
      await page.locator('#projectDeleteConfirm').click();
      await page.locator('#projectDeleteModal').waitFor({ state: 'hidden' });
      assert.equal(mutations.at(-1).body.delete_files, false);
      await page.locator('.project-delete').first().click();
      assert.equal(await page.locator('#projectDeleteKeepFiles').isChecked(), true, 'each dialog starts with keep-files');
      await page.locator('#projectDeleteFiles').check();
      const deletedName = await page.locator('.project-title').first().innerText();
      await page.locator('#projectDeleteConfirm').click();
      await page.locator('#projectDeleteModal').waitFor({ state: 'hidden' });
      assert.deepEqual(mutations.at(-1).body, { name: deletedName, delete_files: true, confirm: true });
      await page.locator('#projectSearch').fill('slow');
      await page.waitForFunction(() => document.querySelector('#projectSearch').value === 'slow');
      for (let i = 0; !heldResponse && i < 100; i++) await new Promise(r => setTimeout(r, 10));
      assert.ok(heldResponse, 'slow request reached fixture');
      await page.locator('#projectSearch').fill('Dự án 03');
      await page.waitForFunction(() => document.querySelectorAll('.project-card').length === 1 && document.querySelector('.project-title').textContent === 'Dự án 03');
      const staleFinished = page.waitForEvent('requestfinished', r => new URL(r.url()).searchParams.get('q') === 'slow');
      await heldResponse();await staleFinished;
      assert.equal(await page.locator('.project-title').innerText(), 'Dự án 03', 'late response cannot replace current query');
      await page.evaluate(() => loadProjects());
      assert.equal(queries.at(-1).q, 'Dự án 03', 'poll preserves search');
      await page.locator('#projectSearch').fill('<img');
      await page.waitForFunction(() => document.querySelector('.project-title')?.textContent.startsWith('<img'));
      assert.equal(await page.locator('.project-title img').count(), 0, 'project names remain literal text');
      await page.locator('.project-card').click();
      assert.equal(await page.locator('#viewWorkspace').isVisible(), true);
      assert.equal(await page.locator('#projectInput').inputValue(), '<img src=x onerror=alert(1)>');
      await page.locator('#btnBackToGallery').click();
      await page.locator('#btnCreateNewProject').click();
      await page.locator('#modalProjectName').fill('Duplicate fixture');
      await page.locator('#btnConfirmProjectModal').click();
      await page.waitForFunction(() => document.querySelector('#projectCreateError')?.textContent.includes('đã tồn tại'));
      assert.equal(await page.locator('#projectModal').isVisible(), true, 'create failure stays actionable');
      assert.equal(await page.locator('#viewWorkspace').isHidden(), true, 'failed creation does not open nonexistent project');
      await page.locator('#btnCancelProjectModal').click();
      await page.locator('#projectSearch').fill('Hà Nội');
      await page.waitForFunction(() => document.querySelectorAll('.project-card').length === 10);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, 'gallery fits viewport');
      await page.screenshot({ path: path.join(evidence, 'gallery-' + width + '.png') });
      await page.locator('.project-delete').first().click();
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, 'delete dialog fits viewport');
      await page.screenshot({ path: path.join(evidence, 'delete-' + width + '.png') });
      await page.locator('#projectDeleteCancel').click();
      assert.deepEqual(errors, []);
      console.log(JSON.stringify({ width, projectRequests: queries.length, mockedMutations: mutations.length }));
      await context.close();
    }
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
