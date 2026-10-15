import { chromium } from 'playwright';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';

// Browser-only fixtures: exercise UI contracts without changing real learner data.
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
const questions = Array.from({ length: 5 }, (_, i) => ({
  question_id: i + 1,
  prompt: `Choose the correct sentence (${i + 1}).`,
  question_type: 'multiple_choice',
  options: ['She go to school.', 'She goes to school.', 'She going school.', 'She gone school.'],
}));
const preferences = {
  theme: 'dark',
  interface_language: 'vi',
  language: 'vi',
  adaptive_intelligence: true,
  voice_input: false,
  voice_output: false,
};
const submissions = [];
const flags = [];
const forbidden = [];
await page.addInitScript(() =>
  sessionStorage.setItem(
    'tris.workspace.session',
    JSON.stringify({
      token: 'browser-fixture-only',
      account: { account_id: 'test-ui', username: 'QA', learner_name: 'Existing Learner' },
    }),
  ),
);
await page.route('**/health', (route) =>
  route.fulfill({ json: { status: 'ok', auth_required: true, social_login: { google: true } } }),
);
await page.route('**/v1/**', async (route) => {
  const url = new URL(route.request().url());
  const path = url.pathname;
  if (path === '/v1/workspace/presence') return route.continue();
  if (path === '/v1/workspace/models')
    return route.fulfill({
      json: { default: 'english-tutor-local:4b', models: [{ name: 'english-tutor-local:4b' }] },
    });
  if (path === '/v1/workspace/session')
    return route.fulfill({
      json: {
        settings: preferences,
        chats: [
          {
            id: 'history-test',
            title: 'Hội thoại từ hồ sơ cũ',
            mode: 'Grammar',
            scenario: '',
            draft: '',
            project: '',
            demo: false,
            created: '2026-09-01',
            messages: [{ id: 'db-1', role: 'user', content: 'An existing saved message.' }],
          },
        ],
      },
    });
  if (path === '/v1/workspace/study')
    return route.fulfill({
      json: {
        daily_goal: 10,
        exercise: { sessions: 8, attempts: 40, correct: 30, accuracy_percent: 75 },
        skills_available: ['General Grammar'],
        history: [
          {
            id: 7,
            skill: 'General Grammar',
            correct_count: 4,
            total_questions: 5,
            status: 'completed',
          },
        ],
        documents: [{ id: 2, title: 'Tài liệu cũ.pdf', file_type: 'pdf', chunk_count: 12 }],
      },
    });
  if (path === '/v1/workspace/preferences')
    return route.fulfill({ json: { settings: preferences } });
  if (path === '/v1/workspace/exercises')
    return route.fulfill({ json: { session_id: 42, questions } });
  if (path.endsWith('/flag')) {
    flags.push(route.request().postDataJSON());
    return route.fulfill({ json: { flagged: true } });
  }
  if (path.endsWith('/submit')) {
    submissions.push(route.request().postDataJSON());
    return route.fulfill({
      json: {
        total: 5,
        correct_count: 5,
        results: questions.map((q) => ({
          question_id: q.question_id,
          is_correct: true,
          correct_answer: 'She goes to school.',
          explanation_vi: 'Chủ ngữ she dùng động từ goes.',
        })),
      },
    });
  }
  forbidden.push(path);
  return route.fulfill({ status: 500, json: { detail: 'Unmocked request blocked by test' } });
});
let passed = 0;
const ok = (label, value = true) => {
  assert.ok(value, label);
  passed++;
  console.log('PASS ' + label);
};
try {
  await page.goto(process.env.TRIS_TEST_URL || 'http://127.0.0.1:7860');
  await page.getByText('Hội thoại từ hồ sơ cũ', { exact: true }).waitFor();
  ok('Existing profile history loads into sidebar');
  await page.getByRole('button', { name: 'Học tập & tài liệu', exact: true }).click();
  await page.getByRole('button', { name: 'Tạo bài tập', exact: true }).click();
  await page.getByRole('heading', { name: 'Choose the correct sentence (1).' }).waitFor();
  ok(
    'Study dialog is full width',
    (await page.locator('.study-modal').boundingBox()).width >= 1000,
  );
  const questionBox = await page.locator('.quiz-question').boundingBox();
  const boardBox = await page.locator('.quiz-board').boundingBox();
  ok(
    'Question board sits to the right of question',
    boardBox.x > questionBox.x + questionBox.width,
  );
  ok(
    'Bulk submit disabled until all questions answered',
    await page.getByRole('button', { name: 'Nộp toàn bộ bài' }).isDisabled(),
  );
  await page.getByRole('radio').nth(1).check();
  ok(
    'Answered box shaded without correctness',
    await page
      .getByRole('button', { name: 'Câu 1', exact: true })
      .evaluate((el) => el.classList.contains('answered')),
  );
  ok(
    'No answer explanation before bulk submit',
    (await page.locator('.quiz-feedback').count()) === 0,
  );
  await page.getByRole('button', { name: 'Câu 2', exact: true }).click();
  ok(
    'Direct numbered navigation works',
    (await page.locator('.quiz-question h3').innerText()).includes('(2)'),
  );
  await page.getByRole('radio').nth(1).check();
  await page.getByRole('button', { name: 'Cắm cờ', exact: true }).click();
  await page.getByRole('button', { name: 'Bỏ cờ', exact: true }).waitFor();
  ok('Flag persists through API', flags.length === 1 && flags[0].flagged);
  for (let i = 3; i <= 5; i++) {
    await page.getByRole('button', { name: `Câu ${i}`, exact: true }).click();
    await page.getByRole('radio').nth(1).check();
  }
  await page.keyboard.press('Escape');
  await page.getByRole('button', { name: 'Học tập & tài liệu', exact: true }).click();
  ok(
    'Closing panel preserves attempt',
    await page.getByRole('button', { name: 'Nộp toàn bộ bài' }).isEnabled(),
  );
  for (const width of [320, 390, 768, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    const b = await page.locator('.study-modal').boundingBox();
    ok(`Study ${width}px modal within viewport`, b.x >= 0 && b.x + b.width <= width + 1);
    ok(
      `Study ${width}px no horizontal overflow`,
      await page.locator('.study-modal').evaluate((el) => el.scrollWidth <= el.clientWidth + 1),
    );
  }
  await fs.mkdir('test-results', { recursive: true });
  await page.screenshot({ path: 'test-results/study-quiz.png' });
  await page.getByRole('button', { name: 'Nộp toàn bộ bài' }).click();
  await page.locator('.quiz-score').waitFor();
  ok(
    'All five answers submitted in one request',
    submissions.length === 1 && submissions[0].answers.length === 5,
  );
  ok(
    'Explanation shown after submit',
    (await page.locator('.quiz-feedback').innerText()).includes('Chủ ngữ she'),
  );
  await page.getByRole('button', { name: 'Ôn tập & tiến độ', exact: true }).click();
  ok('Existing progress shown', (await page.locator('.study-stats').innerText()).includes('75%'));
  await page.getByRole('button', { name: 'Thư viện', exact: true }).click();
  await page.getByRole('checkbox').check();
  await page.getByRole('button', { name: 'Hỏi AI về tài liệu đã chọn', exact: true }).click();
  ok(
    'Old library documents feed chat RAG',
    (await page.locator('.composer-files').innerText()).includes('1 tài liệu từ thư viện'),
  );
  ok('No unexpected backend writes', forbidden.length === 0);
  ok('No browser errors', errors.length === 0);
  console.log(
    `${passed} study assertions passed (browser fixtures; no production records modified).`,
  );
} finally {
  await browser.close();
}
