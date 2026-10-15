/**
 * Live interaction during content generation: queued follow-ups, quick
 * replies, honest progress statuses and completion actions. Runs against a
 * self-contained local server that streams NDJSON exactly like the real
 * workspace backend (media task holds the GPU, follow-ups queue behind it).
 */
import { chromium } from 'playwright';
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';

const root = path.resolve(import.meta.dirname, '..');
const dist = path.join(root, 'dist');
const mime = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript',
  '.css': 'text/css',
  '.svg': 'image/svg+xml',
  '.woff2': 'font/woff2',
};

const PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAYAAADED76LAAAAF0lEQVR4nGP8z8DwnwEPYMInOXwUAwAaGQ ManeuAAAAAElFTkSuQmCC',
  'base64',
);

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let mediaRunning = false;
let mediaDone = Promise.resolve();
let wakeMediaWaiters = () => {};
const bodies = [];

function serveChat(res, body) {
  res.writeHead(200, {
    'Content-Type': 'application/x-ndjson',
    'Cache-Control': 'no-store',
    'X-Accel-Buffering': 'no',
  });
  const send = (event) => res.write(JSON.stringify(event) + '\n');
  bodies.push(body);
  if (body.action === 'image' && !body.follow_up) {
    mediaRunning = true;
    mediaDone = new Promise((resolve) => {
      wakeMediaWaiters = resolve;
    });
    void (async () => {
      send({ status: 'Mình sẽ tạo ảnh từ mô tả của bạn bằng bộ sinh ảnh local sd-turbo.' });
      await sleep(700);
      send({ status: 'Đã chuẩn bị mô tả cho bộ tạo ảnh: "A tiny turquoise fox reading a book".' });
      await sleep(500);
      send({ status: 'Đang nạp bộ sinh ảnh sd-turbo vào GPU…' });
      await sleep(450);
      send({ status: 'Đang khử nhiễu bước 1/4…' });
      await sleep(450);
      send({ status: 'Đang khử nhiễu bước 2/4…' });
      await sleep(550);
      send({
        delta: 'Đã tạo bằng model local.\n\n[Tris media: image](/v1/media/tris_image_test.png)',
      });
      send({ done: true, seconds: 3, sources: [] });
      mediaRunning = false;
      wakeMediaWaiters();
      res.end();
    })();
    return;
  }
  void (async () => {
    if (body.follow_up) {
      send({ status: 'Đã xếp hàng: Tris sẽ trả lời ngay sau khi tác vụ hiện tại hoàn tất.' });
      await mediaDone;
      send({ delta: 'Chào bạn! Mình đã nhận yêu cầu bổ sung của bạn.' });
      send({ done: true, seconds: 1, sources: [] });
    } else {
      send({ delta: 'Trả lời nhanh từ Tris.' });
      send({ done: true, seconds: 1, sources: [] });
    }
    res.end();
  })();
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, 'http://127.0.0.1');
  if (url.pathname === '/health')
    return res.writeHead(200, { 'Content-Type': 'application/json' }).end(
      JSON.stringify({ status: 'ok', auth_required: true }),
    );
  if (url.pathname === '/v1/workspace/presence') {
    req.resume();
    return res.writeHead(200, { 'Content-Type': 'application/json' }).end('{}');
  }
  if (url.pathname === '/v1/workspace/models')
    return res.writeHead(200, { 'Content-Type': 'application/json' }).end(
      JSON.stringify({
        default: 'english-tutor-local:4b',
        models: [{ name: 'english-tutor-local:4b' }],
      }),
    );
  if (url.pathname === '/v1/workspace/session')
    return res.writeHead(200, { 'Content-Type': 'application/json' }).end(
      JSON.stringify({ chats: [], settings: { language: 'vi' } }),
    );
  if (url.pathname === '/v1/workspace/chat') {
    let raw = '';
    req.on('data', (chunk) => (raw += chunk));
    req.on('end', () => serveChat(res, JSON.parse(raw || '{}')));
    return;
  }
  if (url.pathname === '/v1/media/tris_image_test.png')
    return res.writeHead(200, { 'Content-Type': 'image/png' }).end(PNG);
  const file = path.join(
    dist,
    url.pathname === '/' ? 'index.html' : decodeURIComponent(url.pathname),
  );
  fs.readFile(file)
    .then((data) =>
      res
        .writeHead(200, { 'Content-Type': mime[path.extname(file)] || 'application/octet-stream' })
        .end(data),
    )
    .catch(() => {
      res.writeHead(404).end('not found');
    });
});
await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
const base = `http://127.0.0.1:${server.address().port}`;

const browser = await chromium.launch({
  executablePath:
    process.env.TRIS_BROWSER ||
    'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  headless: true,
});
const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await context.newPage();
const errors = [];
page.on('pageerror', (e) => errors.push(e.message));
await page.addInitScript(() =>
  sessionStorage.setItem(
    'tris.workspace.session',
    JSON.stringify({
      token: 'interaction-fixture',
      account: { account_id: 'interaction-ui', username: 'QA', learner_name: 'QA' },
    }),
  ),
);

let passed = 0;
const ok = (label, value = true) => {
  assert.ok(value, label);
  passed++;
  console.log('PASS ' + label);
};
const bodyText = () => page.locator('.chat-scroll').innerText();

try {
  await page.goto(base);
  await page.locator('.composer-card textarea').waitFor();

  await page.getByRole('button', { name: 'Đính kèm tệp', exact: true }).click();
  await page.getByRole('button', { name: 'Tạo ảnh trong chat', exact: true }).click();
  await page.locator('.composer-card textarea').fill('A tiny turquoise fox reading a book');
  await page.getByRole('button', { name: 'Gửi tin nhắn', exact: true }).click();

  // 1. Contextual confirmation is the first visible feedback.
  await page.waitForFunction(() =>
    document.querySelector('.chat-scroll')?.innerText.includes('sd-turbo'),
  );
  ok('Contextual confirmation shown for the image request');

  // 2. Honest live progress while the task runs.
  await page.waitForFunction(() =>
    document.querySelector('.chat-scroll')?.innerText.includes('Đang khử nhiễu bước'),
  );
  ok('Real render progress streamed into the status line');

  // 3. Chat stays usable; quick replies are offered while busy.
  await page.locator('.quick-replies .quick-reply').first().waitFor();
  ok('Quick replies visible while generating');
  await page.locator('.composer-card textarea').fill('Trong lúc chờ cho mình hỏi: ảnh này dùng được làm gì?');
  ok('Composer stays usable during generation');

  await page.getByRole('button', { name: 'Sáng màu hơn', exact: true }).click();
  await page.waitForFunction(() =>
    document.querySelector('.chat-scroll')?.innerText.includes('Đã nhận yêu cầu mới'),
  );
  ok('Follow-up acknowledged without touching the running task');
  await page.locator('.queue-badge').waitFor();
  ok('Queue badge counts the pending message');
  await page.locator('.queued-pill').first().waitFor();
  ok('Queued placeholder marked visually');

  // 4. The running task finishes on its own, untouched.
  await page.locator('.chat-generated-media img').first().waitFor();
  await page.waitForFunction(
    () => document.querySelector('.chat-generated-media img')?.naturalWidth > 0,
  );
  ok('Media task completes normally despite the follow-up');

  // 5. Queued turn is then answered automatically.
  await page.waitForFunction(() =>
    document.querySelector('.chat-scroll')?.innerText.includes('Mình đã nhận yêu cầu bổ sung'),
  );
  ok('Queued follow-up answered right after the task');
  ok(
    'Follow-up request asked the backend queue',
    bodies[1]?.follow_up === true && bodies[1]?.action === 'image',
  );

  // 6. Completion actions for the finished media result.
  await page.locator('.quick-replies.completion').waitFor();
  await page.getByRole('button', { name: 'Tạo biến thể', exact: true }).click();
  await page.waitForFunction(() => document.querySelectorAll('.chat-generated-media img').length === 2);
  ok(
    'Variation re-sends the original description as a new media request',
    bodies[2]?.action === 'image' && bodies[2]?.follow_up === false && bodies[2]?.message.includes('turquoise fox'),
  );

  ok('No JavaScript errors', errors.length === 0);
  await page.screenshot({ path: 'test-results/interaction-live.png', fullPage: false });
  console.log(`${passed} interaction assertions passed (isolated local fixtures).`);
} finally {
  await browser.close();
  server.close();
}
