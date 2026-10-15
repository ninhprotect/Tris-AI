import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import {
  Plus,
  ArrowUp,
  Square,
  Mic,
  ChevronDown,
  Folder,
  Globe2,
  GitCompareArrows,
  ShieldCheck,
  FileText,
  Image,
  Video,
  Check,
  X,
  Loader2,
} from 'lucide-react';
import { modeLabel } from '../data';
import { ApiError, transcribeAudio } from '../api';
import type { Attachment, Chat, ChatAction, Lang, Mode, ModelInfo } from '../types';
import { IconButton, Popover } from './ui';

type VoiceState = 'idle' | 'requesting' | 'recording' | 'transcribing';

const MAX_RECORDING_SECONDS = 60;

function clock(seconds: number) {
  return `${Math.floor(seconds / 60)
    .toString()
    .padStart(2, '0')}:${Math.floor(seconds % 60)
    .toString()
    .padStart(2, '0')}`;
}

export function Composer({
  chat,
  update,
  appendDraft,
  send,
  busy,
  queuedCount,
  stop,
  lang,
  model,
  models,
  setModel,
  projects,
  files,
  addFiles,
  removeFile,
  web,
  setWeb,
  compareWith,
  setCompareWith,
  notify,
}: {
  chat: Chat;
  update: (patch: Partial<Chat>) => void;
  appendDraft: (chatId: string, text: string) => void;
  send: () => void;
  busy: boolean;
  queuedCount: number;
  stop: () => void;
  lang: Lang;
  model: string;
  models: ModelInfo[];
  setModel: (v: string) => void;
  projects: string[];
  files: Attachment[];
  addFiles: (files: File[]) => void;
  removeFile: (id: string) => void;
  web: boolean;
  setWeb: (v: boolean) => void;
  compareWith: string;
  setCompareWith: (v: string) => void;
  notify: (v: string) => void;
}) {
  const [menu, setMenu] = useState<string | null>(null);
  const [voiceState, setVoiceState] = useState<VoiceState>('idle');
  const [voiceLevel, setVoiceLevel] = useState(0);
  const [voiceSeconds, setVoiceSeconds] = useState(0);
  const [microphoneName, setMicrophoneName] = useState('');
  const [heardAudio, setHeardAudio] = useState(false);
  const [meterReady, setMeterReady] = useState(false);
  const textarea = useRef<HTMLTextAreaElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const mediaStream = useRef<MediaStream | null>(null);
  const mediaRecorder = useRef<MediaRecorder | null>(null);
  const mediaChunks = useRef<Blob[]>([]);
  const audioContext = useRef<AudioContext | null>(null);
  const animationFrame = useRef<number | null>(null);
  const voiceTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const transcriptionAbort = useRef<AbortController | null>(null);
  const voiceSession = useRef(0);
  const recordingStarted = useRef(0);
  const heardAudioRef = useRef(false);
  const t = (vi: string, en: string) => (lang === 'vi' ? vi : en);
  useLayoutEffect(() => {
    const el = textarea.current;
    if (el) {
      el.style.height = '0px';
      el.style.height = `${Math.min(160, Math.max(62, el.scrollHeight))}px`;
    }
  }, [chat.draft, chat.id]);
  useEffect(() => {
    const el = textarea.current;
    if (!el) return;
    let width = 0;
    const observer = new ResizeObserver(() => {
      if (el.clientWidth !== width) {
        width = el.clientWidth;
        el.style.height = '0px';
        el.style.height = `${Math.min(160, Math.max(62, el.scrollHeight))}px`;
      }
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  function releaseMicrophone() {
    if (voiceTimer.current) clearInterval(voiceTimer.current);
    voiceTimer.current = null;
    if (animationFrame.current !== null) cancelAnimationFrame(animationFrame.current);
    animationFrame.current = null;
    void audioContext.current?.close().catch(() => undefined);
    audioContext.current = null;
    mediaStream.current?.getTracks().forEach((track) => track.stop());
    mediaStream.current = null;
    setVoiceLevel(0);
    setMeterReady(false);
  }
  useEffect(() => {
    return () => {
      voiceSession.current += 1;
      transcriptionAbort.current?.abort();
      transcriptionAbort.current = null;
      const recorder = mediaRecorder.current;
      if (recorder) {
        recorder.ondataavailable = null;
        recorder.onerror = null;
        recorder.onstop = null;
        if (recorder.state !== 'inactive') recorder.stop();
      }
      mediaRecorder.current = null;
      releaseMicrophone();
      setVoiceState('idle');
      setVoiceSeconds(0);
      setHeardAudio(false);
    };
  }, [chat.id]);
  function chooseFiles(accept: string) {
    setMenu(null);
    if (fileInput.current) {
      fileInput.current.accept = accept;
      fileInput.current.click();
    }
  }
  function microphoneError(error: unknown) {
    const name = error instanceof DOMException ? error.name : '';
    if (name === 'NotAllowedError' || name === 'SecurityError')
      return t(
        'Quyền micro đang bị chặn. Bấm biểu tượng điều chỉnh bên trái thanh địa chỉ, cho phép Microphone rồi tải lại trang.',
        'Microphone permission is blocked. Allow Microphone in the site controls beside the address bar, then reload.',
      );
    if (name === 'NotFoundError' || name === 'DevicesNotFoundError')
      return t(
        'Không tìm thấy micro. Hãy cắm micro hoặc chọn thiết bị đầu vào trong Windows.',
        'No microphone was found. Connect one or select an input device in Windows.',
      );
    if (name === 'NotReadableError' || name === 'TrackStartError' || name === 'AbortError')
      return t(
        'Micro đang bị ứng dụng khác sử dụng hoặc Windows chưa cho phép truy cập.',
        'The microphone is busy in another app or Windows denied access.',
      );
    return t(
      'Không thể bắt đầu ghi âm. Hãy kiểm tra micro mặc định của Windows rồi thử lại.',
      'Recording could not start. Check the default Windows microphone and try again.',
    );
  }
  function startMeter(stream: MediaStream, session: number) {
    const AudioConstructor =
      window.AudioContext ||
      (window as typeof window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AudioConstructor) return;
    try {
      const context = new AudioConstructor();
      if (context.state === 'suspended') void context.resume().catch(() => undefined);
      const analyser = context.createAnalyser();
      analyser.fftSize = 256;
      analyser.smoothingTimeConstant = 0.75;
      context.createMediaStreamSource(stream).connect(analyser);
      audioContext.current = context;
      setMeterReady(true);
      const values = new Uint8Array(analyser.fftSize);
      let lastPaint = 0;
      const sample = (now: number) => {
        if (session !== voiceSession.current) return;
        analyser.getByteTimeDomainData(values);
        let sum = 0;
        for (const value of values) {
          const normalized = (value - 128) / 128;
          sum += normalized * normalized;
        }
        if (now - lastPaint > 60) {
          const level = Math.min(1, Math.sqrt(sum / values.length) * 5);
          setVoiceLevel(level);
          if (level > 0.025 && !heardAudioRef.current) {
            heardAudioRef.current = true;
            setHeardAudio(true);
          }
          lastPaint = now;
        }
        animationFrame.current = requestAnimationFrame(sample);
      };
      animationFrame.current = requestAnimationFrame(sample);
    } catch {
      // Recording still works when an older browser cannot expose a live meter.
    }
  }
  async function submitRecording(blob: Blob, session: number, chatId: string) {
    if (session !== voiceSession.current) return;
    if (blob.size < 128) {
      setVoiceState('idle');
      notify(
        t(
          'Không ghi nhận được dữ liệu âm thanh. Hãy kiểm tra micro đầu vào của Windows.',
          'No audio data was recorded. Check the Windows input microphone.',
        ),
      );
      return;
    }
    setVoiceState('transcribing');
    const controller = new AbortController();
    transcriptionAbort.current = controller;
    try {
      const result = await transcribeAudio(blob, 'auto', controller.signal);
      if (session !== voiceSession.current) return;
      appendDraft(chatId, result.text);
      notify(
        t(
          `Đã chuyển giọng nói thành văn bản trong ${result.processing_seconds.toFixed(1)} giây.`,
          `Speech converted to text in ${result.processing_seconds.toFixed(1)} seconds.`,
        ),
      );
      requestAnimationFrame(() => textarea.current?.focus());
    } catch (error) {
      if (session !== voiceSession.current || controller.signal.aborted) return;
      notify(
        error instanceof ApiError
          ? error.message
          : t(
              'Không kết nối được bộ nhận dạng giọng nói local.',
              'The local speech recognizer could not be reached.',
            ),
      );
    } finally {
      if (session === voiceSession.current) {
        transcriptionAbort.current = null;
        setVoiceState('idle');
        setVoiceSeconds(0);
      }
    }
  }
  async function startMicrophone() {
    if (!window.isSecureContext) {
      notify(
        t(
          'Micro chỉ hoạt động trên http://127.0.0.1:7860 hoặc HTTPS.',
          'Microphone access requires http://127.0.0.1:7860 or HTTPS.',
        ),
      );
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      notify(
        t(
          'Trình duyệt này chưa hỗ trợ ghi âm. Hãy dùng bản Chrome, Edge hoặc Brave mới.',
          'This browser cannot record audio. Use a current Chrome, Edge, or Brave release.',
        ),
      );
      return;
    }
    const session = ++voiceSession.current;
    const chatId = chat.id;
    setVoiceState('requesting');
    setVoiceSeconds(0);
    setHeardAudio(false);
    heardAudioRef.current = false;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      if (session !== voiceSession.current) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      const mimeType = [
        'audio/webm;codecs=opus',
        'audio/webm',
        'audio/ogg;codecs=opus',
        'audio/mp4',
      ].find((type) => MediaRecorder.isTypeSupported(type));
      const recorder = mimeType
        ? new MediaRecorder(stream, { mimeType, audioBitsPerSecond: 64000 })
        : new MediaRecorder(stream);
      mediaStream.current = stream;
      mediaRecorder.current = recorder;
      mediaChunks.current = [];
      setMicrophoneName(
        stream.getAudioTracks()[0]?.label || t('Micro mặc định', 'Default microphone'),
      );
      recorder.ondataavailable = (event) => {
        if (event.data.size) mediaChunks.current.push(event.data);
      };
      recorder.onerror = () => {
        if (session !== voiceSession.current) return;
        recorder.onstop = null;
        mediaRecorder.current = null;
        releaseMicrophone();
        setVoiceState('idle');
        notify(
          t(
            'Trình duyệt đã mất kết nối với micro. Hãy kiểm tra thiết bị đầu vào.',
            'The browser lost the microphone. Check the input device.',
          ),
        );
      };
      recorder.onstop = () => {
        const elapsed = (performance.now() - recordingStarted.current) / 1000;
        const blob = new Blob(mediaChunks.current, {
          type: recorder.mimeType || mediaChunks.current[0]?.type || 'audio/webm',
        });
        mediaRecorder.current = null;
        mediaChunks.current = [];
        releaseMicrophone();
        setVoiceSeconds(elapsed);
        void submitRecording(blob, session, chatId);
      };
      recorder.start(250);
      recordingStarted.current = performance.now();
      setVoiceState('recording');
      startMeter(stream, session);
      voiceTimer.current = setInterval(() => {
        const elapsed = (performance.now() - recordingStarted.current) / 1000;
        setVoiceSeconds(elapsed);
        if (elapsed >= MAX_RECORDING_SECONDS && recorder.state === 'recording') recorder.stop();
      }, 250);
    } catch (error) {
      if (session !== voiceSession.current) return;
      releaseMicrophone();
      mediaRecorder.current = null;
      setVoiceState('idle');
      notify(microphoneError(error));
    }
  }
  function microphone() {
    if (voiceState === 'recording') {
      setVoiceState('transcribing');
      const recorder = mediaRecorder.current;
      if (recorder?.state === 'recording') recorder.stop();
      return;
    }
    if (voiceState === 'idle') void startMicrophone();
  }
  return (
    <div className="composer-dock" data-testid="composer">
      <div className="context-row">
        <div className="context-anchor">
          <button
            type="button"
            className="context-button"
            onClick={() => setMenu(menu === 'project' ? null : 'project')}
            aria-expanded={menu === 'project'}
          >
            <Folder size={15} />
            <span>{chat.project || t('Chọn dự án', 'Choose project')}</span>
            <ChevronDown size={12} />
          </button>
          {menu === 'project' && (
            <Popover
              close={() => setMenu(null)}
              label={t('Chọn dự án', 'Choose project')}
              className="project-popover"
            >
              <span className="popover-eyebrow">{t('NGỮ CẢNH CỦA BẠN', 'YOUR CONTEXT')}</span>
              {['', ...projects].map((p) => (
                <button
                  key={p}
                  className="menu-row"
                  onClick={() => {
                    update({ project: p });
                    setMenu(null);
                  }}
                >
                  <Folder size={16} />
                  <span>{p || t('Không có dự án', 'No project')}</span>
                  {chat.project === p && <Check size={15} />}
                </button>
              ))}
            </Popover>
          )}
        </div>
        <span className="context-hint">
          {t('Một không gian, mọi ý tưởng', 'A little space for big ideas')}
        </span>
      </div>
      <form
        className={`composer-card ${voiceState === 'recording' ? 'is-recording' : ''}`}
        onSubmit={(e) => {
          e.preventDefault();
          // Sending stays available while a task runs: App decides between an
          // immediate turn and a queued follow-up, so the queue is real.
          if (voiceState === 'idle') send();
        }}
      >
        {chat.action && chat.action !== 'auto' && chat.action !== 'chat' && (
          <div className="composer-files">
            <div className="file-chip tool-chip">
              <Image size={18} />
              <span>
                {chat.action === 'image-search'
                  ? t('Tìm ảnh tương tự', 'Find similar images')
                  : t('Tạo ', 'Create ') +
                    (chat.action === 'image' ? t('ảnh', 'image') : chat.action.toUpperCase())}{' '}
                · {t('ngay trong chat', 'in this chat')}
              </span>
              <IconButton
                label={t('Tắt chế độ tạo ảnh', 'Cancel media mode')}
                onClick={() => update({ action: 'auto' })}
              >
                <X size={14} />
              </IconButton>
            </div>
          </div>
        )}
        {!!chat.documentIds?.length && (
          <div className="composer-files">
            <div className="file-chip">
              <FileText size={18} />
              <span>
                {t(
                  `${chat.documentIds.length} tài liệu từ thư viện`,
                  `${chat.documentIds.length} library documents`,
                )}
              </span>
              <IconButton
                label={t('Bỏ tài liệu đã chọn', 'Clear selected documents')}
                onClick={() => update({ documentIds: [] })}
              >
                <X size={14} />
              </IconButton>
            </div>
          </div>
        )}
        {!!files.length && (
          <div className="composer-files">
            {files.map((f) => (
              <div className="file-chip" key={f.id}>
                {f.preview ? <img src={f.preview} alt="" /> : <FileText size={21} />}
                <span>
                  {f.name}
                  <small>{(f.size / 1024 / 1024).toFixed(1)} MB</small>
                </span>
                <IconButton
                  label={t(`Bỏ tệp ${f.name}`, `Remove ${f.name}`)}
                  onClick={() => removeFile(f.id)}
                >
                  <X size={14} />
                </IconButton>
              </div>
            ))}
          </div>
        )}
        <textarea
          ref={textarea}
          value={chat.draft}
          onChange={(e) => update({ draft: e.target.value })}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              if (voiceState === 'idle') send();
            }
          }}
          placeholder={
            busy
              ? t(
                  'Tris đang bận — tin nhắn sẽ được gửi ngay khi tác vụ hiện tại xong…',
                  'Tris is busy — your message will be sent as soon as the current task finishes…',
                )
              : t(
                  'Hỏi Tris bất cứ điều gì, hoặc thả tài liệu vào đây...',
                  'Ask Tris anything, or drop a document here...',
                )
          }
          aria-label={t('Nhắn tin cho Tris', 'Message Tris')}
          maxLength={4000}
          rows={2}
        />
        {voiceState !== 'idle' && (
          <div className={`voice-capture-status ${voiceState}`} role="status" aria-live="polite">
            <span className="voice-meter" aria-hidden="true">
              {[0.55, 0.85, 1, 0.72, 0.45].map((weight, index) => (
                <i key={index} style={{ height: `${4 + voiceLevel * 16 * weight}px` }} />
              ))}
            </span>
            <span className="voice-capture-copy">
              <strong>
                {voiceState === 'requesting'
                  ? t('Đang xin quyền micro…', 'Requesting microphone access…')
                  : voiceState === 'recording'
                    ? t(`Đang nghe · ${clock(voiceSeconds)}`, `Listening · ${clock(voiceSeconds)}`)
                    : t('Đang chuyển thành văn bản local…', 'Converting to text locally…')}
              </strong>
              {voiceState === 'recording' && (
                <small className={meterReady && voiceSeconds > 2 && !heardAudio ? 'no-signal' : ''}>
                  {meterReady && voiceSeconds > 2 && !heardAudio
                    ? t(
                        'Chưa thấy tín hiệu âm thanh — hãy nói gần micro hơn.',
                        'No audio signal yet — speak closer to the microphone.',
                      )
                    : microphoneName}
                </small>
              )}
            </span>
          </div>
        )}
        <div className="composer-toolbar">
          <div className="composer-tools-left">
            <div className="attachment-anchor">
              <IconButton
                label={t('Đính kèm tệp', 'Add attachment')}
                onClick={() => setMenu(menu === 'file' ? null : 'file')}
                aria-expanded={menu === 'file'}
              >
                <Plus size={20} />
              </IconButton>
              {menu === 'file' && (
                <Popover
                  close={() => setMenu(null)}
                  label={t('Đính kèm', 'Attachments')}
                  className="attachment-popover"
                >
                  {(['image', 'gif', 'video'] as ChatAction[]).map((action) => (
                    <button
                      key={action}
                      type="button"
                      className="menu-row"
                      onClick={() => {
                        setMenu(null);
                        update({ action, demo: false });
                        textarea.current?.focus();
                      }}
                    >
                      <Image size={18} />
                      <span>
                        {action === 'image'
                          ? t('Tạo ảnh trong chat', 'Create image in chat')
                          : action === 'gif'
                            ? t('Tạo GIF trong chat', 'Create GIF in chat')
                            : t('Tạo video từ chuỗi ảnh', 'Create image-sequence video')}
                      </span>
                    </button>
                  ))}
                  <button
                    type="button"
                    className="menu-row"
                    onClick={() => {
                      update({ action: 'image-search', imageMode: 'vision', demo: false });
                      chooseFiles('.png,.jpg,.jpeg,.webp');
                    }}
                  >
                    <Globe2 size={18} />
                    <span>{t('Tìm ảnh tương tự', 'Find similar images')}</span>
                  </button>
                  <button
                    type="button"
                    className="menu-row"
                    onClick={() => chooseFiles('.pdf,.txt,.md,.docx')}
                  >
                    <FileText size={18} />
                    <span>{t('Gửi tài liệu', 'Upload document')}</span>
                    <small>20 MB</small>
                  </button>
                  <button
                    type="button"
                    className="menu-row"
                    onClick={() => chooseFiles('.png,.jpg,.jpeg,.webp')}
                  >
                    <Image size={18} />
                    <span>{t('Gửi hình ảnh', 'Upload image')}</span>
                    <small>10 MB</small>
                  </button>
                  <button
                    type="button"
                    className="menu-row"
                    onClick={() => chooseFiles('.mp4,.mov,.webm,.mkv')}
                  >
                    <Video size={18} />
                    <span>{t('Gửi video', 'Upload video')}</span>
                    <small>150 MB</small>
                  </button>
                  <div className="menu-separator" />
                  <p className="popover-note">
                    {t(
                      'Tối đa 5 tệp · 180 MB/lượt. Video chỉ được lưu, chưa tự động phiên âm.',
                      'Up to 5 files · 180 MB total. Videos are stored, not transcribed.',
                    )}
                  </p>
                </Popover>
              )}
            </div>
            <div className="mode-anchor">
              <button
                type="button"
                className="mode-button"
                aria-label={t('Chế độ học', 'Learning mode')}
                onClick={() => setMenu(menu === 'mode' ? null : 'mode')}
                aria-expanded={menu === 'mode'}
              >
                <ShieldCheck size={15} />
                <span>{modeLabel(chat.mode, lang)}</span>
                <ChevronDown size={11} />
              </button>
              {menu === 'mode' && (
                <Popover
                  close={() => setMenu(null)}
                  label={t('Chế độ học', 'Learning mode')}
                  className="mode-popover"
                >
                  {chat.mode === 'Role Play' && (
                    <label className="popover-note">
                      {t('Tình huống nhập vai', 'Role-play scenario')}
                      <select
                        aria-label={t('Tình huống nhập vai', 'Role-play scenario')}
                        value={chat.scenario || 'Coffee Shop'}
                        onChange={(e) => update({ scenario: e.target.value })}
                      >
                        {[
                          'Coffee Shop',
                          'Job Interview',
                          'Hotel Check-in',
                          'Travel',
                          'Daily Conversation',
                        ].map((s) => (
                          <option key={s}>{s}</option>
                        ))}
                      </select>
                    </label>
                  )}
                  <label className="popover-note">
                    {t('Khi gửi ảnh', 'When uploading images')}
                    <select
                      aria-label={t('Xử lý ảnh', 'Image processing')}
                      value={chat.imageMode || 'vision'}
                      onChange={(e) => update({ imageMode: e.target.value as 'vision' | 'ocr' })}
                    >
                      <option value="vision">
                        {t('Hiểu ảnh · Vision local', 'Understand image · local vision')}
                      </option>
                      <option value="ocr">
                        {t('Đọc chữ · MinerU / OCR', 'Read text · MinerU / OCR')}
                      </option>
                    </select>
                  </label>
                  {(['Conversation', 'Grammar', 'Vocabulary', 'Role Play'] as Mode[]).map(
                    (mode) => (
                      <button
                        key={mode}
                        className="menu-row"
                        onClick={() => {
                          update({ mode });
                          setMenu(null);
                        }}
                      >
                        <span>{modeLabel(mode, lang)}</span>
                        {chat.mode === mode && <Check size={16} />}
                      </button>
                    ),
                  )}
                  <div className="menu-separator" />
                  <button
                    type="button"
                    className="menu-row"
                    aria-pressed={web}
                    onClick={() => setWeb(!web)}
                  >
                    <Globe2 size={16} />
                    <span>{t('Tìm kiếm web', 'Search the web')}</span>
                    {web && <Check size={16} />}
                  </button>
                  <p className="popover-note">
                    {t(
                      'Bật tìm kiếm sẽ gửi từ khóa ra Internet.',
                      'Web search sends your query to the Internet.',
                    )}
                  </p>
                </Popover>
              )}
            </div>
          </div>
          <div className="composer-tools-right">
            <div className="model-anchor">
              <button
                type="button"
                className="model-button"
                onClick={() => setMenu(menu === 'model' ? null : 'model')}
                aria-expanded={menu === 'model'}
                disabled={busy}
              >
                <span>{model.replace('english-tutor-local:', 'Tris ').replace(':latest', '')}</span>
                <span className="model-local-label">Local</span>
                <ChevronDown size={12} />
              </button>
              {menu === 'model' && (
                <Popover
                  close={() => setMenu(null)}
                  label={t('Chọn model', 'Choose model')}
                  className="model-popover"
                >
                  <span className="popover-eyebrow">{t('MODEL TRÊN MÁY', 'ON-DEVICE MODELS')}</span>
                  {!models.length && (
                    <p className="popover-note">
                      {t(
                        'Chưa tìm thấy model Ollama đã cài. Hãy kiểm tra Ollama và thư mục model; không có model nào được tự tải.',
                        'No installed Ollama model found. Check Ollama and its model folder; nothing is downloaded automatically.',
                      )}
                    </p>
                  )}
                  {models.map((m) => (
                    <button
                      key={m.name}
                      className="menu-row"
                      onClick={() => {
                        setModel(m.name);
                        setMenu(null);
                      }}
                    >
                      <span>
                        {m.name.replace('english-tutor-local:', 'Tris ')}
                        <small>
                          {m.size
                            ? `${(m.size / 1e9).toFixed(1)} GB · Ollama`
                            : t('Đợi kết nối Ollama', 'Waiting for Ollama')}
                        </small>
                      </span>
                      {model === m.name && <Check size={16} />}
                    </button>
                  ))}
                  <div className="menu-separator" />
                  <button
                    type="button"
                    className="menu-row"
                    aria-pressed={!!compareWith}
                    onClick={() => {
                      if (compareWith) setCompareWith('');
                      else
                        setCompareWith(
                          models.find(
                            (m) => m.name !== model && m.name.includes('english-tutor-local'),
                          )?.name || models.find((m) => m.name !== model)?.name || '',
                        );
                    }}
                  >
                    <GitCompareArrows size={16} />
                    <span>{t('Đối chiếu hai model', 'Cross-check two models')}</span>
                    {compareWith && <Check size={16} />}
                  </button>
                  {compareWith && (
                    <label className="popover-note">
                      {t('Model đối chiếu', 'Comparison model')}
                      <select
                        aria-label={t('Model đối chiếu', 'Comparison model')}
                        value={compareWith}
                        onChange={(e) => setCompareWith(e.target.value)}
                      >
                        {models
                          .filter((m) => m.name !== model)
                          .map((m) => (
                            <option key={m.name} value={m.name}>
                              {m.name.replace('english-tutor-local:', 'Tris ').replace(':latest', '')}
                            </option>
                          ))}
                      </select>
                    </label>
                  )}
                  <p className="popover-note">
                    {t(
                      'Cùng một câu hỏi được gửi cho cả hai model, sau đó Tris đối chiếu điểm đồng thuận, mâu thuẫn và điều cần kiểm chứng thêm. Chế độ này chưa dùng tài liệu/web.',
                      'The same question goes to both models; Tris then reports agreement, contradictions and what needs further verification. Documents/web are not used in this mode.',
                    )}
                  </p>
                  <p className="popover-note">
                    {t(
                      'Model qwen3… là nền để dựng lại bản Tris khi cần và làm chuẩn so sánh; chọn chúng cho chat sẽ không có tính cách Tris.',
                      'qwen3… models are the base images for rebuilding Tris and serve as comparison baselines; chatting with them directly loses the Tris persona.',
                    )}
                  </p>
                </Popover>
              )}
            </div>
            <IconButton
              className={`microphone ${voiceState}`}
              label={
                voiceState === 'recording'
                  ? t('Dừng ghi âm', 'Stop recording')
                  : voiceState === 'requesting'
                    ? t('Đang xin quyền micro', 'Requesting microphone access')
                    : voiceState === 'transcribing'
                      ? t('Đang chuyển thành văn bản', 'Converting to text')
                      : t('Nhập bằng giọng nói', 'Voice input')
              }
              aria-pressed={voiceState === 'recording'}
              disabled={voiceState === 'requesting' || voiceState === 'transcribing'}
              onClick={microphone}
            >
              {voiceState === 'recording' ? (
                <Square size={16} fill="currentColor" />
              ) : voiceState === 'requesting' || voiceState === 'transcribing' ? (
                <Loader2 size={18} className="spin" />
              ) : (
                <Mic size={18} />
              )}
            </IconButton>
            <div className="composer-send-group">
              {busy && (
                <IconButton
                  className="send-button stop-button"
                  label={t('Dừng trả lời và xóa hàng đợi', 'Stop response and clear the queue')}
                  onClick={stop}
                >
                  <Square size={15} fill="currentColor" />
                </IconButton>
              )}
              <button
                type="submit"
                className={`send-button ${busy ? 'queue-send' : ''}`}
                aria-label={
                  busy
                    ? t('Gửi vào hàng đợi', 'Send to queue')
                    : t('Gửi tin nhắn', 'Send message')
                }
                title={
                  busy
                    ? t(
                        'Tris đang tạo nội dung — tin nhắn này sẽ được trả lời ngay sau đó.',
                        'Tris is creating content — this message will be answered right after.',
                      )
                    : undefined
                }
                disabled={voiceState !== 'idle' || (!chat.draft.trim() && !files.length)}
              >
                <ArrowUp size={21} strokeWidth={2.2} />
                {busy && queuedCount > 0 && (
                  <span className="queue-badge" aria-hidden="true">
                    {queuedCount}
                  </span>
                )}
              </button>
            </div>
          </div>
        </div>
      </form>
      <input
        ref={fileInput}
        type="file"
        multiple
        hidden
        onChange={(e) => {
          addFiles(Array.from(e.target.files || []));
          e.target.value = '';
        }}
      />
      <p className="composer-footnote">
        <span>
          {t(
            'Tris có thể mắc lỗi. Hãy kiểm tra thông tin quan trọng.',
            'Tris can make mistakes. Check important information.',
          )}
        </span>
        <span>
          {chat.demo ? (
            t('Đang dùng dữ liệu mẫu', 'Using sample data')
          ) : (
            <>
              <span className="tiny-dot" />
              {t('Chạy trên máy của bạn', 'Runs on your device')}
            </>
          )}
        </span>
      </p>
    </div>
  );
}
