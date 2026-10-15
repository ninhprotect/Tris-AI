import type { Account, Chat, ChatAction, Health, ModelInfo } from './types';

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}
export const readSession = (): { token: string; account: Account } | null => {
  try {
    return JSON.parse(sessionStorage.getItem('tris.workspace.session') || 'null');
  } catch {
    return null;
  }
};
export function authHeaders(): Record<string, string> {
  const token = readSession()?.token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}
export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  let response: Response;
  const headers = new Headers(authHeaders());
  if (options.body && !(options.body instanceof FormData))
    headers.set('Content-Type', 'application/json');
  new Headers(options.headers).forEach((value, key) => headers.set(key, value));
  try {
    response = await fetch(path, { ...options, headers });
  } catch (error) {
    if (options.signal?.aborted) throw error;
    throw new ApiError('Không kết nối được Tris AI. Hãy kiểm tra backend đang chạy.', 0);
  }
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new ApiError(
      typeof data.detail === 'string' ? data.detail : `Yêu cầu chưa hoàn tất (${response.status}).`,
      response.status,
    );
  }
  return response.json();
}
export const loadHealth = () => request<Health>('/health');
export const loadModels = () =>
  request<{ models: ModelInfo[]; default: string }>('/v1/workspace/models');

export type TranscriptionResult = {
  text: string;
  language: string;
  audio_seconds: number;
  processing_seconds: number;
  device: string;
  model: string;
};

export function transcribeAudio(
  audio: Blob,
  language: 'vi' | 'en' | 'auto',
  signal?: AbortSignal,
): Promise<TranscriptionResult> {
  const suffix = audio.type.includes('ogg')
    ? 'ogg'
    : audio.type.includes('wav')
      ? 'wav'
      : audio.type.includes('mp4')
        ? 'm4a'
        : 'webm';
  const body = new FormData();
  body.set('language', language);
  body.set('file', audio, `tris-microphone-${Date.now()}.${suffix}`);
  return request<TranscriptionResult>('/v1/workspace/transcribe', {
    method: 'POST',
    body,
    signal,
  });
}

async function readNdjson(response: Response, deliver: (line: string) => void) {
  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';
      for (const line of lines) deliver(line);
    }
    buffer += decoder.decode();
    deliver(buffer);
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}

export async function streamCompare(
  text: string,
  modelA: string,
  modelB: string,
  mode: string,
  scenario: string,
  lang: 'vi' | 'en',
  history: { role: 'user' | 'assistant'; content: string }[],
  signal: AbortSignal,
  onEvent: (event: {
    delta?: string;
    which?: 'a' | 'b';
    judge?: string;
    error?: string;
    done?: boolean;
    seconds?: number;
    status?: string;
  }) => void,
) {
  const response = await fetch('/v1/workspace/compare', {
    method: 'POST',
    signal,
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({
      message: text,
      model_a: modelA,
      model_b: modelB,
      mode,
      scenario,
      language: lang,
      history,
    }),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new ApiError(data.detail || `Lỗi ${response.status}`, response.status);
  }
  if (!response.body) throw new ApiError('Không nhận được dữ liệu trả lời.', 502);
  let completed = false;
  const deliver = (line: string) => {
    if (!line.trim()) return;
    const event = JSON.parse(line);
    if (event.done) completed = true;
    onEvent(event);
  };
  try {
    await readNdjson(response, deliver);
    if (!completed && !signal.aborted)
      throw new ApiError('Kết nối bị ngắt trước khi đối chiếu xong. Hãy thử lại.', 502);
  } finally {
    /* reader released inside readNdjson */
  }
}

export async function streamChat(
  chat: Chat,
  text: string,
  model: string,
  lang: string,
  web: boolean,
  signal: AbortSignal,
  onEvent: (event: {
    delta?: string;
    error?: string;
    done?: boolean;
    seconds?: number;
    status?: string;
    sources?: { title: string; label: string; url?: string }[];
  }) => void,
  followUp = false,
  actionOverride?: ChatAction,
) {
  const response = await fetch('/v1/workspace/chat', {
    method: 'POST',
    signal,
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({
      message: text,
      mode: chat.mode,
      // Only an explicit tool choice sets a media action; a queued follow-up
      // must not silently inherit whatever chip the composer showed before.
      action: actionOverride || chat.action || 'auto',
      scenario: chat.scenario || 'Coffee Shop',
      follow_up: followUp,
      image_context: chat.messages
        .flatMap((m) => m.attachments || [])
        .map((a) => a.visionContext || '')
        .filter(Boolean)
        .join('\n')
        .slice(-12000),
      model,
      language: lang,
      web_search: web,
      history: chat.messages
        .slice(0, -1)
        .filter((m) => !m.error)
        .slice(-12)
        .map((m) => ({ role: m.role, content: m.content.slice(0, 8000) })),
      document_ids: [
        ...new Set([
          ...(chat.documentIds || []),
          ...chat.messages
            .flatMap((m) => m.attachments || [])
            .flatMap((a) => (a.documentId ? [a.documentId] : [])),
        ]),
      ].slice(-20),
    }),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new ApiError(data.detail || `Lỗi ${response.status}`, response.status);
  }
  if (!response.body) throw new ApiError('Không nhận được dữ liệu trả lời.', 502);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let completed = false;
  const deliver = (line: string) => {
    if (!line.trim()) return;
    const event = JSON.parse(line);
    if (event.done) completed = true;
    onEvent(event);
  };
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';
      for (const line of lines) deliver(line);
    }
    buffer += decoder.decode();
    deliver(buffer);
    if (!completed && !signal.aborted)
      throw new ApiError('Kết nối bị ngắt trước khi AI trả lời xong. Hãy gửi lại câu hỏi.', 502);
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}
