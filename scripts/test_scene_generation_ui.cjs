/* Isolated UI regression for mockup-based Scene Editor card.
   All generation/apply calls mocked, no account use. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { chromium } = require(process.env.VS_PLAYWRIGHT_PATH || 'C:/Users/leath/AppData/Local/Programs/aicoworker/resources/openclaw/node_modules/playwright-core');
const root = path.resolve(__dirname, '..');
const out = process.env.VS_GENERATION_EVIDENCE || path.join(root, 'data/generation-ui-smoke');
fs.mkdirSync(out, { recursive: true });

(async () => {
  const browser = await chromium.launch({
    executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe',
    headless: true
  });
  try {
    for (const width of [390, 1280]) {
      const context = await browser.newContext({
        viewport: { width, height: 800 },
        isMobile: width < 600,
        hasTouch: width < 600
      });
      const page = await context.newPage();
      page.on('console', msg => console.log('PAGE LOG:', msg.text()));
      page.on('pageerror', e => console.error('PAGE ERROR:', e.message));
      page.on('response', res => { if (res.status() === 404) console.log('404 URL:', res.url()); });
      let submissions = 0;
      let applied = 0;
      let task = null;

      const view = {
        job_id: 'fixture',
        version: 0,
        mode: 'quick',
        editable: true,
        scenes: [{
          scene_id: 's-one',
          index: 0,
          start: 0,
          end: 3,
          duration: 3,
          narration: 'Một cảnh mẫu, giữ lời đọc và thời lượng.',
          visual_prompt: 'A red apple on a table, no text',
          image_url: '/original?edit=original',
          audio_url: '/audio',
          image_sha256: 'original',
          edit_id: 'original',
          fit: 'original',
          review_status: 'needs_review',
          history: []
        }]
      };

      await page.route('http://localhost:9881/**', async route => {
        const req = route.request();
        const u = new URL(req.url());

        if (u.pathname === '/') {
          return route.fulfill({
            contentType: 'text/html',
            body: fs.readFileSync(path.join(root, 'static/index.html'), 'utf8')
          });
        }
        if (u.pathname.startsWith('/scene-editor.js')) {
          return route.fulfill({
            contentType: 'application/javascript',
            body: fs.readFileSync(path.join(root, 'static/scene-editor.js'), 'utf8')
          });
        }
        if (u.pathname.startsWith('/scene-generation-ui.js')) {
          return route.fulfill({
            contentType: 'application/javascript',
            body: fs.readFileSync(path.join(root, 'static/scene-generation-ui.js'), 'utf8')
          });
        }
        if (u.pathname.includes('/image') || u.pathname === '/original' || u.pathname === '/candidate') {
          return route.fulfill({
            contentType: 'image/svg+xml',
            body: '<svg xmlns="http://www.w3.org/2000/svg" width="360" height="640"><rect width="360" height="640" fill="' + (u.pathname.includes('candidate') ? '#843b28' : '#53664b') + '"/><text x="30" y="300" fill="white" font-size="28">' + (u.pathname.includes('candidate') ? 'Candidate' : 'Original') + '</text></svg>'
          });
        }
        if (u.pathname.endsWith('/scene-editor')) {
          return route.fulfill({ json: view });
        }
        if (u.pathname.endsWith('/generations')) {
          if (req.method() === 'POST') {
            submissions++;
            const b = req.postDataJSON();
            assert.equal(b.provider, 'chatgpt');
            assert.ok(b.prompt.includes('red apple'));
            task = { id: 'candidate-one', state: 'queued', provider: 'chatgpt', prompt: b.prompt };
            return route.fulfill({ status: 202, json: task });
          }
          if (task) task = { ...task, state: 'completed', image_url: '/candidate' };
          return route.fulfill({ json: { items: task ? [task] : [], providers: ['chatgpt'] } });
        }
        if (u.pathname.endsWith('/candidate-one/apply')) {
          applied++;
          assert.equal(req.postDataJSON().version, 0);
          view.version = 1;
          view.scenes[0] = {
            ...view.scenes[0],
            image_url: '/candidate?selected=true',
            edit_id: 'generated-edit',
            image_sha256: 'candidate',
            history: [{ id: 'generated-edit', provider: 'chatgpt', created: 1 }]
          };
          return route.fulfill({ json: view });
        }
        return route.fulfill({ status: 404, body: 'route unavailable' });
      });

      await page.goto('http://localhost:9881/');
      await page.evaluate(() => window.openSceneEditor('fixture'));
      await page.locator('.se-card').waitFor();

      // Click "Vẽ lại" button
      const regenBtn = page.locator('.se-btn-green', { hasText: 'Vẽ lại' });
      await regenBtn.click();
      assert.equal(submissions, 1);
      assert.equal(applied, 0, 'generating never applies implicitly');

      // Wait for candidate thumbnail to appear in grid
      const candidateSelect = page.locator('.se-history-select');
      await page.waitForFunction(() => !!document.querySelector('option[value="candidate:candidate-one"]'));

      await page.screenshot({ path: path.join(out, `mockup-card-${width}.png`) });

      // Click candidate thumb to apply
      await candidateSelect.selectOption('candidate:candidate-one');
      await page.waitForFunction(() => {
        const img = document.querySelector('.se-main-image');
        return img && img.getAttribute('src').includes('selected=true');
      });

      assert.equal(applied, 1);
      assert.equal(view.scenes[0].duration, 3);
      assert.equal(view.scenes[0].narration, 'Một cảnh mẫu, giữ lời đọc và thời lượng.');

      console.log(JSON.stringify({ width, submissions, applied, sceneDuration: view.scenes[0].duration }));
      await context.close();
    }
    console.log('Scene card mockup and regeneration flow verified successfully!');
  } finally {
    await browser.close();
  }
})().catch(e => {
  console.error(e);
  process.exitCode = 1;
});
