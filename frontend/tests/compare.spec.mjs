/**
 * Model cross-check ("Đối chiếu hai model"): the same question streams to two
 * models in sequence, then a judge pass reports agreement/contradictions
 * without inventing a verdict. Fixture server streams NDJSON exactly like the
 * real /v1/workspace/compare route.
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
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const bodies = [];

function serveCompare(res, body) {
  res.writeHead(200, { 'Content-Type': 'application/x-ndjson', 'Cache-Control': 'no-store' });
  const send = (event) => res.write(JSON.stringify(event) + '\n');
  bodies.push(body);
  void (async () => {
    send({ status: 'Mình sẽ hỏi cùng một câu cho test:4b và test:8b, rồi đối chiếu hai câu trả lời.' });
    await sleep(250);
    send({ which: 'a', delta: 'Mèo ' });
    await sleep(200);
    send({ which: 'a', delta: 'là động vật có vú.' });
    send({ which: 'a', done: true });
    send({ status: 'Đang nạp test:8b — máy chỉ giữ được một model trong VRAM nên test:4b được giải phóng.' });
    await sleep(300);
    send({ which: 'b', delta: 'Con mèo thuộc ' });
    await sleep(200);
    send({ which: 'b', delta: 'họ Felidae.' });
    send({ which: 'b', done: true });
    send({ status: 'Đang đối chiếu hai câu trả lời…' });
    await sleep(250);
    send({ judge: 'Cả hai cùng xác nhận mèo là động vật. ' });
    await sleep(150);
    send({ judge: 'Bên B nêu thêm họ Felidae — cần kiểm chứng thêm.' });
    send({ done: true, seconds: 4, model_a: 'test:4b', model_b: 'test:8b' });
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
        models: [
          { name: 'english-tutor-local:4b', size: 2500000000 },
          { name: 'english-tutor-local:8b', size: 5200000000 },
          { name: 'qwen3:4b', size: 2500000000 },
        ],
      }),
    );
  if (url.pathname === '/v1/workspace/session')
    return res.writeHead(200, { 'Content-Type': 'application/json' }).end(
      JSON.stringify({ chats: [], settings: { language: 'vi' } }),
    );
  if (url.pathname === '/v1/workspace/compare') {
    let raw = '';
    req.on('data', (chunk) => (raw += chunk));
    req.on('end', () => serveCompare(res, JSON.parse(raw || '{}')));
    return;
  }
  const file = path.join(dist, url.pathname === '/' ? 'index.html' : decodeURIComponent(url.pathname));
  fs.readFile(file)
    .then((data) =>
      res.writeHead(200, { 'Content-Type': mime[path.extname(file)] || 'application/octet-stream' }).end(data),
    )
    .catch(() => res.writeHead(404).end('not found'));
});
await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
const base = `http://127.0.0.1:${server.address().port}`;

const browser = await chromium.launch({
  executablePath:
    process.env.TRIS_BROWSER || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
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
      token: 'compare-fixture',
      account: { account_id: 'compare-ui', username: 'QA', learner_name: 'QA' },
    }),
  ),
);

let passed = 0;
const ok = (label, value = true) => {
  assert.ok(value, label);
  passed++;
  console.log('PASS ' + label);
};

try {
  await page.goto(base);
  await page.locator('.composer-card textarea').waitFor();

  // Turn on cross-check in the model popover and pick the comparison model.
  await page.locator('.model-button').click();
  await page.getByRole('button', { name: 'Đối chiếu hai model', exact: true }).click();
  await page.getByLabel('Model đối chiếu').selectOption('english-tutor-local:8b');
  ok('Comparison model selectable');
  await page.keyboard.press('Escape');

  await page.locator('.composer-card textarea').fill('Con mèo là gì?');
  await page.getByRole('button', { name: 'Gửi tin nhắn', exact: true }).click();

  // Both model columns stream side by side.
  await page.locator('[data-testid="compare-block"]').waitFor();
  await page.waitForFunction(() =>
    document.querySelector('[data-testid="compare-block"]')?.innerText.includes('Mèo'),
  );
  ok('Both model answers stream into the compare block');
  const columns = await page.locator('.compare-col').count();
  ok('Two columns rendered', columns === 2);

  // Honest VRAM status is shown while switching models.
  await page.waitForFunction(() =>
    document.querySelector('.chat-scroll')?.innerText.includes('VRAM'),
  );
  ok('Model-switch status is truthful about VRAM');

  // Judge verdict streams (live block or the final markdown, whichever wins
  // the race — the fixture streams fast enough to finish between polls).
  await page.waitForFunction(() =>
    document.querySelector('.chat-scroll')?.innerText.includes('cần kiểm chứng thêm'),
  );
  ok('Judge verdict streams with the no-fabrication wording');

  // Done: persisted as markdown content, compare block replaced.
  await page.waitForFunction(() =>
    document.querySelector('.chat-scroll')?.innerText.includes('Kết luận đối chiếu'),
  );
  await page.waitForFunction(() => document.querySelector('[data-testid="compare-block"]') === null);
  ok('Finished compare persists as markdown content');
  ok(
    'Compare request carried both models',
    bodies[0]?.model_a === 'english-tutor-local:4b' && bodies[0]?.model_b === 'english-tutor-local:8b',
  );

  // Reload: markdown survives without any live-only state.
  await page.reload();
  await page.locator('.composer-card textarea').waitFor();
  await page.waitForFunction(() =>
    document.querySelector('.chat-scroll')?.innerText.includes('Kết luận đối chiếu'),
  );
  ok('Cross-check result survives reload');

  ok('No JavaScript errors', errors.length === 0);
  await page.screenshot({ path: 'test-results/compare-result.png' });
  console.log(`${passed} compare assertions passed (isolated local fixtures).`);
} finally {
  await browser.close();
  server.close();
}
