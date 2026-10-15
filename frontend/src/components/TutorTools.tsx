import { useEffect, useState } from 'react';
import { ArrowLeft, ArrowRight, Flag, RefreshCw, BookOpen, Download } from 'lucide-react';
import { ApiError, authHeaders, request } from '../api';
import type { Lang } from '../types';

type Question = {
  question_id: number;
  prompt: string;
  options: string[];
  question_type: string;
  is_flagged?: boolean;
};
type Quiz = { session_id: number; questions: Question[] };
type QuizResult = {
  total: number;
  correct_count: number;
  results: {
    question_id: number;
    is_correct: boolean;
    correct_answer: string;
    explanation_vi: string;
  }[];
};
type Attempt = {
  quiz: Quiz;
  answers: Record<number, string>;
  current: number;
  result: QuizResult | null;
};
type Study = {
  daily_goal: number;
  exercise: { sessions: number; attempts: number; correct: number; accuracy_percent: number };
  skills_available: string[];
  history: {
    id: number;
    skill: string;
    correct_count: number;
    total_questions: number;
    status: string;
  }[];
  documents: { id: number; title: string; file_type: string; chunk_count: number }[];
};
type Preferences = {
  theme: string;
  interface_language: string;
  language: string;
  adaptive_intelligence: boolean;
  voice_input: boolean;
  voice_output: boolean;
};

export function TutorTools({
  lang,
  accountKey,
  notify,
  login,
  useDocuments,
}: {
  lang: Lang;
  accountKey: string;
  notify: (s: string) => void;
  login: () => void;
  useDocuments: (ids: number[]) => void;
}) {
  const t = (vi: string, en: string) => (lang === 'vi' ? vi : en);
  const key = `tris.study.attempt.${accountKey}`;
  const [tab, setTab] = useState('quiz');
  const [data, setData] = useState<Study | null>(null);
  const [prefs, setPrefs] = useState<Preferences | null>(null);
  const [error, setError] = useState('');
  const [unauthorized, setUnauthorized] = useState(false);
  const [busy, setBusy] = useState(false);
  const [chosen, setChosen] = useState<number[]>([]);
  const [attempt, setAttempt] = useState<Attempt | null>(() => {
    try {
      return JSON.parse(sessionStorage.getItem(key) || 'null');
    } catch {
      return null;
    }
  });
  useEffect(() => {
    sessionStorage.setItem(key, JSON.stringify(attempt));
  }, [key, attempt]);
  async function refresh() {
    try {
      const [study, settings] = await Promise.all([
        request<Study>('/v1/workspace/study'),
        request<{ settings: Preferences }>('/v1/workspace/preferences'),
      ]);
      setData(study);
      setPrefs(settings.settings);
      setError('');
      setUnauthorized(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setUnauthorized(e instanceof ApiError && e.status === 401);
    }
  }
  useEffect(() => {
    void refresh();
  }, []);
  async function run(action: () => Promise<void>) {
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      await action();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  function startQuiz(quiz: Quiz) {
    setAttempt({ quiz, answers: {}, current: 0, result: null });
    setTab('quiz');
  }
  const question = attempt?.quiz.questions[attempt.current];
  const answerResult = attempt?.result?.results.find(
    (r) => r.question_id === question?.question_id,
  );
  return (
    <div className="tutor-tools">
      <nav className="tool-tabs">
        {[
          ['quiz', t('Bài tập', 'Exercises')],
          ['progress', t('Ôn tập & tiến độ', 'Review & progress')],
          ['documents', t('Thư viện', 'Library')],
          ['profile', t('Hồ sơ học & backup', 'Learning profile & backup')],
        ].map(([id, label]) => (
          <button key={id} className={tab === id ? 'active' : ''} onClick={() => setTab(id)}>
            {label}
          </button>
        ))}
        <button aria-label={t('Làm mới dữ liệu', 'Refresh data')} onClick={refresh}>
          <RefreshCw size={16} />
        </button>
      </nav>
      {error && (
        <div className="form-error" role="alert">
          {error}
          {unauthorized && (
            <button className="secondary-button" onClick={login}>
              {t('Đăng nhập tài khoản hiện có', 'Sign in to your existing account')}
            </button>
          )}
        </div>
      )}
      {!data && !error && (
        <p role="status">{t('Đang tải hồ sơ từ hệ thống…', 'Loading your existing profile…')}</p>
      )}
      {data && tab === 'quiz' && (
        <>
          <form
            className="quiz-setup"
            onSubmit={(e) => {
              e.preventDefault();
              const form = new FormData(e.currentTarget);
              void run(async () =>
                startQuiz(
                  await request<Quiz>('/v1/workspace/exercises', {
                    method: 'POST',
                    body: JSON.stringify({
                      skill: form.get('skill'),
                      difficulty: form.get('difficulty'),
                      question_count: Number(form.get('count')),
                    }),
                  }),
                ),
              );
            }}
          >
            <label>
              {t('Kỹ năng', 'Skill')}
              <select name="skill">
                {data.skills_available.map((skill) => (
                  <option key={skill}>{skill}</option>
                ))}
              </select>
            </label>
            <label>
              {t('Độ khó', 'Difficulty')}
              <select name="difficulty" defaultValue="Adaptive">
                {['Adaptive', 'Easy', 'Medium', 'Hard'].map((d) => (
                  <option key={d}>{d}</option>
                ))}
              </select>
            </label>
            <label>
              {t('Số câu', 'Questions')}
              <select name="count" defaultValue="5">
                <option>3</option>
                <option>5</option>
                <option>10</option>
              </select>
            </label>
            <button className="primary-button" disabled={busy || (!!attempt && !attempt.result)}>
              {busy
                ? t('Đang tạo bằng AI…', 'Generating with AI…')
                : t('Tạo bài tập', 'Generate exercises')}
            </button>
          </form>
          {attempt && question && (
            <div className="quiz-layout">
              <section className="quiz-question">
                <p className="muted">
                  {t('Câu', 'Question')} {attempt.current + 1}/{attempt.quiz.questions.length}
                </p>
                <h3>{question.prompt}</h3>
                {question.question_type === 'multiple_choice' ? (
                  <div className="quiz-options">
                    {question.options.map((option, i) => (
                      <label
                        className={
                          attempt.answers[question.question_id] === option ? 'selected' : ''
                        }
                        key={i}
                      >
                        <input
                          type="radio"
                          name={`answer-${question.question_id}`}
                          checked={attempt.answers[question.question_id] === option}
                          disabled={!!attempt.result || busy}
                          onChange={() =>
                            setAttempt({
                              ...attempt,
                              answers: { ...attempt.answers, [question.question_id]: option },
                            })
                          }
                        />
                        <span>{String.fromCharCode(65 + i)}.</span>
                        {option}
                      </label>
                    ))}
                  </div>
                ) : (
                  <textarea
                    aria-label={t('Câu trả lời', 'Your answer')}
                    placeholder={t('Nhập câu trả lời…', 'Type your answer…')}
                    value={attempt.answers[question.question_id] || ''}
                    disabled={!!attempt.result || busy}
                    onChange={(e) =>
                      setAttempt({
                        ...attempt,
                        answers: { ...attempt.answers, [question.question_id]: e.target.value },
                      })
                    }
                  />
                )}
                <div className="quiz-navigation">
                  <button
                    disabled={attempt.current === 0}
                    onClick={() => setAttempt({ ...attempt, current: attempt.current - 1 })}
                  >
                    <ArrowLeft size={15} />
                    {t('Câu trước', 'Previous')}
                  </button>
                  <button
                    disabled={busy}
                    aria-pressed={!!question.is_flagged}
                    onClick={() =>
                      void run(async () => {
                        const flagged = !question.is_flagged;
                        await request(
                          `/v1/workspace/exercises/${attempt.quiz.session_id}/questions/${question.question_id}/flag`,
                          { method: 'PUT', body: JSON.stringify({ flagged }) },
                        );
                        setAttempt(
                          (latest) =>
                            latest && {
                              ...latest,
                              quiz: {
                                ...latest.quiz,
                                questions: latest.quiz.questions.map((q) =>
                                  q.question_id === question.question_id
                                    ? { ...q, is_flagged: flagged }
                                    : q,
                                ),
                              },
                            },
                        );
                      })
                    }
                  >
                    <Flag size={15} />
                    {question.is_flagged ? t('Bỏ cờ', 'Unflag') : t('Cắm cờ', 'Flag')}
                  </button>
                  <button
                    disabled={attempt.current === attempt.quiz.questions.length - 1}
                    onClick={() => setAttempt({ ...attempt, current: attempt.current + 1 })}
                  >
                    {t('Câu sau', 'Next')}
                    <ArrowRight size={15} />
                  </button>
                </div>
                {answerResult && (
                  <div className={`quiz-feedback ${answerResult.is_correct ? 'correct' : ''}`}>
                    <strong>
                      {answerResult.is_correct
                        ? t('Chính xác', 'Correct')
                        : t('Cần xem lại', 'Review this answer')}
                    </strong>
                    <p>
                      {t('Đáp án: ', 'Answer: ')}
                      {answerResult.correct_answer}
                    </p>
                    <p>{answerResult.explanation_vi}</p>
                  </div>
                )}
              </section>
              <aside className="quiz-board">
                <h4>{t('Bảng câu hỏi', 'Questions')}</h4>
                <div className="quiz-number-grid">
                  {attempt.quiz.questions.map((q, i) => (
                    <button
                      key={q.question_id}
                      aria-label={`${t('Câu', 'Question')} ${i + 1}`}
                      aria-current={i === attempt.current ? 'step' : undefined}
                      className={`${attempt.answers[q.question_id]?.trim() ? 'answered' : ''} ${attempt.current === i ? 'current' : ''}`}
                      onClick={() => setAttempt({ ...attempt, current: i })}
                    >
                      {i + 1}
                      {q.is_flagged && <Flag size={10} />}
                    </button>
                  ))}
                </div>
                <small>
                  {t('Đã trả lời', 'Answered')}:{' '}
                  {Object.values(attempt.answers).filter((a) => a.trim()).length}/
                  {attempt.quiz.questions.length}
                </small>
                {attempt.result ? (
                  <p className="quiz-score">
                    {attempt.result.correct_count}/{attempt.result.total} {t('câu đúng', 'correct')}
                  </p>
                ) : (
                  <button
                    className="primary-button"
                    disabled={
                      busy ||
                      attempt.quiz.questions.some((q) => !attempt.answers[q.question_id]?.trim())
                    }
                    onClick={() =>
                      void run(async () => {
                        const result = await request<QuizResult>(
                          `/v1/workspace/exercises/${attempt.quiz.session_id}/submit`,
                          {
                            method: 'POST',
                            body: JSON.stringify({
                              answers: attempt.quiz.questions.map((q) => ({
                                question_id: q.question_id,
                                answer: attempt.answers[q.question_id],
                              })),
                            }),
                          },
                        );
                        setAttempt({ ...attempt, result });
                        await refresh();
                      })
                    }
                  >
                    {t('Nộp toàn bộ bài', 'Submit all answers')}
                  </button>
                )}
                {attempt.result && (
                  <button className="text-button" onClick={() => setAttempt(null)}>
                    {t('Bài mới', 'New exercise')}
                  </button>
                )}
                <p className="muted">
                  {t(
                    'Ô đậm = đã trả lời, chưa chấm đúng/sai.',
                    'Filled box = answered, not yet graded.',
                  )}
                </p>
              </aside>
            </div>
          )}
          {!attempt && (
            <p className="muted">
              {t(
                'Bài tập được tạo bằng model local thật và lưu vào hồ sơ hiện tại.',
                'Exercises use your real local model and existing learning profile.',
              )}
            </p>
          )}
        </>
      )}
      {data && tab === 'progress' && (
        <>
          <div className="study-stats">
            <span>
              {t('Đã hoàn thành', 'Completed')}
              <strong>{data.exercise.sessions}</strong>
            </span>
            <span>
              {t('Số câu đã làm', 'Answers')}
              <strong>{data.exercise.attempts}</strong>
            </span>
            <span>
              {t('Độ chính xác', 'Accuracy')}
              <strong>{data.exercise.accuracy_percent}%</strong>
            </span>
          </div>
          <form
            className="quiz-setup"
            onSubmit={(e) => {
              e.preventDefault();
              const daily_question_goal = Number(new FormData(e.currentTarget).get('goal'));
              void run(async () => {
                await request('/v1/workspace/goal', {
                  method: 'PUT',
                  body: JSON.stringify({ daily_question_goal }),
                });
                await refresh();
              });
            }}
          >
            <label>
              {t('Mục tiêu câu/ngày', 'Daily question goal')}
              <input name="goal" type="number" min={1} max={200} defaultValue={data.daily_goal} />
            </label>
            <button className="secondary-button" disabled={busy}>
              {t('Lưu mục tiêu', 'Save goal')}
            </button>
          </form>
          <div className="review-actions">
            {[
              ['wrong', t('Ôn câu sai', 'Review mistakes')],
              ['flagged', t('Ôn câu cắm cờ', 'Review flagged')],
              ['weak', t('Ôn điểm yếu', 'Review weak skills')],
            ].map(([kind, label]) => (
              <button
                className="secondary-button"
                disabled={busy || (!!attempt && !attempt.result)}
                key={kind}
                onClick={() =>
                  void run(async () =>
                    startQuiz(
                      await request<Quiz>(`/v1/workspace/review/${kind}`, { method: 'POST' }),
                    ),
                  )
                }
              >
                {label}
              </button>
            ))}
          </div>
          <h3>{t('Lịch sử bài học', 'Exercise history')}</h3>
          <div className="study-list">
            {data.history.map((h) => (
              <div key={h.id}>
                <span>
                  #{h.id} · {h.skill}
                </span>
                <strong>
                  {h.status === 'completed'
                    ? `${h.correct_count}/${h.total_questions}`
                    : t('Chưa nộp', 'Not submitted')}
                </strong>
              </div>
            ))}
            {!data.history.length && (
              <p className="muted">{t('Chưa có bài tập đã lưu.', 'No exercises saved yet.')}</p>
            )}
          </div>
        </>
      )}
      {data && tab === 'documents' && (
        <>
          <p className="muted">
            {t(
              'Đây là thư viện đã có trong hồ sơ cũ. Tải tài liệu mới bằng dấu + hoặc kéo vào chat.',
              'Your existing document library. Upload new files with + or drag them into chat.',
            )}
          </p>
          <div className="study-list">
            {data.documents.map((doc) => (
              <label key={doc.id}>
                <input
                  type="checkbox"
                  checked={chosen.includes(doc.id)}
                  onChange={(e) =>
                    setChosen(
                      e.target.checked ? [...chosen, doc.id] : chosen.filter((id) => id !== doc.id),
                    )
                  }
                />
                <BookOpen size={16} />
                <span>
                  {doc.title}
                  <small>
                    {doc.file_type} · {doc.chunk_count} {t('đoạn', 'chunks')}
                  </small>
                </span>
              </label>
            ))}
          </div>
          {!data.documents.length && (
            <p>{t('Chưa có tài liệu trong hồ sơ.', 'No documents in this profile.')}</p>
          )}
          <button
            className="primary-button"
            disabled={!chosen.length}
            onClick={() => useDocuments(chosen)}
          >
            {t('Hỏi AI về tài liệu đã chọn', 'Ask AI about selected documents')}
          </button>
          <button
            className="secondary-button"
            disabled={!chosen.length || busy || (!!attempt && !attempt.result)}
            onClick={() =>
              void run(async () =>
                startQuiz(
                  await request<Quiz>('/v1/workspace/exercises', {
                    method: 'POST',
                    body: JSON.stringify({
                      skill: 'General Grammar',
                      difficulty: 'Adaptive',
                      question_count: 5,
                      document_ids: chosen,
                    }),
                  }),
                ),
              )
            }
          >
            {t('Tạo 5 câu từ tài liệu', 'Create 5 questions from documents')}
          </button>
        </>
      )}
      {tab === 'profile' && prefs && (
        <>
          <p className="muted">
            {t(
              'Các tùy chọn dưới đây được lưu vào SQLite hiện có, không tạo hồ sơ tách riêng.',
              'These preferences are saved to the existing SQLite learning profile.',
            )}
          </p>
          <label className="setting-row">
            {t('Ngôn ngữ giải thích của AI', 'AI explanation language')}
            <select
              value={prefs.language}
              onChange={(e) => setPrefs({ ...prefs, language: e.target.value })}
            >
              <option value="vi">Tiếng Việt</option>
              <option value="en">English</option>
            </select>
          </label>
          {(['adaptive_intelligence', 'voice_input', 'voice_output'] as const).map((name, i) => (
            <label className="setting-row" key={name}>
              <span>
                {
                  [
                    t('Cá nhân hóa theo kỹ năng', 'Adapt to learning skills'),
                    t('Nhập bằng giọng nói', 'Voice input'),
                    t('Bật giọng đọc', 'Enable read aloud'),
                  ][i]
                }
              </span>
              <input
                type="checkbox"
                checked={prefs[name]}
                onChange={(e) => setPrefs({ ...prefs, [name]: e.target.checked })}
              />
            </label>
          ))}
          <button
            className="primary-button"
            disabled={busy}
            onClick={() =>
              void run(async () => {
                await request('/v1/workspace/preferences', {
                  method: 'PUT',
                  body: JSON.stringify(prefs),
                });
                notify(t('Đã lưu cài đặt hồ sơ.', 'Learning preferences saved.'));
              })
            }
          >
            {t('Lưu cài đặt hồ sơ', 'Save profile preferences')}
          </button>
          <div className="review-actions">
            <button
              className="secondary-button"
              disabled={busy}
              onClick={() =>
                void run(async () => {
                  const r = await request<{ path: string }>('/v1/workspace/backup', {
                    method: 'POST',
                  });
                  notify(t('Đã sao lưu SQLite: ', 'SQLite backed up: ') + r.path);
                })
              }
            >
              {t('Sao lưu SQLite', 'Back up SQLite')}
            </button>
            <button
              className="secondary-button"
              onClick={() =>
                void run(async () => {
                  const data = await request('/v1/workspace/export');
                  const url = URL.createObjectURL(
                    new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }),
                  );
                  const a = document.createElement('a');
                  a.href = url;
                  a.download = 'tris-learner.json';
                  a.click();
                  setTimeout(() => URL.revokeObjectURL(url), 1000);
                })
              }
            >
              <Download size={15} />
              {t('Xuất hồ sơ JSON', 'Export profile JSON')}
            </button>
          </div>
        </>
      )}
    </div>
  );
}

export function MediaTools({ lang }: { lang: Lang }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [media, setMedia] = useState<{ url: string; mode: string; name: string } | null>(null);
  const t = (vi: string, en: string) => (lang === 'vi' ? vi : en);
  useEffect(
    () => () => {
      if (media) URL.revokeObjectURL(media.url);
    },
    [media],
  );
  return (
    <div className="modal-body">
      <p className="muted">
        {t(
          'Dùng pipeline sd-turbo local hiện có. Quá trình có thể mất vài phút trên GPU 6 GB.',
          'Uses your existing local sd-turbo pipeline. Processing can take a few minutes on a 6 GB GPU.',
        )}
      </p>
      <form
        className="auth-form"
        onSubmit={async (e) => {
          e.preventDefault();
          if (busy) return;
          const form = new FormData(e.currentTarget);
          setBusy(true);
          setError('');
          try {
            const mode = String(form.get('mode'));
            const r = await request<{ file_url: string; file_name: string }>('/v1/media-generate', {
              method: 'POST',
              body: JSON.stringify({ prompt: form.get('prompt'), mode, frames: 6 }),
            });
            const response = await fetch(r.file_url, { headers: authHeaders() });
            if (!response.ok)
              throw new Error(t('Không tải được ảnh/video.', 'Could not load generated media.'));
            setMedia({ url: URL.createObjectURL(await response.blob()), mode, name: r.file_name });
          } catch (e) {
            setError(e instanceof Error ? e.message : String(e));
          } finally {
            setBusy(false);
          }
        }}
      >
        <label>
          {t('Mô tả', 'Description')}
          <input
            name="prompt"
            required
            maxLength={1000}
            placeholder={t('Mô tả hình ảnh bạn muốn…', 'Describe your image…')}
          />
        </label>
        <label>
          {t('Định dạng', 'Format')}
          <select name="mode">
            <option value="image">PNG</option>
            <option value="gif">GIF</option>
            <option value="video">Video MP4</option>
          </select>
        </label>
        <button className="primary-button" disabled={busy}>
          {busy ? t('Đang tạo trên máy…', 'Generating locally…') : t('Bắt đầu tạo', 'Generate')}
        </button>
      </form>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      {media && (
        <div className="generated-media">
          {media.mode === 'video' ? (
            <video src={media.url} controls />
          ) : (
            <img src={media.url} alt={t('Nội dung Tris vừa tạo', 'Generated by Tris')} />
          )}
          <a download={media.name} href={media.url}>
            {t('Tải xuống', 'Download')}
          </a>
        </div>
      )}
    </div>
  );
}
