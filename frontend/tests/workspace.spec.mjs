import { chromium } from 'playwright';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';

// Standalone test runner; uses an installed browser, never downloads Chromium.
const base = process.env.TRIS_TEST_URL || 'http://127.0.0.1:7860';
const browser = await chromium.launch({
  executablePath:
    process.env.TRIS_BROWSER || 'C:/Program Files/Google/Chrome/Application/chrome.exe',
  headless: true,
});
const context = await browser.newContext({
  viewport: { width: 1440, height: 900 },
  reducedMotion: 'reduce',
});
const page = await context.newPage();
const errors = [];
page.on('pageerror', (e) => errors.push(e.message));
const out = path.resolve('test-results');
await fs.mkdir(out, { recursive: true });
let passed = 0;
function ok(label, condition = true) {
  assert.ok(condition, label);
  passed++;
  console.log(`PASS ${label}`);
}
async function visibleBox(selector) {
  const box = await page.locator(selector).boundingBox();
  assert.ok(box, `${selector} is visible`);
  return box;
}
try {
  await page.goto(base);
  await page.locator('textarea').waitFor();
  await page.evaluate(() => document.fonts.ready);
  ok(
    'Empty send is disabled',
    await page.getByRole('button', { name: 'Gửi tin nhắn', exact: true }).isDisabled(),
  );
  await page.screenshot({ path: path.join(out, 'desktop-empty.png') });
  await page.getByRole('button', { name: 'Mở menu tài khoản', exact: true }).click();
  const account = await visibleBox('.account-button');
  const menu = await visibleBox('.account-popover');
  ok('Account popover opens above footer', menu.y + menu.height <= account.y + 1);
  await page.screenshot({ path: path.join(out, 'desktop-account.png') });
  await page.keyboard.press('Escape');
  ok('Escape closes account popover', (await page.locator('.account-popover').count()) === 0);
  ok(
    'Escape restores trigger focus',
    await page.locator('.account-button').evaluate((el) => el === document.activeElement),
  );
  await page.locator('textarea').fill('Bản nháp vẫn còn khi đổi thiết bị.');
  for (const label of ['Mobile', 'Tablet', 'Laptop', 'Desktop']) {
    await page.getByRole('button', { name: 'Hiển thị thiết bị', exact: true }).click();
    await page.getByRole('button', { name: new RegExp(`^${label}`) }).click();
    ok(
      `${label} preserves draft`,
      (await page.locator('textarea').inputValue()) === 'Bản nháp vẫn còn khi đổi thiết bị.',
    );
    if (label === 'Mobile')
      ok(
        'Internal preview uses actual responsive layout',
        (await page.locator('.app-frame').getAttribute('data-layout')) === 'mobile',
      );
  }
  await page.getByRole('button', { name: 'Hiển thị thiết bị', exact: true }).click();
  await page.getByRole('button', { name: 'Tự động / Đặt lại' }).click();
  for (const width of [320, 375, 390, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: width < 768 ? 844 : 900 });
    await page.waitForTimeout(100);
    const geometry = await page.evaluate(() => ({
      width: innerWidth,
      bodyWidth: document.body.scrollWidth,
      rootHeight: document.documentElement.scrollHeight,
      height: innerHeight,
    }));
    const composer = await visibleBox('[data-testid="composer"]');
    const send = await visibleBox('.send-button');
    ok(
      `${width}px no body overflow`,
      geometry.bodyWidth <= width && geometry.rootHeight <= geometry.height,
    );
    ok(
      `${width}px composer contained`,
      composer.x >= 0 &&
        composer.x + composer.width <= width + 1 &&
        composer.y + composer.height <= geometry.height + 1,
    );
    ok(
      `${width}px send visible and 44px target`,
      send.x >= 0 && send.x + send.width <= width && send.width >= 44 && send.height >= 44,
    );
    for (const [trigger, popup] of [
      ['.model-button', '.model-popover'],
      ['.mode-button', '.mode-popover'],
      ['.context-button', '.project-popover'],
      ['.attachment-anchor > button', '.attachment-popover'],
    ]) {
      await page.locator(trigger).click();
      const bounds = await visibleBox(popup);
      ok(
        `${width}px ${popup} stays on screen`,
        bounds.x >= 0 && bounds.x + bounds.width <= width && bounds.y >= 0,
      );
      await page.keyboard.press('Escape');
    }
    if (width < 768) {
      await page.getByRole('button', { name: 'Mở thanh bên', exact: true }).click();
      ok(`${width}px mobile drawer`, await page.locator('.sidebar.drawer-open').isVisible());
      await page.getByRole('button', { name: 'Mở menu tài khoản' }).click();
      const bounds = await visibleBox('.account-popover');
      ok(
        `${width}px account menu stays on screen`,
        bounds.x >= 0 && bounds.x + bounds.width <= width && bounds.y >= 0,
      );
      await page.locator('.account-button').click();
      await page.locator('.drawer-close').click();
    }
    if (width === 390 || width === 768)
      await page.screenshot({ path: path.join(out, `viewport-${width}.png`) });
  }
  await page.getByRole('button', { name: 'Thu gọn thanh bên' }).click();
  ok(
    'Collapsing sidebar preserves draft',
    (await page.locator('textarea').inputValue()) === 'Bản nháp vẫn còn khi đổi thiết bị.',
  );
  await page.getByRole('button', { name: 'Mở rộng thanh bên' }).click();
  await page.locator('.mode-button').click();
  await page.getByRole('button', { name: 'Ngữ pháp', exact: true }).click();
  ok(
    'Changing learning mode never submits a draft',
    (await page.locator('textarea').inputValue()) === 'Bản nháp vẫn còn khi đổi thiết bị.',
  );
  await page.locator('.model-button').click();
  await page.keyboard.press('Escape');
  ok(
    'Opening model menu never submits a draft',
    (await page.locator('textarea').inputValue()) === 'Bản nháp vẫn còn khi đổi thiết bị.',
  );
  await page.locator('.context-button').click();
  await page.locator('.project-popover').getByRole('button', { name: 'Tủ sách của tôi' }).click();
  ok(
    'Choosing project works',
    (await page.locator('.context-button').innerText()).includes('Tủ sách'),
  );
  await page.getByRole('button', { name: 'Không gian Tris AI', exact: true }).click();
  await page.getByRole('button', { name: /Trải nghiệm mẫu/ }).click();
  await page.locator('.history-item').first().click();
  const footerBefore = await visibleBox('.account-button');
  const composerBefore = await visibleBox('[data-testid="composer"]');
  await page.locator('.sidebar-scroll').evaluate((el) => (el.scrollTop = el.scrollHeight));
  await page.locator('.chat-scroll').evaluate((el) => {
    el.scrollTop = 0;
    el.dispatchEvent(new Event('scroll'));
  });
  ok(
    'Sidebar history can scroll independently',
    await page
      .locator('.sidebar-scroll')
      .evaluate((el) => el.scrollHeight > el.clientHeight && el.scrollTop > 0),
  );
  ok(
    'Account pinned while sidebar scrolls',
    (await visibleBox('.account-button')).y === footerBefore.y,
  );
  ok(
    'Composer pinned while chat scrolls',
    (await visibleBox('[data-testid="composer"]')).y === composerBefore.y,
  );
  await page.getByRole('button', { name: 'Về tin nhắn mới nhất' }).waitFor();
  await page.locator('textarea').fill('Hãy giúp mình luyện tập.');
  await page.keyboard.press('Enter');
  await page.getByRole('button', { name: 'Dừng trả lời' }).waitFor();
  await page.waitForTimeout(150);
  ok(
    'Streaming does not steal history scroll position',
    await page.locator('.chat-scroll').evaluate((el) => el.scrollTop < 5),
  );
  await page.getByRole('button', { name: 'Dừng trả lời' }).click();
  await page.getByRole('button', { name: 'Gửi tin nhắn', exact: true }).waitFor();
  await page.getByRole('button', { name: 'Về tin nhắn mới nhất' }).click();
  await page.waitForFunction(() => {
    const el = document.querySelector('.chat-scroll');
    return el.scrollHeight - el.scrollTop - el.clientHeight < 90;
  });
  ok(
    'Jump to latest works',
    await page
      .locator('.chat-scroll')
      .evaluate((el) => el.scrollHeight - el.scrollTop - el.clientHeight < 90),
  );
  await page.screenshot({ path: path.join(out, 'desktop-conversation.png') });
  await page.getByRole('button', { name: 'Đoạn chat mới', exact: true }).click();
  await page.locator('textarea').fill('Dòng một');
  await page.keyboard.press('Shift+Enter');
  await page.keyboard.type('Line two');
  ok('Shift+Enter adds newline', (await page.locator('textarea').inputValue()).includes('\n'));
  await page.locator('input[type=file]').setInputFiles({
    name: 'lesson.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from('This is a local attachment preview test.'),
  });
  ok(
    'Attachment preview',
    await page
      .locator('.composer-files')
      .innerText()
      .then((t) => t.includes('lesson.txt')),
  );
  await page.getByRole('button', { name: 'Bỏ tệp lesson.txt' }).click();
  await page.locator('input[type=file]').setInputFiles({
    name: 'invalid.exe',
    mimeType: 'application/octet-stream',
    buffer: Buffer.from('not executable'),
  });
  ok('Unsupported file rejected', (await page.locator('.composer-files').count()) === 0);
  await page.keyboard.press('Control+,');
  await page.locator('#lang-select').selectOption('en');
  ok('English updates system UI', (await page.locator('html').getAttribute('lang')) === 'en');
  await page.locator('#theme-select').selectOption('light');
  ok('Theme actually changes', (await page.locator('html').getAttribute('data-theme')) === 'light');
  await page.screenshot({ path: path.join(out, 'settings-light.png') });
  await page.locator('#theme-select').selectOption('dark');
  await page.locator('#lang-select').selectOption('vi');
  await page.keyboard.press('Escape');
  await page.reload();
  await page.locator('textarea').waitFor();
  ok('Draft survives reload', (await page.locator('textarea').inputValue()).includes('Dòng một'));
  ok('No browser JavaScript errors', errors.length === 0);
  console.log(`\n${passed} assertions passed. Screenshots: ${out}`);
} finally {
  await browser.close();
}
