import { chromium } from 'playwright';
import assert from 'node:assert/strict';

const base = process.env.TRIS_TEST_URL || 'http://127.0.0.1:7860';
const browser = await chromium.launch({
  executablePath:
    process.env.TRIS_BROWSER || 'C:/Program Files/Google/Chrome/Application/chrome.exe',
  headless: true,
});
const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
const page = await context.newPage();
const errors = [];
page.on('pageerror', (error) => errors.push(error.message));

await page.addInitScript(() => {
  sessionStorage.setItem(
    'tris.workspace.session',
    JSON.stringify({
      token: 'microphone-browser-fixture',
      account: { account_id: 'mic-ui', username: 'QA', learner_name: 'QA' },
    }),
  );
  window.__micMode = 'ready';
  window.__stoppedTracks = 0;
  const track = {
    kind: 'audio',
    label: 'Fixture microphone',
    stop() {
      window.__stoppedTracks += 1;
    },
  };
  const stream = {
    getTracks: () => [track],
    getAudioTracks: () => [track],
  };
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: {
      async getUserMedia() {
        if (window.__micMode === 'denied')
          throw new DOMException('Permission denied', 'NotAllowedError');
        if (window.__micMode === 'missing') throw new DOMException('No device', 'NotFoundError');
        return stream;
      },
    },
  });
  class FixtureRecorder {
    static isTypeSupported(type) {
      return type.startsWith('audio/webm');
    }
    constructor(input, options = {}) {
      this.stream = input;
      this.mimeType = options.mimeType || 'audio/webm';
      this.state = 'inactive';
      this.ondataavailable = null;
      this.onerror = null;
      this.onstop = null;
    }
    start() {
      this.state = 'recording';
    }
    stop() {
      if (this.state === 'inactive') return;
      this.state = 'inactive';
      const data = new Blob([new Uint8Array(512).fill(1)], { type: this.mimeType });
      this.ondataavailable?.({ data });
      queueMicrotask(() => this.onstop?.());
    }
  }
  Object.defineProperty(window, 'MediaRecorder', { configurable: true, value: FixtureRecorder });
  class FixtureAudioContext {
    createAnalyser() {
      return {
        fftSize: 256,
        smoothingTimeConstant: 0,
        getByteTimeDomainData(values) {
          values.fill(128);
          for (let i = 0; i < values.length; i += 8) values[i] = 160;
        },
      };
    }
    createMediaStreamSource() {
      return { connect() {} };
    }
    close() {
      return Promise.resolve();
    }
  }
  Object.defineProperty(window, 'AudioContext', {
    configurable: true,
    value: FixtureAudioContext,
  });
});

let transcriptionAuth = '';
let transcriptionBody = '';
await page.route('**/health', (route) =>
  route.fulfill({ json: { status: 'ok', auth_required: true } }),
);
await page.route('**/v1/**', async (route) => {
  const path = new URL(route.request().url()).pathname;
  if (path === '/v1/workspace/presence') return route.continue();
  if (path === '/v1/workspace/models')
    return route.fulfill({
      json: {
        default: 'english-tutor-local:4b',
        models: [{ name: 'english-tutor-local:4b' }],
      },
    });
  if (path === '/v1/workspace/session')
    return route.fulfill({ json: { chats: [], settings: { language: 'vi' } } });
  if (path === '/v1/workspace/transcribe') {
    transcriptionAuth = route.request().headers().authorization || '';
    transcriptionBody = route.request().postData() || '';
    await new Promise((resolve) => setTimeout(resolve, 120));
    return route.fulfill({
      json: {
        text: 'Hello from local speech',
        language: 'en',
        audio_seconds: 1.2,
        processing_seconds: 0.3,
        model: 'base',
        device: 'cpu',
      },
    });
  }
  return route.fulfill({ json: {} });
});

let passed = 0;
const ok = (label, value = true) => {
  assert.ok(value, label);
  passed += 1;
  console.log('PASS ' + label);
};

try {
  await page.goto(base);
  const textarea = page.getByRole('textbox', { name: 'Nhắn tin cho Tris' });
  await textarea.fill('Bản nháp');
  await page.getByRole('button', { name: 'Nhập bằng giọng nói' }).click();
  await page.getByRole('button', { name: 'Dừng ghi âm' }).waitFor();
  ok('Recording state is visible', await page.getByText(/Đang nghe/).isVisible());
  ok('Selected microphone is visible', await page.getByText('Fixture microphone').isVisible());
  ok('Live signal meter detects fixture audio', await page.locator('.voice-meter').isVisible());

  await page.waitForTimeout(100);
  await page.getByRole('button', { name: 'Dừng ghi âm' }).click();
  ok(
    'Transcribing state is visible',
    await page.getByText(/Đang chuyển thành văn bản local/).isVisible(),
  );
  await page.waitForFunction(() =>
    document.querySelector('textarea')?.value.includes('Hello from local speech'),
  );
  ok(
    'Transcript appends without overwriting draft',
    (await textarea.inputValue()) === 'Bản nháp Hello from local speech',
  );
  ok('Microphone track is stopped', (await page.evaluate(() => window.__stoppedTracks)) === 1);
  ok(
    'Transcription uses account authorization',
    transcriptionAuth === 'Bearer microphone-browser-fixture',
  );
  ok(
    'Multipart request carries language and audio file',
    transcriptionBody.includes('name="language"') && transcriptionBody.includes('tris-microphone-'),
  );

  await page.evaluate(() => (window.__micMode = 'denied'));
  await page.getByRole('button', { name: 'Nhập bằng giọng nói' }).click();
  await page.locator('.toast').waitFor();
  ok(
    'Permission denial has a specific recovery message',
    (await page.locator('.toast').innerText()).includes('Quyền micro đang bị chặn'),
  );
  ok('No browser JavaScript errors', errors.length === 0);
  console.log(`${passed} microphone UI assertions passed.`);
} finally {
  await browser.close();
}
