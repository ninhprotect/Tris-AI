export type Lang = 'vi' | 'en';
export type Device = 'auto' | 'desktop' | 'laptop' | 'tablet' | 'mobile';
export type Mode = 'Conversation' | 'Grammar' | 'Vocabulary' | 'Role Play';
export type ChatAction = 'auto' | 'chat' | 'image' | 'gif' | 'video' | 'image-search';
export type Panel =
  | 'settings'
  | 'usage'
  | 'upgrade'
  | 'prompts'
  | 'schedule'
  | 'plugins'
  | 'search'
  | 'login'
  | 'register'
  | 'study'
  | 'media'
  | null;
export type Attachment = {
  id: string;
  name: string;
  size: number;
  type: string;
  file?: File;
  documentId?: number;
  visionContext?: string;
  preview?: string;
};
export type CompareLive = {
  modelA: string;
  modelB: string;
  a: string;
  b: string;
  judge: string;
};
export type Message = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  attachments?: Attachment[];
  seconds?: number;
  error?: boolean;
  status?: string;
  queued?: boolean;
  mediaMode?: 'image' | 'gif' | 'video';
  compare?: CompareLive;
  sources?: { title: string; label: string; url?: string }[];
};
export type Chat = {
  id: string;
  title: string;
  messages: Message[];
  draft: string;
  project: string;
  mode: Mode;
  scenario?: string;
  documentIds?: number[];
  imageMode?: 'vision' | 'ocr';
  action?: ChatAction;
  demo: boolean;
  starred?: boolean;
  created: string;
};
export type Account = {
  account_id: string;
  username: string;
  learner_name: string;
  auth_provider?: string;
};
export type Health = {
  status: string;
  auth_required: boolean;
  social_login?: { google: boolean };
  local_tts?: { vi: boolean; en: boolean };
  local_stt?: { ready: boolean; model_loaded: boolean; model: string; device: string };
};
export type ModelInfo = { name: string; size?: number };
export type Settings = {
  lang: Lang;
  theme: 'dark' | 'light' | 'system';
  device: Device;
  collapsed: boolean;
  model: string;
  web: boolean;
  compareWith: string;
};
export const uid = () => crypto.randomUUID();
