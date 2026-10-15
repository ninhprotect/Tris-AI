import { chromium } from 'playwright';
import assert from 'node:assert/strict';

const health = await (await fetch('http://127.0.0.1:7861/health')).json();
assert.equal(health.device, 'cuda:0');
const browser = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
await page.addInitScript(() => sessionStorage.setItem('tris.workspace.session', JSON.stringify({token:'voice-ui-fixture',account:{account_id:'voice-ui',username:'QA',learner_name:'QA'}})));
await page.route('**/v1/**', async route => {
  const path = new URL(route.request().url()).pathname;
  if (path === '/v1/workspace/presence') return route.continue();
  if (path === '/v1/workspace/voice-status') return route.fulfill({json:health});
  if (path === '/v1/workspace/session') return route.fulfill({json:{chats:[],settings:{language:'vi'}}});
  if (path === '/v1/workspace/models') return route.fulfill({json:{default:'english-tutor-local:4b',models:[{name:'english-tutor-local:4b'}]}});
  return route.fulfill({json:{}});
});
try {
  await page.goto('http://127.0.0.1:7860');
  await page.getByRole('button',{name:'Mở menu tài khoản',exact:true}).click();
  await page.getByRole('button',{name:/Cài đặt/}).click();
  await page.getByRole('button',{name:'Giọng Tris',exact:true}).click();
  await page.getByText('NVIDIA GeForce GTX 1060',{exact:true}).waitFor();
  assert.ok((await page.locator('.settings-content').innerText()).includes('Sẵn sàng'));
  assert.ok((await page.locator('.settings-content').innerText()).includes('Không tự phát'));
  await page.screenshot({path:'test-results/voice-gpu-settings.png'});
  await page.keyboard.press('Escape');
  await page.getByRole('button',{name:'Công cụ',exact:true}).click();
  const text = await page.locator('.modal').innerText();
  assert.ok(text.includes('Nguyễn Hải Hà Ninh'));
  assert.ok(!text.includes('Alibaba'));
  assert.ok(!text.includes('Model nền'));
  console.log('6 live-GPU/status/creator UI assertions passed; no production account writes.');
} finally { await browser.close(); }
