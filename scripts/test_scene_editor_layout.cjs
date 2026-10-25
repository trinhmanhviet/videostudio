/* Real Chromium layout regression for Page View Scene Editor.
   Uses the app's shipped playwright-core; never attaches to a user's Chrome. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { chromium } = require(process.env.VS_PLAYWRIGHT_PATH || 'C:/Users/leath/AppData/Local/Programs/aicoworker/resources/openclaw/node_modules/playwright-core');
const root = path.resolve(__dirname, '..');
const evidence = process.env.VS_LAYOUT_EVIDENCE || path.join(root, 'data', 'mobile-layout');
fs.mkdirSync(evidence, { recursive: true });

const fixture = {
  job_id: 'layout-fixture',
  version: 0,
  mode: 'quick',
  editable: true,
  state: 'completed',
  scenes: [0, 1, 2].map(i => ({
    scene_id: 'scene-' + i,
    index: i,
    start: i * 3,
    end: (i + 1) * 3,
    duration: 3,
    narration: 'Lời đọc cảnh ' + (i + 1) + ' được giữ nguyên khi thay ảnh.',
    image_url: '/fixture-image',
    audio_url: '/fixture-audio',
    image_sha256: 'fixture',
    edit_id: 'original',
    fit: 'original',
    review_status: 'needs_review',
    history: []
  }))
};

(async () => {
  const browser = await chromium.launch({
    executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe',
    headless: true
  });
  try {
    const results = [];
    for (const [width, height] of [[390, 740], [360, 640], [480, 800], [844, 390], [1280, 900]]) {
      const context = await browser.newContext({
        viewport: { width, height },
        isMobile: width < 900,
        deviceScaleFactor: 1,
        hasTouch: width < 900
      });
      const page = await context.newPage();
      const rawHtml = fs.readFileSync(path.join(root, 'static/index.html'), 'utf8');

      await page.route('http://layout.test/**', async route => {
        const url = new URL(route.request().url());
        if (url.pathname === '/') {
          return route.fulfill({ contentType: 'text/html', body: rawHtml });
        }
        if (url.pathname.startsWith('/scene-editor.js')) {
          return route.fulfill({ contentType: 'application/javascript', body: fs.readFileSync(path.join(root, 'static/scene-editor.js'), 'utf8') });
        }
        if (url.pathname.startsWith('/scene-generation-ui.js')) {
          return route.fulfill({ contentType: 'application/javascript', body: fs.readFileSync(path.join(root, 'static/scene-generation-ui.js'), 'utf8') });
        }
        if (url.pathname === '/fixture-image') {
          return route.fulfill({
            contentType: 'image/svg+xml',
            body: '<svg xmlns="http://www.w3.org/2000/svg" width="360" height="640"><rect width="360" height="640" fill="#42583a"/><text x="40" y="320" fill="white" font-size="28">Scene image</text></svg>'
          });
        }
        if (url.pathname.endsWith('/scene-editor')) {
          return route.fulfill({ json: fixture });
        }
        if (url.pathname.endsWith('/generations')) {
          return route.fulfill({ json: { items: [], providers: ['chatgpt'] } });
        }
        return route.fulfill({ status: 404, body: 'not implemented' });
      });

      await page.goto('http://layout.test/');
      await page.evaluate(() => window.openSceneEditor('layout-fixture'));
      await page.locator('.se-card').first().waitFor();

      const measures = () => page.evaluate(() => {
        const rect = s => {
          const el = document.querySelector(s);
          if (!el) return { top: 0, bottom: 0, height: 0, width: 0 };
          const r = el.getBoundingClientRect();
          return { top: r.top, bottom: r.bottom, height: r.height, width: r.width };
        };
        const image = rect('.se-main-image');
        const header = rect('.se-page-header');
        const view = rect('#viewSceneEditor');
        return {
          viewport: { width: innerWidth, height: innerHeight },
          image,
          header,
          view,
          overflow: document.documentElement.scrollWidth > innerWidth
        };
      });

      const m = await measures();
      await page.screenshot({ path: path.join(evidence, `page-view-${width}x${height}.png`) });
      results.push(m);
      console.log(`Measured ${width}x${height}:`, JSON.stringify(m));

      assert.equal(m.viewport.width, width, 'must test actual mobile CSS width');
      assert.equal(m.overflow, false, 'no horizontal overflow on page');
      assert.ok(m.header.height <= Math.max(160, height * 0.25), 'page header must not dominate viewport');
      assert.ok(m.image.height >= 120, 'main scene image must have visible height');

      // Verify buttons exist and match mockup
      const firstCard = page.locator('.se-card').first();
      assert.ok(await firstCard.locator('.se-btn-green', { hasText: 'Browse' }).isVisible(), 'Browse button visible');
      assert.ok(await firstCard.locator('.se-btn-green', { hasText: 'Vẽ lại' }).isVisible(), 'Vẽ lại button visible');
      assert.ok(await firstCard.locator('.se-provider-radios').isVisible(), 'Provider radios visible');
      assert.ok(await firstCard.locator('.se-thumbs-grid').isVisible(), 'Thumbnail grid visible');

      // Verify Back button works and restores view
      await page.locator('#btnBackFromEditor').click();
      assert.equal(await page.locator('#viewSceneEditor').isHidden(), true, 'editor hidden after Back');
      assert.equal(await page.locator('#viewGallery').isVisible(), true, 'gallery restored after Back');

      await context.close();
    }
    fs.writeFileSync(path.join(evidence, 'page-view-measurements.json'), JSON.stringify(results, null, 2));
    console.log('All layout responsive checks passed!');
  } finally {
    await browser.close();
  }
})().catch(e => {
  console.error(e);
  process.exitCode = 1;
});
