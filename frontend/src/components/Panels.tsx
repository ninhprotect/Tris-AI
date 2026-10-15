import { useEffect, useState } from 'react';
import {
  ArrowUpRight,
  BookOpen,
  CalendarClock,
  Check,
  CloudOff,
  Download,
  Globe2,
  HardDrive,
  Laptop,
  LockKeyhole,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
  UserRound,
} from 'lucide-react';
import { ApiError, request } from '../api';
import type { Account, Chat, ChatAction, Health, Lang, Panel, Settings } from '../types';
import { Modal, Toggle, TrisMark } from './ui';
import { TutorTools } from './TutorTools';

export type Reminder = { id: string; title: string; at: string; done?: boolean };
export function Panels({
  panel,
  close,
  lang,
  settings,
  changeSettings,
  health,
  account,
  onLogin,
  setPanel,
  notify,
  usePrompt,
  chats,
  selectChat,
  reminders,
  setReminders,
  useDocuments,
  selectAction,
}: {
  panel: Panel;
  close: () => void;
  lang: Lang;
  settings: Settings;
  changeSettings: (p: Partial<Settings>) => void;
  health: Health | null;
  account: Account | null;
  onLogin: (token: string, account: Account) => void;
  setPanel: (p: Panel) => void;
  notify: (v: string) => void;
  usePrompt: (v: string) => void;
  chats: Chat[];
  selectChat: (id: string) => void;
  reminders: Reminder[];
  setReminders: (r: Reminder[]) => void;
  useDocuments: (ids: number[]) => void;
  selectAction: (action: ChatAction) => void;
}) {
  const [tab, setTab] = useState('general');
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [voice, setVoice] = useState<{
    engine: string;
    speaker: boolean;
    reference_count: number;
    error?: string;
    device?: string;
    gpu_name?: string;
    device_notice?: string;
    last_conversion_seconds?: number;
  } | null>(null);
  useEffect(() => {
    if (panel === 'settings')
      void request<NonNullable<typeof voice>>('/v1/workspace/voice-status')
        .then(setVoice)
        .catch(() => setVoice(null));
  }, [panel]);
  const t = (vi: string, en: string) => (lang === 'vi' ? vi : en);
  if (!panel) return null;
  const title = {
    settings: t('Cài đặt', 'Settings'),
    usage: t('Mức sử dụng', 'Usage'),
    upgrade: t('Không gian của riêng bạn', 'Your own workspace'),
    prompts: t('Một chút cảm hứng', 'A little inspiration'),
    schedule: t('Lịch học của bạn', 'Your study schedule'),
    plugins: t('Công cụ của Tris', 'Tris tools'),
    search: t('Tìm cuộc trò chuyện', 'Find a conversation'),
    login: t('Chào mừng trở lại', 'Welcome back'),
    register: t('Bắt đầu cùng Tris', 'Get started with Tris'),
    study: t('Học tập & tài liệu', 'Study & documents'),
    media: t('Sáng tạo với Tris', 'Create with Tris'),
  }[panel];
  async function authenticate(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setLoading(true);
    setError('');
    try {
      const username = String(form.get('username'));
      const password = String(form.get('password'));
      if (panel === 'register' && password !== form.get('confirm'))
        throw new Error(t('Hai mật khẩu chưa khớp.', 'Passwords do not match.'));
      const data = await request<{ access_token: string; account: Account }>(
        `/v1/auth/${panel === 'register' ? 'register' : 'login'}`,
        {
          method: 'POST',
          body: JSON.stringify({
            username,
            password,
            ...(panel === 'register' ? { learner_name: String(form.get('name')) || username } : {}),
          }),
        },
      );
      onLogin(data.access_token, data.account);
      close();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : t('Chưa đăng nhập được.', 'Unable to sign in.'),
      );
    } finally {
      setLoading(false);
    }
  }
  function exportData() {
    const blob = new Blob(
      [
        JSON.stringify(
          {
            app: 'Tris AI Workspace',
            version: 1,
            exported: new Date().toISOString(),
            chats: chats.map((c) => ({
              ...c,
              messages: c.messages.map((m) => ({
                ...m,
                attachments: m.attachments?.map(({ file, preview, ...a }) => a),
              })),
            })),
            settings,
            reminders,
          },
          null,
          2,
        ),
      ],
      { type: 'application/json' },
    );
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `tris-workspace-${new Date().toISOString().slice(0, 10)}.json`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    notify(t('Đã xuất bản sao workspace.', 'Workspace exported.'));
  }
  return (
    <Modal
      title={title}
      close={close}
      className={
        panel === 'study'
          ? 'study-modal'
          : panel === 'settings'
            ? 'settings-modal'
            : panel === 'search'
              ? 'search-modal'
              : ''
      }
    >
      {panel === 'study' && (
        <TutorTools
          lang={lang}
          accountKey={account?.account_id || 'guest'}
          notify={notify}
          login={() => setPanel('login')}
          useDocuments={(ids) => {
            useDocuments(ids);
            close();
          }}
        />
      )}
      {panel === 'media' && (
        <button className="primary-button" onClick={() => selectAction('image')}>
          {t('Tạo ảnh ngay trong chat', 'Create images in this chat')}
        </button>
      )}
      {panel === 'settings' && (
        <div className="settings-layout">
          <nav className="settings-nav" aria-label={t('Danh mục cài đặt', 'Settings categories')}>
            {[
              ['general', Settings2, t('Chung', 'General')],
              ['account', UserRound, t('Tài khoản', 'Account')],
              ['data', HardDrive, t('Dữ liệu', 'Data')],
              ['voice', Sparkles, t('Giọng Tris', 'Tris voice')],
            ].map(([id, Icon, text]) => {
              const I = Icon as typeof Settings2;
              return (
                <button
                  key={String(id)}
                  className={tab === id ? 'selected' : ''}
                  onClick={() => setTab(String(id))}
                >
                  <I size={17} />
                  {String(text)}
                </button>
              );
            })}
          </nav>
          <div className="settings-content">
            {tab === 'voice' && (
              <>
                <h3>{t('Giọng từ mẫu được cấp phép', 'Voice from authorized recordings')}</h3>
                <p className="muted">
                  {t(
                    'Nội dung câu trả lời được tổng hợp thành lời nói mới rồi chuyển đặc trưng giọng bằng OpenVoice. Không phát ghép file MP3 gốc.',
                    'Responses are newly synthesized and tone-converted with OpenVoice. Original MP3 clips are not spliced into answers.',
                  )}
                </p>
                <div className="setting-row">
                  <span>{t('Trạng thái', 'Status')}</span>
                  <strong>
                    {voice?.speaker && !voice.error
                      ? t('Sẵn sàng', 'Ready')
                      : t('Chưa sẵn sàng / cần đăng nhập', 'Unavailable / sign in')}
                  </strong>
                </div>
                <div className="setting-row">
                  <span>{t('Số mẫu tham chiếu', 'Reference clips')}</span>
                  <strong>{voice?.reference_count ?? '—'}</strong>
                </div>
                {voice?.error && <p className="form-error">{voice.error}</p>}
                <div className="setting-row">
                  <span>{t('Bộ xử lý chuyển giọng', 'Voice conversion processor')}</span>
                  <strong>
                    {voice?.device?.startsWith('cuda')
                      ? voice.gpu_name || 'NVIDIA GPU'
                      : voice?.device === 'cpu'
                        ? 'CPU'
                        : '—'}
                  </strong>
                </div>
                {voice?.device_notice && <p className="muted">{voice.device_notice}</p>}
                <p className="muted">
                  {t(
                    'English: nhịp đọc chậm, giữ cao độ tự nhiên. Tiếng Việt giữ cấu hình hiện tại.',
                    'English: slower articulation, natural pitch. Vietnamese keeps its existing preset.',
                  )}
                </p>
                <p className="muted">
                  {t(
                    'Bấm biểu tượng loa dưới câu trả lời để nghe. Không tự phát; không âm thầm đổi sang giọng khác nếu chuyển giọng lỗi. Độ giống không được cam kết 100%.',
                    'Click the speaker below a response to listen. No autoplay or silent voice substitution. A 100% voice match is not guaranteed.',
                  )}
                </p>
              </>
            )}
            {tab === 'general' && (
              <>
                <h3>{t('Theo cách của bạn', 'Make it yours')}</h3>
                <div className="setting-row">
                  <label htmlFor="theme-select">{t('Giao diện', 'Appearance')}</label>
                  <select
                    id="theme-select"
                    value={settings.theme}
                    onChange={(e) => changeSettings({ theme: e.target.value as Settings['theme'] })}
                  >
                    <option value="dark">{t('Tối', 'Dark')}</option>
                    <option value="light">{t('Sáng', 'Light')}</option>
                    <option value="system">{t('Hệ thống', 'System')}</option>
                  </select>
                </div>
                <div className="setting-row">
                  <label htmlFor="lang-select">{t('Ngôn ngữ hệ thống', 'System language')}</label>
                  <select
                    id="lang-select"
                    value={lang}
                    onChange={(e) => changeSettings({ lang: e.target.value as Lang })}
                  >
                    <option value="vi">Tiếng Việt (VI)</option>
                    <option value="en">English (EN)</option>
                  </select>
                </div>
                <div className="setting-row">
                  <span>
                    {t('Tìm kiếm web', 'Web search')}
                    <small>
                      {t(
                        'Từ khóa được gửi ra Internet khi bật.',
                        'Queries are sent to the Internet when enabled.',
                      )}
                    </small>
                  </span>
                  <Toggle
                    label={t('Tìm kiếm web', 'Web search')}
                    value={settings.web}
                    change={(v) => changeSettings({ web: v })}
                  />
                </div>
                <div className="setting-row">
                  <span>{t('Thu gọn sidebar', 'Compact sidebar')}</span>
                  <Toggle
                    label={t('Thu gọn sidebar', 'Compact sidebar')}
                    value={settings.collapsed}
                    change={(v) => changeSettings({ collapsed: v })}
                  />
                </div>
                <p className="settings-hint">
                  <Check size={14} />
                  {t('Tự động lưu trên trình duyệt này.', 'Automatically saved in this browser.')}
                </p>
              </>
            )}
            {tab === 'account' && (
              <>
                <h3>
                  {account?.learner_name ||
                    t('Bạn đang ở chế độ khách', 'You are browsing as a guest')}
                </h3>
                <p className="muted">
                  {t(
                    'Đăng nhập để gọi model, tải tài liệu và kết nối với hồ sơ học của bạn.',
                    'Sign in to chat with a model, upload documents and connect your learner profile.',
                  )}
                </p>
                <button
                  className="primary-button"
                  onClick={() => {
                    setError('');
                    setPanel('login');
                  }}
                >
                  {t('Đăng nhập', 'Sign in')}
                </button>
                {account && (
                  <form
                    className="auth-form"
                    onSubmit={async (e) => {
                      e.preventDefault();
                      const f = new FormData(e.currentTarget);
                      setLoading(true);
                      try {
                        await request('/v1/auth/change-password', {
                          method: 'POST',
                          body: JSON.stringify({
                            current_password: f.get('current'),
                            new_password: f.get('next'),
                          }),
                        });
                        notify(t('Đã đổi mật khẩu.', 'Password updated.'));
                      } catch (e) {
                        notify(e instanceof Error ? e.message : 'Error');
                      } finally {
                        setLoading(false);
                      }
                    }}
                  >
                    <label>
                      {t('Mật khẩu hiện tại', 'Current password')}
                      <input
                        name="current"
                        type="password"
                        required
                        autoComplete="current-password"
                      />
                    </label>
                    <label>
                      {t('Mật khẩu mới', 'New password')}
                      <input
                        name="next"
                        type="password"
                        required
                        minLength={10}
                        autoComplete="new-password"
                      />
                    </label>
                    <button className="secondary-button" disabled={loading}>
                      {t('Đổi mật khẩu', 'Change password')}
                    </button>
                  </form>
                )}
              </>
            )}
            {tab === 'data' && (
              <>
                <h3>{t('Dữ liệu thuộc về bạn', 'Your data is yours')}</h3>
                <p className="muted">
                  {t(
                    'Xuất hội thoại, draft và cài đặt của giao diện mới. Không bao gồm mật khẩu, token hay dữ liệu PostgreSQL.',
                    'Export chats, drafts and settings from this workspace. Passwords, tokens and PostgreSQL data are excluded.',
                  )}
                </p>
                <button className="secondary-button" onClick={exportData}>
                  <Download size={16} />
                  {t('Xuất workspace JSON', 'Export workspace JSON')}
                </button>
                <p className="settings-hint">
                  {t(
                    'Bản sao dữ liệu học của giao diện cũ vẫn ở thư mục backups của dự án.',
                    'Backups from the previous learning interface remain in the project backups folder.',
                  )}
                </p>
              </>
            )}
          </div>
        </div>
      )}
      {(panel === 'login' || panel === 'register') && (
        <div className="modal-body auth-body">
          <TrisMark className="auth-mark" />
          <p className="muted">
            {t(
              'Tiếp tục hành trình học cùng một người bạn AI.',
              'Continue learning with your own AI companion.',
            )}
          </p>
          {health?.social_login?.google && (
            <a className="google-button" href="/v1/auth/oauth/google/start">
              <Globe2 size={18} />
              {t('Tiếp tục với Google', 'Continue with Google')}
            </a>
          )}
          <form className="auth-form" onSubmit={authenticate}>
            <label>
              {t('Tên đăng nhập', 'Username')}
              <input
                name="username"
                autoComplete="username"
                minLength={3}
                maxLength={32}
                required
                autoFocus
              />
            </label>
            {panel === 'register' && (
              <label>
                {t('Tên hiển thị', 'Display name')}
                <input name="name" autoComplete="nickname" maxLength={50} required />
              </label>
            )}
            <label>
              {t('Mật khẩu', 'Password')}
              <input
                name="password"
                type="password"
                autoComplete={panel === 'register' ? 'new-password' : 'current-password'}
                minLength={panel === 'register' ? 10 : 1}
                maxLength={128}
                required
              />
            </label>
            {panel === 'register' && (
              <>
                <label>
                  {t('Nhập lại mật khẩu', 'Confirm password')}
                  <input name="confirm" type="password" autoComplete="new-password" required />
                </label>
                <small className="muted">
                  {t(
                    'Ít nhất 10 ký tự, gồm chữ hoa, chữ thường và chữ số.',
                    'At least 10 characters with uppercase, lowercase and a number.',
                  )}
                </small>
              </>
            )}
            {error && (
              <p role="alert" className="form-error">
                {error}
              </p>
            )}
            <button className="primary-button" disabled={loading}>
              {loading
                ? t('Đang kết nối…', 'Connecting…')
                : panel === 'login'
                  ? t('Đăng nhập', 'Sign in')
                  : t('Tạo tài khoản', 'Create account')}
            </button>
          </form>
          <button
            className="text-button"
            onClick={() => {
              setError('');
              setPanel(panel === 'login' ? 'register' : 'login');
            }}
          >
            {panel === 'login'
              ? t('Chưa có tài khoản? Đăng ký', 'New here? Create an account')
              : t('Đã có tài khoản? Đăng nhập', 'Already have an account? Sign in')}
          </button>
        </div>
      )}
      {panel === 'search' && (
        <div className="modal-body">
          <div className="search-field">
            <Search size={18} />
            <input
              autoFocus
              aria-label={t('Tìm theo tên hoặc nội dung', 'Search by title or content')}
              placeholder={t('Tìm theo tên hoặc nội dung...', 'Search by title or content...')}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
          <div className="search-results">
            {chats
              .filter(
                (c) =>
                  c.messages.length &&
                  (c.title + c.messages.map((m) => m.content).join(' '))
                    .toLocaleLowerCase()
                    .includes(query.toLocaleLowerCase()),
              )
              .map((c) => (
                <button
                  key={c.id}
                  onClick={() => {
                    selectChat(c.id);
                    close();
                  }}
                >
                  <span>
                    {c.title}
                    <small>
                      {c.demo ? t('Hội thoại mẫu', 'Sample chat') : c.project || 'Tris AI'}
                    </small>
                  </span>
                  <ArrowUpRight size={16} />
                </button>
              ))}
          </div>
        </div>
      )}
      {panel === 'prompts' && (
        <div className="modal-body">
          <p className="muted">
            {t(
              'Chọn một ý tưởng. Cùng Tris biến nó thành bước tiến nhỏ hôm nay.',
              'Pick an idea. Take a small step forward with Tris.',
            )}
          </p>
          <div className="prompt-list">
            {[
              t(
                'Cùng mình luyện hội thoại ở quán cà phê.',
                'Let’s practice a conversation at a coffee shop.',
              ),
              t(
                'Giải thích thì hiện tại hoàn thành bằng ví dụ dễ hiểu.',
                'Explain the present perfect with simple examples.',
              ),
              t(
                'Giúp mình viết một email công việc tự nhiên hơn.',
                'Help me write a more natural work email.',
              ),
              t(
                'Cho mình 5 từ tiếng Anh về một chủ đề mới.',
                'Teach me five English words about a new topic.',
              ),
            ].map((p) => (
              <button
                key={p}
                onClick={() => {
                  usePrompt(p);
                  close();
                }}
              >
                <BookOpen size={18} />
                <span>{p}</span>
                <ArrowUpRight size={15} />
              </button>
            ))}
          </div>
        </div>
      )}
      {panel === 'schedule' && (
        <div className="modal-body">
          <p className="muted">
            {t(
              'Lời nhắc hiển thị trong Tris khi trang đang mở. Không chạy ngầm khi đóng trình duyệt.',
              'Reminders appear while this page is open. They do not run after the browser closes.',
            )}
          </p>
          <form
            className="auth-form"
            onSubmit={(e) => {
              e.preventDefault();
              const f = new FormData(e.currentTarget);
              const at = String(f.get('at'));
              if (new Date(at).getTime() <= Date.now()) {
                notify(t('Hãy chọn thời điểm trong tương lai.', 'Choose a future time.'));
                return;
              }
              setReminders([
                ...reminders,
                { id: crypto.randomUUID(), title: String(f.get('title')), at },
              ]);
              e.currentTarget.reset();
            }}
          >
            <label>
              {t('Mình sẽ học gì?', 'What will you study?')}
              <input
                name="title"
                required
                maxLength={100}
                placeholder={t('15 phút luyện nói', '15 minutes of conversation')}
              />
            </label>
            <label>
              {t('Thời gian', 'When')}
              <input name="at" type="datetime-local" required />
            </label>
            <button className="secondary-button">
              <CalendarClock size={16} />
              {t('Thêm lịch học', 'Add reminder')}
            </button>
          </form>
          <div className="reminder-list">
            {reminders.map((r) => (
              <div key={r.id}>
                <CalendarClock size={17} />
                <span>
                  {r.title}
                  <small>
                    {new Date(r.at).toLocaleString(lang)} {r.done && '✓'}
                  </small>
                </span>
                <button
                  className="text-button"
                  onClick={() =>
                    setReminders(
                      reminders.map((v) => (v.id === r.id ? { ...v, done: !v.done } : v)),
                    )
                  }
                >
                  {r.done ? t('Đã xong', 'Done') : t('Đánh dấu xong', 'Complete')}
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
      {panel === 'plugins' && (
        <div className="modal-body">
          <p className="muted">
            {t(
              'Những công cụ kết nối với không gian học của bạn.',
              'Tools that connect to your learning space.',
            )}
          </p>
          <div className="integration-list">
            <div>
              <Globe2 size={23} />
              <span>
                <strong>{t('Tìm ảnh tương tự', 'Find similar images')}</strong>
                <small>
                  {t(
                    'Hiểu ảnh local rồi mở Google Images/Lens khi bạn chọn.',
                    'Local image understanding, with optional Google Images/Lens links.',
                  )}
                </small>
              </span>
              <button className="secondary-button" onClick={() => selectAction('image-search')}>
                {t('Dùng', 'Use')}
              </button>
            </div>
            <div>
              <BookOpen size={23} />
              <span>
                <strong>{t('Bài tập, ôn tập & tài liệu', 'Exercises, review & documents')}</strong>
                <small>
                  {t(
                    'Câu sai, cắm cờ, mục tiêu ngày, RAG, backup dữ liệu.',
                    'Mistakes, flags, daily goals, RAG and backups.',
                  )}
                </small>
              </span>
              <button className="secondary-button" onClick={() => setPanel('study')}>
                {t('Mở', 'Open')}
              </button>
            </div>
            {(['image', 'gif', 'video'] as ChatAction[]).map((action) => (
              <div key={action}>
                <Sparkles size={23} />
                <span>
                  <strong>
                    {action === 'image'
                      ? t('Tạo ảnh local', 'Local image generation')
                      : action === 'gif'
                        ? 'GIF'
                        : t('Video chuỗi ảnh', 'Image-sequence video')}
                  </strong>
                  <small>
                    {t(
                      'Hiển thị trong cuộc trò chuyện hiện tại, không mở ô chat khác.',
                      'Generated directly in your current conversation.',
                    )}
                  </small>
                </span>
                <button className="secondary-button" onClick={() => selectAction(action)}>
                  {t('Dùng', 'Use')}
                </button>
              </div>
            ))}
            {[
              [
                CloudOff,
                'Ollama',
                health
                  ? t(
                      'Backend sẵn sàng. Model được lấy từ Ollama.',
                      'Backend ready. Models are loaded from Ollama.',
                    )
                  : t('Khởi động backend để kết nối.', 'Start the backend to connect.'),
              ],
              [
                BookOpen,
                'Tài liệu & OCR',
                t(
                  'PDF, DOCX, ảnh → thư viện RAG local.',
                  'PDFs, DOCX and images → local RAG library.',
                ),
              ],
              [
                Globe2,
                t('Tìm kiếm web', 'Web search'),
                t(
                  'Chỉ hoạt động khi bạn bật. Có gửi từ khóa ra Internet.',
                  'Only enabled with your choice. Sends queries to the web.',
                ),
              ],
            ].map(([Icon, name, desc]) => {
              const I = Icon as typeof CloudOff;
              return (
                <div key={String(name)}>
                  <I size={23} />
                  <span>
                    <strong>{String(name)}</strong>
                    <small>{String(desc)}</small>
                  </span>
                  {Icon === Globe2 ? (
                    <Toggle
                      label="Web search"
                      value={settings.web}
                      change={(v) => changeSettings({ web: v })}
                    />
                  ) : (
                    <ShieldCheck size={16} />
                  )}
                </div>
              );
            })}
          </div>
          <p className="muted">
            {t(
              'Tris AI được tạo ra và phát triển bởi Nguyễn Hải Hà Ninh, sinh viên CNTT Đại học Thủ Dầu Một.',
              'Tris AI was created and developed by Nguyễn Hải Hà Ninh, an IT student at Thu Dau Mot University.',
            )}
          </p>
        </div>
      )}
      {panel === 'usage' && (
        <div className="modal-body">
          <div className="usage-symbol">
            <CloudOff size={28} />
          </div>
          <h3>{t('Sức mạnh nằm trên máy bạn.', 'The power is on your device.')}</h3>
          <p className="muted">
            {t(
              'Tris dùng Ollama local, không có hạn mức token trả phí của nhà cung cấp. Bộ nhớ ngữ cảnh, RAM và tốc độ máy vẫn có giới hạn.',
              'Tris uses local Ollama without a paid provider token quota. Context length, RAM and device speed still have limits.',
            )}
          </p>
          <div className="usage-facts">
            <span>
              {t('Model đã chọn', 'Selected model')}
              <strong>{settings.model}</strong>
            </span>
            <span>
              {t('Kết nối backend', 'Backend connection')}
              <strong>
                {health ? t('Đang kết nối', 'Connected') : t('Chưa kết nối', 'Offline')}
              </strong>
            </span>
            <span>
              {t('Hội thoại trên trình duyệt', 'Browser conversations')}
              <strong>{chats.filter((c) => c.messages.length && !c.demo).length}</strong>
            </span>
          </div>
        </div>
      )}
      {panel === 'upgrade' && (
        <div className="modal-body">
          <div className="usage-symbol purple">
            <Sparkles size={28} />
          </div>
          <h3>{t('Tris AI, tự do theo cách của bạn.', 'Tris AI, yours to grow.')}</h3>
          <p className="muted">
            {t(
              'Phiên bản local hiện không có gói đăng ký trả phí. Khi cần mạnh hơn, bạn có thể cài model phù hợp hoặc nâng cấp máy. Mục thanh toán sẽ chỉ xuất hiện khi có gói dịch vụ thật.',
              'This local version has no paid subscription. You can install another compatible model or upgrade your hardware. Billing will be introduced only when a real plan is available.',
            )}
          </p>
          <button className="secondary-button" onClick={() => setPanel('usage')}>
            {t('Xem mức sử dụng', 'View usage')}
            <ArrowUpRight size={16} />
          </button>
        </div>
      )}
    </Modal>
  );
}
