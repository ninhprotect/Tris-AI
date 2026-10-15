import { useCallback, useEffect, useRef, useState, type CSSProperties } from 'react';
import {
  ArrowUpRight,
  BookOpen,
  Check,
  ChevronDown,
  ChevronRight,
  CloudOff,
  FileText,
  Laptop,
  MessageCircle,
  Monitor,
  PanelLeft,
  RotateCcw,
  Smartphone,
  Sparkles,
  Tablet,
  Upload,
  X,
} from 'lucide-react';
import { ApiError, loadHealth, loadModels, readSession, request, streamChat, streamCompare } from './api';
import { initialChats, newChat, sampleAnswer } from './data';
import { Sidebar } from './components/Sidebar';
import { Composer } from './components/Composer';
import { ChatScrollArea } from './components/ChatScrollArea';
import { Panels, type Reminder } from './components/Panels';
import { IconButton, Popover, TrisMark } from './components/ui';
import {
  uid,
  type Account,
  type Attachment,
  type Chat,
  type ChatAction,
  type Device,
  type Health,
  type Mode,
  type ModelInfo,
  type Panel,
  type Settings,
} from './types';

function readStored<T>(key: string, fallback: T): T {
  try {
    const v = localStorage.getItem(key);
    return v ? JSON.parse(v) : fallback;
  } catch {
    return fallback;
  }
}
const prefix = 'tris.workspace.v1.';
const defaults: Settings = {
  lang: 'vi',
  theme: 'dark',
  device: 'auto',
  collapsed: false,
  model: 'english-tutor-local:4b',
  web: false,
  compareWith: '',
};
const devices: {
  id: Device;
  label: string;
  width: number;
  height: number;
  icon: typeof Monitor;
}[] = [
  { id: 'desktop', label: 'Desktop', width: 1440, height: 900, icon: Monitor },
  { id: 'laptop', label: 'Laptop', width: 1024, height: 768, icon: Laptop },
  { id: 'tablet', label: 'Tablet', width: 768, height: 1024, icon: Tablet },
  { id: 'mobile', label: 'Mobile', width: 390, height: 844, icon: Smartphone },
];
function storeKey(account: Account | null) {
  return prefix + 'chats.' + (account?.account_id || 'guest');
}
function loadChats(account: Account | null) {
  const data = readStored<Chat[]>(storeKey(account), []);
  return Array.isArray(data) &&
    data.length &&
    data.every(
      (c) =>
        c && typeof c.id === 'string' && Array.isArray(c.messages) && typeof c.draft === 'string',
    )
    ? data.map((c) => ({
        ...c,
        // Queued flags are session-live only; after a reload nothing is queued.
        messages: c.messages.map((m) => (m.queued ? { ...m, queued: false } : m)),
      }))
    : [newChat()];
}

type PendingSend = {
  chatId: string;
  text: string;
  files: Attachment[];
  assistantId: string;
  mediaMode?: 'image' | 'gif' | 'video';
  compare?: { a: string; b: string };
};
type TaskKind = 'chat' | 'image' | 'gif' | 'video';
export const modelLabel = (name: string) =>
  name.replace('english-tutor-local:', 'Tris ').replace(':latest', '');

export function App() {
  const [settings, setSettings] = useState<Settings>(() => {
    const s = { ...defaults, ...readStored<Partial<Settings>>(prefix + 'settings', {}) };
    if (!['auto', 'desktop', 'laptop', 'tablet', 'mobile'].includes(s.device)) s.device = 'auto';
    return s;
  });
  const [account, setAccount] = useState<Account | null>(() => readSession()?.account || null);
  const [chats, setChats] = useState<Chat[]>(() => loadChats(readSession()?.account || null));
  const [activeId, setActiveId] = useState(chats[0].id);
  const [projects, setProjects] = useState<string[]>(() =>
    readStored(prefix + 'projects', ['Tiếng Anh mỗi ngày', 'Tủ sách của tôi']),
  );
  const [reminders, setReminders] = useState<Reminder[]>(() =>
    readStored(prefix + 'reminders', []),
  );
  const [drawer, setDrawer] = useState(false);
  const [deviceMenu, setDeviceMenu] = useState(false);
  const [panel, setPanel] = useState<Panel>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [replyLanguage, setReplyLanguage] = useState<'vi' | 'en'>('vi');
  const [toast, setToast] = useState('');
  const [busyId, setBusyId] = useState<string | null>(null);
  const [pending, setPending] = useState<PendingSend[]>([]);
  const [runningKind, setRunningKind] = useState<TaskKind | null>(null);
  const [uploads, setUploads] = useState<Record<string, Attachment[]>>({});
  const [dragging, setDragging] = useState(false);
  const [frameSize, setFrameSize] = useState({
    width: window.innerWidth,
    height: window.innerHeight,
  });
  const frame = useRef<HTMLDivElement>(null);
  const controller = useRef<AbortController | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const dragDepth = useRef(0);
  const busyRef = useRef(false);
  const pendingRef = useRef<PendingSend[]>([]);
  const chatsRef = useRef(chats);
  const storageAccount = useRef(account);
  chatsRef.current = chats;
  useEffect(() => {
    if (frameSize.width >= 1024) setDrawer(false);
  }, [frameSize.width]);
  const active = chats.find((c) => c.id === activeId) || chats[0];
  const files = uploads[active.id] || [];
  const t = useCallback(
    (vi: string, en: string) => (settings.lang === 'vi' ? vi : en),
    [settings.lang],
  );
  const notify = useCallback((value: string) => {
    setToast(value);
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(''), 5000);
  }, []);
  useEffect(() => {
    const tab = crypto.randomUUID();
    const heartbeat = () =>
      fetch('/v1/workspace/presence', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tab }),
      }).catch(() => {});
    const closed = () =>
      navigator.sendBeacon(
        '/v1/workspace/presence',
        new Blob([JSON.stringify({ tab, closed: true })], { type: 'application/json' }),
      );
    void heartbeat();
    const timer = setInterval(heartbeat, 25000);
    window.addEventListener('pagehide', closed);
    window.addEventListener('pageshow', heartbeat);
    return () => {
      clearInterval(timer);
      closed();
      window.removeEventListener('pagehide', closed);
      window.removeEventListener('pageshow', heartbeat);
    };
  }, []);
  useEffect(() => {
    if (!health || (health.auth_required && !account)) return;
    let cancelled = false;
    request<{ chats: Chat[]; settings?: { language: 'vi' | 'en' } }>('/v1/workspace/session')
      .then((data) => {
        if (!cancelled) {
          setChats((list) => [
            ...list,
            ...data.chats.filter((c) => !list.some((local) => local.id === c.id)),
          ]);
          if (data.settings) setReplyLanguage(data.settings.language);
        }
      })
      .catch((error) => {
        if (!cancelled && error instanceof ApiError && error.status === 401) {
          sessionStorage.removeItem('tris.workspace.session');
          storageAccount.current = null;
          setAccount(null);
          const guest = loadChats(null);
          setChats(guest);
          setActiveId(guest[0].id);
          notify('Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.');
        }
      });
    return () => {
      cancelled = true;
    };
  }, [account?.account_id, health?.status, health?.auth_required, panel, notify]);
  const changeSettings = (value: Partial<Settings>) => setSettings((s) => ({ ...s, ...value }));
  const update = useCallback(
    (id: string, value: Partial<Chat>) =>
      setChats((list) => list.map((c) => (c.id === id ? { ...c, ...value } : c))),
    [],
  );
  const appendDraft = useCallback((id: string, spokenText: string) => {
    const text = spokenText.trim();
    if (!text) return;
    setChats((list) =>
      list.map((chat) =>
        chat.id === id
          ? {
              ...chat,
              draft: [chat.draft.trimEnd(), text].filter(Boolean).join(' ').slice(0, 4000),
            }
          : chat,
      ),
    );
  }, []);
  const updateActive = (value: Partial<Chat>) => update(active.id, value);
  const create = (project = '') => {
    const c = newChat(active.demo, project);
    setChats((list) => [c, ...list]);
    setActiveId(c.id);
    setDrawer(false);
  };
  useEffect(() => {
    localStorage.setItem(prefix + 'settings', JSON.stringify(settings));
    document.documentElement.lang = settings.lang;
    const media = matchMedia('(prefers-color-scheme: dark)');
    const apply = () =>
      (document.documentElement.dataset.theme =
        settings.theme === 'system' ? (media.matches ? 'dark' : 'light') : settings.theme);
    apply();
    media.addEventListener('change', apply);
    return () => media.removeEventListener('change', apply);
  }, [settings]);
  useEffect(() => {
    const persist = () => {
      try {
        localStorage.setItem(
          storeKey(storageAccount.current),
          JSON.stringify(
            chats.map((c) => ({
              ...c,
              messages: c.messages.map((m) => ({
                ...m,
                attachments: m.attachments?.map(({ file, preview, ...a }) => a),
              })),
            })),
          ),
        );
      } catch {
        notify(
          t(
            'Bộ nhớ trình duyệt đầy. Bạn có thể xuất bản sao trong Cài đặt.',
            'Browser storage is full. Export a backup from Settings.',
          ),
        );
      }
    };
    const id = setTimeout(persist, 350);
    window.addEventListener('pagehide', persist);
    return () => {
      clearTimeout(id);
      window.removeEventListener('pagehide', persist);
    };
  }, [chats, notify, t]);
  useEffect(() => {
    localStorage.setItem(prefix + 'projects', JSON.stringify(projects));
  }, [projects]);
  useEffect(() => {
    localStorage.setItem(prefix + 'reminders', JSON.stringify(reminders));
    const timer = setInterval(() => {
      const due = reminders.filter((r) => !r.done && new Date(r.at).getTime() <= Date.now());
      if (due.length) {
        notify(t('Đến giờ học: ', 'Study time: ') + due.map((r) => r.title).join(', '));
        setReminders((items) =>
          items.map((r) => (due.some((d) => d.id === r.id) ? { ...r, done: true } : r)),
        );
      }
    }, 15000);
    return () => clearInterval(timer);
  }, [reminders, notify, t]);
  useEffect(() => {
    if (!frame.current) return;
    const observer = new ResizeObserver((entries) => {
      const r = entries[0].contentRect;
      setFrameSize({ width: Math.round(r.width), height: Math.round(r.height) });
    });
    observer.observe(frame.current);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    const viewport = window.visualViewport;
    const resize = () =>
      document.documentElement.style.setProperty(
        '--available-height',
        `${viewport?.height || window.innerHeight}px`,
      );
    resize();
    viewport?.addEventListener('resize', resize);
    return () => viewport?.removeEventListener('resize', resize);
  }, []);
  useEffect(() => {
    let cancelled = false;
    const refresh = async () => {
      const results = await Promise.allSettled([loadHealth(), loadModels()]);
      if (cancelled) return;
      setHealth(results[0].status === 'fulfilled' ? results[0].value : null);
      if (results[1].status === 'fulfilled') {
        const value = results[1].value;
        setModels(value.models);
        if (value.models.length)
          setSettings((s) => ({
            ...s,
            model: value.models.some((m) => m.name === s.model) ? s.model : value.default,
          }));
      }
    };
    void refresh();
    const timer = setInterval(refresh, 30000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);
  useEffect(() => {
    const listener = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && ['k', ',', 'n'].includes(event.key.toLowerCase())) {
        event.preventDefault();
        if (event.key.toLowerCase() === 'k') setPanel('search');
        else if (event.key === ',') setPanel('settings');
        else create();
      }
      if (event.key === 'Escape') setDrawer(false);
    };
    document.addEventListener('keydown', listener);
    return () => document.removeEventListener('keydown', listener);
  });
  useEffect(() => {
    const query = new URLSearchParams(location.search);
    const code = query.get('oauth_code');
    if (code) {
      history.replaceState(null, '', location.pathname);
      request<{ access_token: string; account: Account }>('/v1/workspace/oauth/exchange', {
        method: 'POST',
        body: JSON.stringify({ code }),
      })
        .then((r) => login(r.access_token, r.account))
        .catch((e) => notify(e.message));
    }
    if (query.has('oauth_error')) {
      history.replaceState(null, '', location.pathname);
      notify(
        t(
          'Đăng nhập Google chưa hoàn tất. Hãy thử lại.',
          'Google sign-in was not completed. Try again.',
        ),
      );
    }
  }, []);
  function login(token: string, user: Account) {
    controller.current?.abort();
    sessionStorage.setItem('tris.workspace.session', JSON.stringify({ token, account: user }));
    storageAccount.current = user;
    setAccount(user);
    const next = loadChats(user);
    setChats(next);
    setActiveId(next[0].id);
    setUploads({});
    notify(t('Đã đăng nhập. Chào bạn!', 'Signed in. Welcome!'));
  }
  async function logout() {
    controller.current?.abort();
    try {
      await request('/v1/auth/logout', { method: 'POST' });
    } catch {
      /* local logout remains available offline */
    }
    sessionStorage.removeItem('tris.workspace.session');
    storageAccount.current = null;
    setAccount(null);
    const guest = loadChats(null);
    setChats(guest);
    setActiveId(guest[0].id);
    setUploads({});
    notify(t('Đã đăng xuất trên trình duyệt này.', 'Signed out on this browser.'));
  }
  function addFiles(incoming: File[]) {
    // Attaching stays available while a task runs: queued sends carry their
    // own files and upload them only when their turn arrives.
    const added: Attachment[] = [];
    let total = files.reduce((n, f) => n + f.size, 0);
    for (const file of incoming) {
      const extension = file.name.split('.').pop()?.toLowerCase() || '';
      const image = ['png', 'jpg', 'jpeg', 'webp'].includes(extension);
      const video = ['mp4', 'mov', 'webm', 'mkv'].includes(extension);
      const doc = ['pdf', 'txt', 'md', 'docx'].includes(extension);
      const limit = (image ? 10 : video ? 150 : 20) * 1024 * 1024;
      if (!image && !video && !doc) {
        notify(
          t(`Định dạng .${extension} chưa được hỗ trợ.`, `.${extension} files are not supported.`),
        );
        continue;
      }
      if (
        files.length + added.length >= 5 ||
        total + file.size > 180 * 1024 * 1024 ||
        file.size > limit
      ) {
        notify(
          t(
            'Vượt giới hạn tệp: tối đa 5 tệp, 180 MB/lượt; ảnh 10 MB, tài liệu 20 MB, video 150 MB.',
            'Upload limit: 5 files, 180 MB total; images 10 MB, documents 20 MB, videos 150 MB.',
          ),
        );
        continue;
      }
      added.push({
        id: uid(),
        name: file.name,
        size: file.size,
        type: file.type,
        file,
        ...(image ? { preview: URL.createObjectURL(file) } : {}),
      });
      total += file.size;
    }
    setUploads((u) => ({ ...u, [active.id]: [...files, ...added] }));
  }
  const mediaKindOf = (action: ChatAction | undefined): TaskKind =>
    action === 'image' || action === 'gif' || action === 'video' ? action : 'chat';
  const enqueueAck = (media: boolean) =>
    media
      ? t(
          'Đã nhận yêu cầu mới — Tris sẽ trả lời ngay sau khi nội dung đang tạo hoàn tất. Tác vụ hiện tại không bị ảnh hưởng.',
          'Got it — Tris will reply right after the current creation finishes. The running task stays untouched.',
        )
      : t('Đã xếp hàng — Tris sẽ trả lời ngay sau lượt hiện tại.', 'Queued — Tris replies right after the current turn.');

  function appendTurn(
    chatId: string,
    text: string,
    sentFiles: Attachment[],
    assistantId: string,
    queuedStatus?: string,
    mediaMode?: 'image' | 'gif' | 'video',
  ) {
    setChats((list) =>
      list.map((c) =>
        c.id === chatId
          ? {
              ...c,
              title: c.title || text.slice(0, 48),
              draft: '',
              action: 'auto',
              messages: [
                ...c.messages,
                { id: uid(), role: 'user' as const, content: text, attachments: sentFiles },
                {
                  id: assistantId,
                  role: 'assistant' as const,
                  content: '',
                  ...(queuedStatus ? { status: queuedStatus, queued: true } : {}),
                  ...(mediaMode ? { mediaMode } : {}),
                },
              ],
            }
          : c,
      ),
    );
    setUploads((u) => ({ ...u, [chatId]: [] }));
  }

  function gateSubmit(): boolean {
    if (active.demo) return true;
    if (!health || (health.auth_required && !account)) {
      if (!health)
        notify(
          t(
            'Backend chưa kết nối. Khởi động start_tris_workspace.bat hoặc chọn Trải nghiệm mẫu trong menu Tris AI.',
            'Backend offline. Start start_tris_workspace.bat or choose Sample experience from the Tris AI menu.',
          ),
        );
      else setPanel('login');
      return false;
    }
    return true;
  }

  function submitDraft() {
    const text =
      active.draft.trim() ||
      (files.length
        ? t('Hãy giúp mình tìm hiểu tài liệu đính kèm.', 'Help me understand the attached document.')
        : '');
    if ((!text && !files.length) || !gateSubmit()) return;
    const compareModel = active.demo ? '' : settings.compareWith;
    if (compareModel) {
      if (files.length || active.documentIds?.length) {
        notify(
          t(
            'Đối chiếu model chưa dùng được tài liệu đính kèm. Hãy bỏ tệp hoặc tắt đối chiếu rồi gửi lại.',
            'Cross-check does not use attachments yet. Remove the files or turn it off, then send again.',
          ),
        );
        return;
      }
      if (compareModel === settings.model) {
        notify(
          t(
            'Model đối chiếu đang trùng model chính. Hãy chọn một model khác trong menu model.',
            'The comparison model equals the main model. Pick a different one in the model menu.',
          ),
        );
        return;
      }
      const compareAssistantId = uid();
      const comparePair = { a: settings.model, b: compareModel };
      if (busyRef.current) {
        appendTurn(active.id, text, [], compareAssistantId, enqueueAck(false));
        pendingRef.current = [
          ...pendingRef.current,
          { chatId: active.id, text, files: [], assistantId: compareAssistantId, compare: comparePair },
        ];
        setPending(pendingRef.current);
        return;
      }
      appendTurn(active.id, text, [], compareAssistantId);
      setRunningKind('chat');
      void runCompare(active.id, text, compareAssistantId, comparePair.a, comparePair.b);
      return;
    }
    const mediaMode = mediaKindOf(active.action);
    const actionOverride = mediaMode === 'chat' ? undefined : (mediaMode as 'image' | 'gif' | 'video');
    const assistantId = uid();
    if (busyRef.current) {
      appendTurn(active.id, text, [...files], assistantId, enqueueAck(actionOverride !== undefined), actionOverride);
      pendingRef.current = [
        ...pendingRef.current,
        { chatId: active.id, text, files: [...files], assistantId, mediaMode: actionOverride },
      ];
      setPending(pendingRef.current);
      return;
    }
    appendTurn(active.id, text, [...files], assistantId, undefined, actionOverride);
    setRunningKind(mediaMode);
    void runSend(active.id, text, [...files], assistantId, false, mediaMode, actionOverride);
  }

  function sendQuick(text: string, action?: ChatAction) {
    const trimmed = text.trim();
    if (!trimmed || !gateSubmit()) return;
    const kind = mediaKindOf(action);
    const assistantId = uid();
    if (busyRef.current) {
      appendTurn(active.id, trimmed, [], assistantId, enqueueAck(kind !== 'chat'), kind === 'chat' ? undefined : kind);
      pendingRef.current = [
        ...pendingRef.current,
        {
          chatId: active.id,
          text: trimmed,
          files: [],
          assistantId,
          mediaMode: kind === 'chat' ? undefined : kind,
        },
      ];
      setPending(pendingRef.current);
      return;
    }
    appendTurn(active.id, trimmed, [], assistantId, undefined, kind === 'chat' ? undefined : kind);
    setRunningKind(kind);
    void runSend(active.id, trimmed, [], assistantId, false, kind, action);
  }

  function stop() {
    const running = chatsRef.current.find((c) => c.id === busyId);
    if (running?.messages.at(-1)?.status)
      notify(
        t(
          'Đã dừng chờ kết quả. Tác vụ tạo nội dung đang chạy sẽ tự hoàn tất trước khi nhận tin nhắn mới.',
          'Stopped waiting. The running creation will finish before new messages are processed.',
        ),
      );
    controller.current?.abort();
    if (pendingRef.current.length) {
      const cancelled = pendingRef.current;
      pendingRef.current = [];
      setPending([]);
      setChats((list) =>
        list.map((c) => {
          const mine = cancelled.filter((p) => p.chatId === c.id);
          if (!mine.length) return c;
          return {
            ...c,
            messages: c.messages.map((m) =>
              mine.some((p) => p.assistantId === m.id)
                ? {
                    ...m,
                    queued: false,
                    status: undefined,
                    content: t('Đã dừng trước khi gửi.', 'Stopped before sending.'),
                  }
                : m,
            ),
          };
        }),
      );
    }
  }

  function drainNext() {
    const next = pendingRef.current[0];
    if (!next) return;
    if (next.compare)
      void runCompare(next.chatId, next.text, next.assistantId, next.compare.a, next.compare.b);
    else
      void runSend(next.chatId, next.text, next.files, next.assistantId, true,
        next.mediaMode ? mediaKindOf(next.mediaMode) : 'chat', next.mediaMode);
  }

  async function runCompare(chatId: string, text: string, assistantId: string, modelA: string, modelB: string) {
    busyRef.current = true;
    setBusyId(chatId);
    setRunningKind('chat');
    const abort = new AbortController();
    controller.current = abort;
    const chat = chatsRef.current.find((c) => c.id === chatId);
    const patchMessage = (patch: Partial<Chat['messages'][number]>) =>
      setChats((list) =>
        list.map((c) =>
          c.id === chatId
            ? {
                ...c,
                messages: c.messages.map((m) => (m.id === assistantId ? { ...m, ...patch } : m)),
              }
            : c,
        ),
      );
    patchMessage({ queued: false });
    if (!chat) {
      patchMessage({
        content: t('Cuộc trò chuyện không còn tồn tại.', 'This conversation no longer exists.'),
        status: undefined,
        error: true,
      });
      busyRef.current = false;
      setBusyId(null);
      controller.current = null;
      return;
    }
    try {
      const live = {
        modelA: modelLabel(modelA),
        modelB: modelLabel(modelB),
        a: '',
        b: '',
        judge: '',
      };
      patchMessage({ compare: live });
      await streamCompare(
        text,
        modelA,
        modelB,
        chat.mode,
        chat.scenario || 'Coffee Shop',
        replyLanguage,
        chat.messages
          .slice(0, -1)
          .filter((m) => !m.error)
          .slice(-12)
          .map((m) => ({ role: m.role, content: m.content.slice(0, 8000) })),
        abort.signal,
        (event) => {
          if (event.error) throw new Error(event.error);
          if (event.status) patchMessage({ status: event.status });
          if (event.delta && event.which) {
            const side = event.which === 'a' ? 'a' : 'b';
            live[side] += event.delta;
            patchMessage({ compare: { ...live } });
          }
          if (event.judge) {
            live.judge += event.judge;
            patchMessage({ compare: { ...live } });
          }
          if (event.done && !event.which) {
            patchMessage({
              content:
                `### ${live.modelA}\n\n${live.a}\n\n### ${live.modelB}\n\n${live.b}` +
                `\n\n### ${t('Kết luận đối chiếu', 'Cross-check verdict')}\n\n${live.judge}`,
              compare: undefined,
              status: undefined,
              seconds: event.seconds,
            });
          }
        },
      );
    } catch (e) {
      if (!abort.signal.aborted) {
        patchMessage({
          content:
            e instanceof Error
              ? e.message
              : t('Có lỗi kết nối. Vui lòng thử lại.', 'Connection error. Please retry.'),
          status: undefined,
          error: true,
          compare: undefined,
        });
        if (e instanceof ApiError && e.status === 401) setPanel('login');
      }
    } finally {
      if (abort.signal.aborted)
        setChats((list) =>
          list.map((c) =>
            c.id === chatId
              ? {
                  ...c,
                  messages: c.messages.map((m) =>
                    m.id === assistantId && !m.content
                      ? { ...m, content: t('Đã dừng đối chiếu.', 'Cross-check stopped.'), status: undefined }
                      : m,
                  ),
                }
              : c,
          ),
        );
      pendingRef.current = pendingRef.current.filter((p) => p.assistantId !== assistantId);
      setPending(pendingRef.current);
      busyRef.current = false;
      setBusyId(null);
      controller.current = null;
      drainNext();
    }
  }

  async function runSend(
    chatId: string,
    text: string,
    sentFiles: Attachment[],
    assistantId: string,
    followUp: boolean,
    kind: TaskKind,
    actionOverride: ChatAction | undefined,
  ) {
    busyRef.current = true;
    setBusyId(chatId);
    setRunningKind(kind);
    const abort = new AbortController();
    controller.current = abort;
    const chat = chatsRef.current.find((c) => c.id === chatId);
    const started = performance.now();
    const patchMessage = (patch: Partial<Chat['messages'][number]>) =>
      setChats((list) =>
        list.map((c) =>
          c.id === chatId
            ? {
                ...c,
                messages: c.messages.map((m) => (m.id === assistantId ? { ...m, ...patch } : m)),
              }
            : c,
        ),
      );
    patchMessage({ queued: false });
    if (!chat) {
      patchMessage({
        content: t('Cuộc trò chuyện không còn tồn tại.', 'This conversation no longer exists.'),
        status: undefined,
        error: true,
      });
      busyRef.current = false;
      setBusyId(null);
      controller.current = null;
      return;
    }
    try {
      let content = '';
      if (chat?.demo) {
        const result = sampleAnswer(settings.lang);
        const parts = result.match(/.{1,14}/gs) || [];
        for (const part of parts) {
          if (abort.signal.aborted) break;
          content += part;
          patchMessage({ content });
          await new Promise((r) => setTimeout(r, 25));
        }
        patchMessage({ seconds: Math.round((performance.now() - started) / 1000) });
      } else {
        for (const attachment of sentFiles) {
          if (abort.signal.aborted) throw new DOMException('Aborted', 'AbortError');
          const data = new FormData();
          data.set('file', attachment.file!);
          data.set('question', text);
          data.set('image_mode', chat?.imageMode || 'vision');
          const result = await request<{
            document_id?: number;
            stored_only?: boolean;
            vision_context?: string;
          }>('/v1/workspace/attachments', { method: 'POST', body: data, signal: abort.signal });
          attachment.documentId = result.document_id;
          attachment.visionContext = result.vision_context;
          if (result.stored_only)
            notify(
              t(
                'Video đã lưu local; chưa tự động phiên âm.',
                'Video saved locally; transcription is not available.',
              ),
            );
        }
        await streamChat(
          {
            ...chat,
            messages: (chat.messages || [])
              .slice(0, -1)
              .concat({
                ...(chat.messages.at(-1) || { id: assistantId, role: 'assistant', content: '' }),
                attachments: sentFiles,
              }),
          },
          text,
          settings.model,
          replyLanguage,
          settings.web,
          abort.signal,
          (event) => {
            if (event.error) throw new Error(event.error);
            if (event.delta) {
              content += event.delta;
              patchMessage({ content, status: undefined });
            }
            if (event.status) patchMessage({ status: event.status });
            if (event.done) patchMessage({ seconds: event.seconds, sources: event.sources });
          },
          followUp,
          actionOverride,
        );
      }
    } catch (e) {
      if (!abort.signal.aborted) {
        patchMessage({
          content:
            e instanceof Error
              ? e.message
              : t('Có lỗi kết nối. Vui lòng thử lại.', 'Connection error. Please retry.'),
          status: undefined,
          error: true,
        });
        if (e instanceof ApiError && e.status === 401) setPanel('login');
      }
    } finally {
      if (abort.signal.aborted)
        setChats((list) =>
          list.map((c) =>
            c.id === chatId
              ? {
                  ...c,
                  messages: c.messages.map((m) =>
                    m.id === assistantId && !m.content
                      ? { ...m, content: t('Đã dừng phản hồi.', 'Response stopped.'), status: undefined }
                      : m,
                  ),
                }
              : c,
          ),
        );
      sentFiles.forEach((f) => {
        if (f.preview) URL.revokeObjectURL(f.preview);
      });
      pendingRef.current = pendingRef.current.filter((p) => p.assistantId !== assistantId);
      setPending(pendingRef.current);
      busyRef.current = false;
      setBusyId(null);
      controller.current = null;
      drainNext();
    }
  }
  const selectedDevice = devices.find((d) => d.id === settings.device);
  const frameStyle = selectedDevice
    ? ({
        '--preview-width': `${selectedDevice.width}px`,
        '--preview-height': `${selectedDevice.height}px`,
      } as CSSProperties)
    : undefined;
  const layout = frameSize.width < 768 ? 'mobile' : frameSize.width < 1024 ? 'tablet' : 'desktop';
  const busyHere = busyId === active.id;
  const runningChat = chats.find((c) => c.id === busyId);
  const runningUserText =
    runningChat?.messages.filter((m) => m.role === 'user').at(-1)?.content || '';
  const mediaNoun = (kind: TaskKind) =>
    settings.lang === 'vi'
      ? kind === 'gif'
        ? 'gif'
        : kind === 'video'
          ? 'video'
          : 'ảnh'
      : kind;
  const recreatePrompt = (modifier: string) =>
    settings.lang === 'vi'
      ? `tạo lại ${mediaNoun(runningKind || 'image')} từ mô tả cũ: ${runningUserText} — ${modifier}`
      : `recreate the ${mediaNoun(runningKind || 'image')} from "${runningUserText}" with ${modifier}`;
  const busyVariantPrompt = (modifier: string) =>
    settings.lang === 'vi'
      ? `tạo thêm ${mediaNoun(runningKind || 'image')} với ${modifier}, dùng lại mô tả: ${runningUserText}`
      : `create another ${mediaNoun(runningKind || 'image')} with ${modifier}, reusing the description: ${runningUserText}`;
  const quickReplies = busyHere
    ? runningKind && runningKind !== 'chat'
      ? [
          {
            label: t('Sáng màu hơn', 'Brighter colors'),
            run: () =>
              sendQuick(
                busyVariantPrompt(t('màu sắc sáng và tươi hơn', 'brighter, more vivid colors')),
                runningKind,
              ),
          },
          {
            label: t('Tông điện ảnh', 'Cinematic tones'),
            run: () =>
              sendQuick(
                busyVariantPrompt(t('tông màu điện ảnh, tương phản nhẹ', 'cinematic tones, soft contrast')),
                runningKind,
              ),
          },
          {
            label: t('Thêm chi tiết nền', 'Richer background'),
            run: () =>
              sendQuick(
                busyVariantPrompt(t('phông nền có thêm chi tiết', 'a more detailed background')),
                runningKind,
              ),
          },
        ]
      : [
          {
            label: t('Ngắn gọn hơn', 'Keep it shorter'),
            run: () =>
              sendQuick(
                t('Rút gọn câu trả lời vừa rồi giúp mình.', 'Condense your previous answer for me.'),
              ),
          },
          {
            label: t('Cho ví dụ', 'Give an example'),
            run: () =>
              sendQuick(t('Cho mình một ví dụ cụ thể nhé.', 'Give me a concrete example.')),
          },
          {
            label: t('Dễ hiểu hơn', 'Explain simply'),
            run: () =>
              sendQuick(
                t('Giải thích lại bằng từ ngữ dễ hiểu hơn giúp mình.', 'Explain that again in simpler words.'),
              ),
          },
        ]
    : undefined;
  const lastMessage = active.messages.at(-1);
  const lastUserText = [...active.messages].reverse().find((m) => m.role === 'user')?.content || '';
  const lastMedia =
    lastMessage && lastMessage.role === 'assistant' && lastMessage.mediaMode && lastMessage.content && !lastMessage.error
      ? lastMessage
      : null;
  const completionActions =
    !busyId && lastMedia
      ? [
          {
            label: t('Tạo biến thể', 'Create a variation'),
            run: () => sendQuick(lastUserText, lastMedia.mediaMode),
          },
          {
            label: t('Sáng màu hơn', 'Brighter colors'),
            run: () =>
              sendQuick(
                settings.lang === 'vi'
                  ? `tạo lại ${mediaNoun(lastMedia.mediaMode!)} từ mô tả cũ: ${lastUserText} — màu sắc sáng và tươi hơn`
                  : `recreate the ${mediaNoun(lastMedia.mediaMode!)} from "${lastUserText}" with brighter, more vivid colors`,
                lastMedia.mediaMode,
              ),
          },
          {
            label: t('Chỉnh mô tả', 'Edit description'),
            run: () => {
              updateActive({ draft: lastUserText.slice(0, 4000) });
              setTimeout(
                () =>
                  document
                    .querySelector<HTMLTextAreaElement>('.composer-card textarea')
                    ?.focus(),
                0,
              );
            },
          },
        ]
      : undefined;
  return (
    <div className={`preview-stage ${selectedDevice ? 'preview-active' : ''}`}>
      <div
        ref={frame}
        className="app-frame"
        style={frameStyle}
        data-layout={layout}
        data-device={settings.device}
      >
        <Sidebar
          chats={chats}
          active={active}
          select={setActiveId}
          create={create}
          collapsed={settings.collapsed}
          toggle={() => changeSettings({ collapsed: !settings.collapsed })}
          drawer={drawer}
          closeDrawer={() => setDrawer(false)}
          projects={projects}
          addProject={(name) => {
            if (!projects.includes(name)) setProjects((p) => [...p, name]);
          }}
          lang={settings.lang}
          account={account}
          panel={setPanel}
          notify={notify}
          logout={logout}
          setDemo={(v) => {
            if (v)
              setChats((list) =>
                list.some((c) => c.demo) ? list : [...list, ...initialChats().slice(1)],
              );
            if (active.messages.length) {
              const c = newChat(v);
              setChats((list) => [c, ...list]);
              setActiveId(c.id);
            } else updateActive({ demo: v });
          }}
          deviceMenu={() => setDeviceMenu(true)}
          backend={!!health}
        />
        <main
          className="canvas"
          inert={drawer}
          onDragEnter={(e) => {
            if (e.dataTransfer.types.includes('Files')) {
              e.preventDefault();
              dragDepth.current++;
              setDragging(true);
            }
          }}
          onDragOver={(e) => {
            if (e.dataTransfer.types.includes('Files')) e.preventDefault();
          }}
          onDragLeave={() => {
            dragDepth.current = Math.max(0, dragDepth.current - 1);
            if (!dragDepth.current) setDragging(false);
          }}
          onDrop={(e) => {
            e.preventDefault();
            dragDepth.current = 0;
            setDragging(false);
            addFiles(Array.from(e.dataTransfer.files));
          }}
        >
          <header className="canvas-header">
            <div className="canvas-title">
              <IconButton
                className="mobile-menu"
                label={t('Mở thanh bên', 'Open sidebar')}
                onClick={() => setDrawer(true)}
              >
                <PanelLeft size={19} />
              </IconButton>
              <span className="breadcrumb-label">
                {active.project || t('Không gian của bạn', 'Your workspace')}
              </span>
              <ChevronRight size={12} className="breadcrumb-arrow" />
              <span className="breadcrumb-current">
                {active.messages.length
                  ? active.title
                  : t('Cuộc trò chuyện mới', 'New conversation')}
              </span>
            </div>
            <div className="canvas-header-actions">
              <IconButton
                label={t('Mở Tris Companion', 'Open Tris Companion')}
                className="companion-open"
                onClick={() => {
                  const token = readSession()?.token || '';
                  window.open('/companion/' + (token ? '#t=' + encodeURIComponent(token) : ''), '_blank');
                }}
              >
                <Sparkles size={18} />
              </IconButton>
              {active.demo ? (
                <span className="demo-badge">{t('Chế độ mẫu', 'Sample mode')}</span>
              ) : (
                <span className="local-indicator">
                  <CloudOff size={13} />
                  <span>Local</span>
                </span>
              )}
              <div className="device-anchor">
                <IconButton
                  label={t('Hiển thị thiết bị', 'Device preview')}
                  className={deviceMenu || selectedDevice ? 'device-active' : ''}
                  onClick={() => setDeviceMenu(!deviceMenu)}
                  aria-expanded={deviceMenu}
                >
                  <Monitor size={18} />
                </IconButton>
                {deviceMenu && (
                  <Popover
                    label={t('Hiển thị thiết bị', 'Device preview')}
                    close={() => setDeviceMenu(false)}
                    className="device-popover"
                  >
                    <div className="device-heading">
                      <strong>{t('Xem trên thiết bị', 'Device preview')}</strong>
                      <span data-testid="viewport-size">
                        {frameSize.width} × {frameSize.height}
                      </span>
                    </div>
                    {devices.map((d) => (
                      <button
                        key={d.id}
                        className={`menu-row ${settings.device === d.id ? 'selected' : ''}`}
                        onClick={() => {
                          changeSettings({ device: d.id });
                          setDeviceMenu(false);
                          setDrawer(false);
                        }}
                      >
                        <d.icon size={17} />
                        <span>{d.label}</span>
                        <small>
                          {d.width} × {d.height}
                        </small>
                        {settings.device === d.id && <Check size={14} />}
                      </button>
                    ))}
                    <div className="menu-separator" />
                    <button
                      className="menu-row"
                      onClick={() => {
                        changeSettings({ device: 'auto' });
                        setDeviceMenu(false);
                      }}
                    >
                      <RotateCcw size={16} />
                      <span>{t('Tự động / Đặt lại', 'Auto / Reset')}</span>
                      {settings.device === 'auto' && <Check size={14} />}
                    </button>
                  </Popover>
                )}
              </div>
            </div>
          </header>
          {active.messages.length ? (
            <ChatScrollArea
              chat={active}
              busy={busyHere}
              lang={settings.lang}
              notify={notify}
              quickReplies={quickReplies}
              completionActions={completionActions}
            />
          ) : (
            <section className="empty-state">
              <div className="empty-inner">
                <div className="hero-mark">
                  <TrisMark />
                  <span className="hero-spark" />
                </div>
                <p className="hero-eyebrow">
                  {t('MỘT NGÀY MỚI, MỘT ĐIỀU HAY', 'A NEW DAY, A NEW DISCOVERY')}
                </p>
                <h1>{t('Hôm nay, mình học gì nhỉ?', 'What shall we learn today?')}</h1>
                <p className="hero-subtitle">
                  {t(
                    'Cứ tò mò. Tris luôn ở đây cùng bạn.',
                    'Stay curious. Tris is right here with you.',
                  )}
                </p>
                <div className="suggestion-grid">
                  {[
                    {
                      icon: MessageCircle,
                      color: 'blue',
                      label: t('Bắt đầu một\ncuộc trò chuyện', 'Start a\nconversation'),
                      sub: t('Luyện nói thật tự nhiên', 'Find your natural voice'),
                      prompt: t(
                        'Cùng mình luyện hội thoại tiếng Anh về ngày hôm nay nhé.',
                        'Let’s practice an English conversation about today.',
                      ),
                      mode: 'Conversation',
                    },
                    {
                      icon: Sparkles,
                      color: 'purple',
                      label: t('Hiểu thêm một\nđiều mới', 'Make room for\na new discovery'),
                      sub: t('Ngữ pháp, theo cách dễ hiểu', 'Grammar made simple'),
                      prompt: t(
                        'Giải thích thì hiện tại hoàn thành bằng ví dụ dễ hiểu.',
                        'Explain the present perfect with simple examples.',
                      ),
                      mode: 'Grammar',
                    },
                    {
                      icon: BookOpen,
                      color: 'teal',
                      label: t('Mở rộng vốn từ\ncủa mình', 'Grow your\nvocabulary'),
                      sub: t('Từng từ nhỏ, mỗi ngày', 'A few new words each day'),
                      prompt: t(
                        'Dạy mình từ curiosity và cách dùng trong một câu.',
                        'Teach me the word curiosity and how to use it.',
                      ),
                      mode: 'Vocabulary',
                    },
                    {
                      icon: FileText,
                      color: 'peach',
                      label: t('Khám phá từ\ntài liệu của bạn', 'Explore your\nown documents'),
                      sub: t('Đọc, hiểu và kết nối ý tưởng', 'Read, understand, connect'),
                      prompt: t(
                        'Mình muốn cùng bạn tìm hiểu tài liệu. Mình sẽ đính kèm ngay.',
                        'I’d like to explore a document with you. I’ll attach it now.',
                      ),
                      mode: 'Conversation',
                    },
                  ].map((card, i) => (
                    <button
                      className={`suggestion-card ${card.color}`}
                      key={i}
                      onClick={() => {
                        updateActive({ draft: card.prompt, mode: card.mode as Mode });
                        frame.current?.querySelector<HTMLTextAreaElement>('textarea')?.focus();
                      }}
                    >
                      <card.icon size={20} strokeWidth={1.6} />
                      <strong>{card.label}</strong>
                      <small>{card.sub}</small>
                      <ArrowUpRight className="suggestion-arrow" size={15} />
                    </button>
                  ))}
                </div>
              </div>
            </section>
          )}
          <Composer
            chat={active}
            update={updateActive}
            appendDraft={appendDraft}
            send={submitDraft}
            busy={!!busyId}
            queuedCount={pending.length}
            stop={stop}
            lang={settings.lang}
            model={settings.model}
            models={models}
            setModel={(model) => changeSettings({ model })}
            projects={projects}
            files={files}
            addFiles={addFiles}
            removeFile={(id) => {
              const f = files.find((f) => f.id === id);
              if (f?.preview) URL.revokeObjectURL(f.preview);
              setUploads((u) => ({ ...u, [active.id]: files.filter((f) => f.id !== id) }));
            }}
            web={settings.web}
            setWeb={(web) => changeSettings({ web })}
            compareWith={settings.compareWith}
            setCompareWith={(compareWith) => changeSettings({ compareWith })}
            notify={notify}
          />
          {dragging && (
            <div className="drop-overlay">
              <Upload size={36} />
              <h2>{t('Thả một ý tưởng vào đây', 'Drop an idea here')}</h2>
              <p>PDF, DOCX, TXT, PNG, JPG, MP4…</p>
              <small>{t('Tối đa 5 tệp · 180 MB/lượt', 'Up to 5 files · 180 MB total')}</small>
            </div>
          )}
        </main>
        {toast && (
          <div className="toast" role="status">
            <span>{toast}</span>
            <IconButton
              label={t('Đóng thông báo', 'Dismiss notification')}
              onClick={() => setToast('')}
            >
              <X size={15} />
            </IconButton>
          </div>
        )}
        {panel && (
          <Panels
            selectAction={(action) => {
              updateActive({
                action,
                demo: false,
                ...(action === 'image-search' ? { imageMode: 'vision' as const } : {}),
              });
              setPanel(null);
              setTimeout(
                () =>
                  document.querySelector<HTMLTextAreaElement>('.composer-card textarea')?.focus(),
                0,
              );
            }}
            useDocuments={(ids) => {
              updateActive({
                documentIds: ids,
                demo: false,
                draft: t(
                  'Hãy giúp mình tìm hiểu tài liệu đã chọn.',
                  'Help me understand the selected documents.',
                ),
              });
            }}
            key={panel}
            panel={panel}
            close={() => setPanel(null)}
            lang={settings.lang}
            settings={settings}
            changeSettings={changeSettings}
            health={health}
            account={account}
            onLogin={login}
            setPanel={setPanel}
            notify={notify}
            usePrompt={(draft) => updateActive({ draft })}
            chats={chats}
            selectChat={setActiveId}
            reminders={reminders}
            setReminders={setReminders}
          />
        )}
      </div>
    </div>
  );
}
