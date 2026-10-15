import { chromium } from 'playwright';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';

const base = process.env.TRIS_TEST_URL || 'http://127.0.0.1:7860';
const browser = await chromium.launch({
  executablePath:
    process.env.TRIS_BROWSER || 'C:/Program Files/Google/Chrome/Application/chrome.exe',
  headless: true,
});
const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await context.newPage();
const errors = [];
page.on('pageerror', (e) => errors.push(e.message));
const bodies = [];
let mediaAuth = '';
let audioRequests = 0;
const names = (await fs.readdir('../data/generated')).filter((f) => f.endsWith('.png')).sort();
const fixture = await fs.readFile(path.join('../data/generated', names.at(-1)));
await page.addInitScript(() =>
  sessionStorage.setItem(
    'tris.workspace.session',
    JSON.stringify({
      token: 'media-browser-fixture',
      account: { account_id: 'media-ui', username: 'QA', learner_name: 'QA' },
    }),
  ),
);
await page.route('**/health', (r) => r.fulfill({ json: { status: 'ok', auth_required: true } }));
await page.route('**/v1/**', async (r) => {
  const p = new URL(r.request().url()).pathname;
  if (p === '/v1/workspace/presence') return r.continue();
  if (p === '/v1/workspace/models')
    return r.fulfill({
      json: { default: 'english-tutor-local:4b', models: [{ name: 'english-tutor-local:4b' }] },
    });
  if (p === '/v1/workspace/session')
    return r.fulfill({ json: { chats: [], settings: { language: 'vi' } } });
  if (p === '/v1/workspace/chat') {
    bodies.push(r.request().postDataJSON());
    return r.fulfill({
      contentType: 'application/x-ndjson',
      body:
        [
          { status: 'Đang tạo ảnh local…' },
          {
            delta: 'Đã tạo bằng model local.\n\n[Tris media: image](/v1/media/tris_image_test.png)',
          },
          { done: true, seconds: 52 },
        ]
          .map((e) => JSON.stringify(e))
          .join('\n') + '\n',
    });
  }
  if (p === '/v1/media/tris_image_test.png') {
    mediaAuth = r.request().headers().authorization;
    return r.fulfill({ contentType: 'image/png', body: fixture });
  }
  if (p === '/v1/speech') {
    audioRequests++;
    return r.fulfill({ status: 503, json: { detail: 'Giọng mẫu đang bận; không thay giọng.' } });
  }
  return r.fulfill({ json: {} });
});
let passed = 0;
const ok = (label, v = true) => {
  assert.ok(v, label);
  passed++;
  console.log('PASS ' + label);
};
try {
  await page.goto(base);
  await page.locator('.composer-card textarea').waitFor();
  await page.getByRole('button', { name: 'Đính kèm tệp', exact: true }).click();
  await page.getByRole('button', { name: 'Tạo ảnh trong chat', exact: true }).click();
  ok(
    'No second chat or media modal',
    (await page.locator('.modal').count()) === 0 &&
      (await page.locator('.composer-card textarea').count()) === 1,
  );
  ok(
    'Inline creation mode visible',
    (await page.locator('.tool-chip').innerText()).includes('Tạo ảnh'),
  );
  await page.locator('.composer-card textarea').fill('A tiny turquoise fox reading a book');
  await page.getByRole('button', { name: 'Gửi tin nhắn', exact: true }).click();
  await page.locator('.chat-generated-media img').waitFor();
  await page.waitForFunction(
    () => document.querySelector('.chat-generated-media img')?.naturalWidth > 0,
  );
  ok(
    'Image creation request dispatched in current chat',
    bodies.length === 1 && bodies[0].action === 'image',
  );
  ok(
    'Generated file request uses account authorization',
    mediaAuth === 'Bearer media-browser-fixture',
  );
  ok('Image download present', await page.locator('.chat-generated-media a[download]').isVisible());
  ok(
    'Image generation duration displayed',
    (await page.locator('.processing-time').innerText()).includes('52 giây'),
  );
  ok('No automatic audio playback', audioRequests === 0);
  await page.getByRole('button', { name: 'Đọc câu trả lời', exact: true }).click();
  await page.locator('.toast').waitFor();
  ok(
    'Voice conversion error is visible without substitution',
    (await page.locator('.toast').innerText()).includes('không thay giọng'),
  );
  await page.waitForTimeout(450);
  await page.reload();
  await page.locator('.chat-generated-media img').waitFor();
  ok(
    'Generated image survives reloading conversation',
    await page.locator('.chat-generated-media img').isVisible(),
  );
  await page.screenshot({ path: 'test-results/chat-generated-image.png' });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator('.chat-generated-media img').waitFor();
  await page.waitForFunction(
    () => document.querySelector('.app-frame')?.getAttribute('data-layout') === 'mobile',
  );
  const b = await page.locator('.chat-generated-media img').boundingBox();
  ok('Generated image fits mobile viewport', b.x >= 0 && b.x + b.width <= 391);
  ok('No JavaScript errors', errors.length === 0);
  console.log(`${passed} media UI assertions passed (isolated browser fixtures).`);
} finally {
  await browser.close();
}
