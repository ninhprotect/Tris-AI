/**
 * Tris Companion (AIRI-style avatar page): the 2D SVG mascot renders by
 * default (blink keeps the eyes in place, emotions drive the face), chat
 * streams from the real NDJSON contract with a "Working..." indicator, TTS is
 * streamed per sentence while the answer is still arriving (/v1/speech, no
 * emoji in the spoken text), mic input fills the composer
 * (/v1/workspace/transcribe), the svg <-> 3D mode toggle works, old Live2D
 * settings migrate, and the weak-machine FPS limiter reacts.
 * All backend endpoints are fixtures.
 */
import { chromium } from 'playwright';
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';

const root = path.resolve(import.meta.dirname, '..');
const dist = path.join(root, 'dist');
const mime = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml' };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Minimal 16-bit mono PCM WAV (0.1 s, 8 kHz) — decodable by decodeAudioData.
function wavBytes() {
  const sampleRate = 8000, samples = 800;
  const dataSize = samples * 2;
  const buf = Buffer.alloc(44 + dataSize);
  buf.write('RIFF', 0); buf.writeUInt32LE(36 + dataSize, 4); buf.write('WAVE', 8);
  buf.write('fmt ', 12); buf.writeUInt32LE(16, 16); buf.writeUInt16LE(1, 20);
  buf.writeUInt16LE(1, 22); buf.writeUInt32LE(sampleRate, 24); buf.writeUInt32LE(sampleRate * 2, 28);
  buf.writeUInt16LE(2, 32); buf.writeUInt16LE(16, 34);
  buf.write('data', 36); buf.writeUInt32LE(dataSize, 40);
  for (let i = 0; i < samples; i++) buf.writeInt16LE(Math.round(Math.sin(i / 6) * 12000), 44 + i * 2);
  return buf;
}
const WAV = wavBytes();

// Voice turn: a slow stream (one word every 50 ms) full of emoji and with a
// quoted English sample, so per-sentence TTS must start before {done}.
const SLOW_PROMPT = 'Một câu nữa nhé';
const SLOW_ANSWER =
  'Tuyệt vời lắm! 😄 Hôm nay mình luyện câu "How are you today?" nhé ✨\n' +
  'Bạn đọc to câu đó vài lần, mình sẽ nghe và sửa từng âm giúp bạn. 🎉 ' +
  'Nhớ lên giọng ở cuối câu hỏi nha, như vậy nghe tự nhiên hơn nhiều đó! 💪❤️';
const SLOW_TAIL = 'tự nhiên hơn nhiều đó!';

let transcribeCalls = 0, chatBodies = [];
const speechLog = []; // { at, body } — `at` is when the request reached the server
let slowDoneAt = null; // when the slow stream sent its {done} event

const readBody = (req) =>
  new Promise((resolve) => {
    let raw = '';
    req.setEncoding('utf8');
    req.on('data', (c) => (raw += c));
    req.on('end', () => resolve(raw));
  });

const server = http.createServer((req, res) => {
  const url = new URL(req.url, 'http://127.0.0.1');
  if (url.pathname === '/health')
    return res.writeHead(200, { 'Content-Type': 'application/json' }).end(
      JSON.stringify({ status: 'ok', auth_required: true }),
    );
  if (url.pathname === '/v1/workspace/presence') { req.resume(); return res.writeHead(200).end('{}'); }
  if (url.pathname === '/v1/workspace/models')
    return res.writeHead(200, { 'Content-Type': 'application/json' }).end(
      JSON.stringify({ default: 'english-tutor-local:4b', models: [{ name: 'english-tutor-local:4b' }] }),
    );
  if (url.pathname === '/v1/workspace/session')
    return res.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify({ chats: [], settings: { language: 'vi' } }));
  if (url.pathname === '/v1/workspace/chat') {
    void readBody(req).then(async (raw) => {
      const body = JSON.parse(raw || '{}');
      chatBodies.push(body);
      res.writeHead(200, { 'Content-Type': 'application/x-ndjson' });
      const send = (e) => res.write(JSON.stringify(e) + '\n');
      send({ status: 'Đang trả lời' });
      if (body.message === SLOW_PROMPT) {
        await sleep(300);
        for (const piece of SLOW_ANSWER.match(/\S+\s*/g)) {
          send({ delta: piece });
          await sleep(50);
        }
        slowDoneAt = performance.now();
        send({ done: true, seconds: 2, sources: [] });
        return res.end();
      }
      await sleep(120);
      send({ delta: 'Chào bạn! Mình ' });
      await sleep(100);
      send({ delta: 'là Tris, chạy local nhé.' });
      send({ done: true, seconds: 1, sources: [] });
      res.end();
    });
    return;
  }
  if (url.pathname === '/v1/speech') {
    const at = performance.now();
    void readBody(req).then((raw) => {
      speechLog.push({ at, body: JSON.parse(raw || '{}') });
      res.writeHead(200, { 'Content-Type': 'audio/wav' }).end(WAV);
    });
    return;
  }
  if (url.pathname === '/v1/workspace/transcribe') {
    transcribeCalls++;
    req.resume();
    return res.writeHead(200, { 'Content-Type': 'application/json' }).end(
      JSON.stringify({ text: 'xin chào Tris', language: 'vi', audio_seconds: 1, processing_seconds: 0.2, model: 'small', device: 'cpu' }),
    );
  }
  let file = path.join(dist, decodeURIComponent(url.pathname));
  if (url.pathname === '/' || url.pathname.endsWith('/')) file = path.join(file, 'index.html');
  fs.readFile(file)
    .then((d) => res.writeHead(200, { 'Content-Type': mime[path.extname(file)] || 'application/octet-stream' }).end(d))
    .catch(() => res.writeHead(404).end());
});
await new Promise((r) => server.listen(0, '127.0.0.1', r));
const base = `http://127.0.0.1:${server.address().port}`;

const browser = await chromium.launch({
  executablePath: process.env.TRIS_BROWSER || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  headless: true,
  args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream', '--autoplay-policy=no-user-gesture-required'],
});
const context = await browser.newContext({ viewport: { width: 1280, height: 860 }, permissions: ['microphone'] });
const page = await context.newPage();
const errors = [];
page.on('pageerror', (e) => errors.push(e.message));

let passed = 0;
const ok = (label, v = true) => { assert.ok(v, label); passed++; console.log('PASS ' + label); };
const settingsIn = () => page.evaluate(() => JSON.parse(localStorage.getItem('tris.companion.settings') || '{}'));

try {
  // Real flow: opened from the main app with #t=<token>; the page stores it
  // for later direct visits and strips the hash.
  await page.goto(base + '/companion/#t=companion-fixture');
  ok(
    'Token from #t persisted for direct visits',
    await page.evaluate(() => localStorage.getItem('tris.companion.token')?.includes('companion-fixture')),
  );
  // Boot finishes with setMode(), which is the first write of the settings.
  await page.waitForFunction(() => localStorage.getItem('tris.companion.settings')?.includes('"liveMode":"svg"'));

  // Old builds stored the (removed) Live2D cats mode: it must come back as the SVG mascot.
  await page.evaluate(() =>
    localStorage.setItem('tris.companion.settings', JSON.stringify({ fps: 30, autoSpeak: false, liveMode: 'live2d', live2d: { scale: 1 } })),
  );
  await page.reload();
  await page.waitForFunction(() => JSON.parse(localStorage.getItem('tris.companion.settings') || '{}').liveMode === 'svg');
  const migrated = await settingsIn();
  ok(
    'Old {liveMode:"live2d"} setting migrates to svg mode',
    migrated.liveMode === 'svg' && !('live2d' in migrated) && (await page.locator('#mode-label').innerText()) === 'Linh vật 2D',
  );

  // The SVG mascot is the default character.
  ok('SVG mascot is visible by default', await page.locator('#actor #avatar').isVisible());
  ok('3D canvas hidden in svg mode', await page.evaluate(() => document.querySelector('#vrm3d').classList.contains('hidden')));

  // Blink: eye height shrinks but the eye centre stays at y=87 (old bug: eyes "fell" while blinking).
  const blink = await page.evaluate(async () => {
    const eye = document.querySelector('#eye-l-white');
    const samples = [];
    const t0 = performance.now();
    let dipAt = 0;
    while (performance.now() - t0 < 7000) {
      window.__companion.step(16);
      const y = parseFloat(eye.getAttribute('y')), h = parseFloat(eye.getAttribute('height'));
      samples.push({ h, c: y + h / 2 });
      if (!dipAt && h < 15) dipAt = performance.now();
      if (dipAt && performance.now() - dipAt > 250) break;
      await new Promise((r) => setTimeout(r, 16));
    }
    const hs = samples.map((s) => s.h);
    return {
      frames: samples.length,
      minH: Math.min(...hs),
      maxH: Math.max(...hs),
      drift: Math.max(...samples.map((s) => Math.abs(s.c - 87))),
    };
  });
  ok(`Mascot blinks (eye height ${blink.maxH} -> ${blink.minH} over ${blink.frames} frames)`, blink.maxH >= 25 && blink.minH < 15);
  ok(`Blink keeps the eye centre fixed at y=87 (max drift ${blink.drift.toFixed(2)})`, blink.drift <= 0.2);

  // Emotion -> face: angry brows come in.
  const angry = await page.evaluate(() => {
    window.__companion.setEmotion('angry');
    for (let i = 0; i < 8; i++) window.__companion.step(33);
    return { expression: window.__companion.expression, brow: parseFloat(document.querySelector('#brow-l').getAttribute('opacity')) };
  });
  ok('setEmotion("angry") switches the expression to angry', angry.expression === 'angry');
  ok(`Angry brows are visible (#brow-l opacity ${angry.brow})`, angry.brow > 0.5);

  // Chat streams into the bubble.
  await page.locator('#input').fill('Chào Tris!');
  await page.locator('#send-btn').click();
  await page.waitForFunction(() => document.querySelector('.messages')?.innerText.includes('là Tris, chạy local nhé.'));
  ok('Chat streams from the NDJSON contract');
  await page.locator('#working').waitFor({ state: 'hidden', timeout: 3000 });
  ok('Working... indicator hidden once the reply is done');
  ok(
    'Backend status text is not echoed (Working... replaces it)',
    await page.evaluate(() => !document.body.innerText.includes('Đang trả lời')),
  );

  // Emotion engine (ported from airi constants/emotions.ts).
  const emotions = await page.evaluate(() => ({
    happy: window.__companion.detectEmotion('Tuyệt vời lắm! 😄'),
    sad: window.__companion.detectEmotion('Buồn quá 😢'),
    angry: window.__companion.detectEmotion('⚠ Cẩn thận lỗi này nhé'),
    neutral: window.__companion.detectEmotion('Câu này bình thường thôi.'),
  }));
  ok(
    'Emotion detection maps text like airi does',
    emotions.happy === 'happy' && emotions.sad === 'sad' && emotions.angry === 'angry' && emotions.neutral === 'neutral',
  );

  // Enable voice, send again: speech is synthesized sentence by sentence
  // while the (slow) answer is still streaming in.
  await page.locator('#voice-toggle').click();
  ok('Voice toggle reflects state', await page.locator('#voice-toggle').getAttribute('aria-pressed') === 'true');
  await page.locator('#input').fill(SLOW_PROMPT);
  await page.locator('#send-btn').click();
  await page.locator('#working').waitFor({ state: 'visible', timeout: 2000 });
  ok(
    'Working... indicator shows while the chat request is pending',
    slowDoneAt === null && (await page.locator('#working').innerText()) === 'Working...',
  );
  await page.waitForFunction((tail) => document.querySelector('.messages')?.innerText.includes(tail), SLOW_TAIL, { timeout: 15000 });
  await page.locator('#working').waitFor({ state: 'hidden', timeout: 15000 });
  ok('Working... indicator hidden after the voiced reply completes');
  ok('Second turn sends the earlier exchange as history', chatBodies[1]?.history?.length === 2);
  ok('TTS endpoint called when auto-speak is on', speechLog.length >= 1);
  ok(
    `First /v1/speech request arrives before the stream's done event (${Math.round(slowDoneAt - (speechLog[0]?.at ?? Infinity))} ms earlier)`,
    slowDoneAt !== null && speechLog.length > 0 && speechLog[0].at < slowDoneAt,
  );
  ok(`Speech is requested per sentence (${speechLog.length} requests)`, speechLog.length >= 3);
  const spoken = speechLog.map((s) => String(s.body.text || ''));
  ok(
    'No emoji in any text sent to /v1/speech',
    spoken.every((t) => t.trim() && !/\p{Extended_Pictographic}/u.test(t)),
  );
  ok(
    'Quoted English sample is voiced with the English voice',
    speechLog.some((s) => s.body.language === 'en' && String(s.body.text).includes('How are you today')),
  );

  // Mouth animates while audio plays (path differs from the closed shape).
  const mouthDuring = await page.locator('#mouth').getAttribute('d');
  ok('Mouth path is driven during playback', typeof mouthDuring === 'string' && mouthDuring.length > 10);

  // FPS limiter reacts (the SVG rAF loop and the 3D loop share the setting).
  await page.locator('#settings-toggle').click();
  await page.locator('#fps-select').selectOption('8');
  ok('FPS cap selector updates note', (await page.locator('#fps-note').innerText()).includes('8'));
  ok('FPS choice persisted', await page.evaluate(() => localStorage.getItem('tris.companion.settings')?.includes('"fps":8')));

  // Mode toggle cycles two modes: SVG mascot -> 3D model -> SVG mascot.
  await page.keyboard.press('Escape');
  ok('Mode label starts on the 2D mascot', (await page.locator('#mode-label').innerText()) === 'Linh vật 2D');
  await page.locator('#mode-toggle').click();
  ok('Cycle reaches 3D model mode', (await page.locator('#mode-label').innerText()) === 'Model 3D');
  ok(
    'Mascot hidden and 3D canvas shown in 3D mode',
    await page.evaluate(() =>
      document.querySelector('#actor').classList.contains('hidden') && !document.querySelector('#vrm3d').classList.contains('hidden')),
  );
  await page.waitForFunction(() =>
    document.querySelector('#status')?.innerText.includes('Chưa có model 3D'),
  );
  ok('Empty 3D mode asks for a .vrm file honestly');
  ok('Mode persisted', await page.evaluate(() => localStorage.getItem('tris.companion.settings')?.includes('"liveMode":"vrm"')));

  await page.locator('#mode-toggle').click();
  await page.waitForFunction(() => !document.querySelector('#actor').classList.contains('hidden'));
  ok('Cycle back to the 2D SVG mascot', (await page.locator('#mode-label').innerText()) === 'Linh vật 2D');
  ok('Mascot visible again and 3D canvas hidden', (await page.locator('#avatar').isVisible())
    && await page.evaluate(() => document.querySelector('#vrm3d').classList.contains('hidden')));
  ok('SVG mode persisted', (await settingsIn()).liveMode === 'svg');

  // Mic: fake device records; second click stops and transcribes.
  await page.keyboard.press('Escape');
  await page.locator('#mic-btn').click();
  await sleep(900);
  await page.locator('#mic-btn').click();
  await page.waitForFunction(() => document.querySelector('#input')?.value.includes('xin chào Tris'), null, { timeout: 15000 });
  ok('Mic transcription fills the composer', transcribeCalls >= 1);

  // Dropping a garbage .vrm lands a friendly error, never a crash.
  await page.evaluate(() => {
    const dt = new DataTransfer();
    const fake = new Uint8Array(64);
    fake.set([0x67, 0x4c, 0x54, 0x46, 2, 0, 0, 0, 64, 0, 0, 0]); // "glTF" magic, broken chunks
    dt.items.add(new File([fake], 'not-a-model.vrm'));
    document.querySelector('#stage').dispatchEvent(new DragEvent('drop', { dataTransfer: dt, bubbles: true }));
  });
  await page.waitForFunction(
    () => document.querySelector('.messages')?.innerText.includes('Không đọc được tệp model này.'),
    null,
    { timeout: 30000 },
  );
  ok('Broken .vrm drop fails with a friendly message');
  ok('Mode stayed on 3D after the drop', await page.evaluate(() =>
    JSON.parse(localStorage.getItem('tris.companion.settings')).liveMode === 'vrm'));

  ok('No JavaScript errors' + (errors.length ? ': ' + errors.join(' | ') : ''), errors.length === 0);
  await page.screenshot({ path: 'test-results/companion.png' });
  console.log(`${passed} companion assertions passed.`);
} finally {
  await browser.close();
  server.close();
}
