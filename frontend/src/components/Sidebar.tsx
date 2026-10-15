import { useEffect, useRef, useState } from 'react';
import {
  PanelLeft,
  Plus,
  ChevronDown,
  Search,
  SquarePen,
  Bookmark,
  BookOpen,
  CalendarClock,
  Blocks,
  Folder,
  ChevronRight,
  MoreHorizontal,
  Settings2,
  LogOut,
  Gauge,
  Monitor,
  Sparkles,
  X,
  CircleHelp,
  Check,
  CloudOff,
} from 'lucide-react';
import type { Account, Chat, Lang, Panel } from '../types';
import { IconButton, Popover, TrisMark } from './ui';

export function Sidebar({
  chats,
  active,
  select,
  create,
  collapsed,
  toggle,
  drawer,
  closeDrawer,
  projects,
  addProject,
  lang,
  account,
  panel,
  notify,
  logout,
  setDemo,
  deviceMenu,
  backend,
}: {
  chats: Chat[];
  active: Chat;
  select: (id: string) => void;
  create: (project?: string) => void;
  collapsed: boolean;
  toggle: () => void;
  drawer: boolean;
  closeDrawer: () => void;
  projects: string[];
  addProject: (name: string) => void;
  lang: Lang;
  account: Account | null;
  panel: (v: Panel) => void;
  notify: (v: string) => void;
  logout: () => void;
  setDemo: (v: boolean) => void;
  deviceMenu: () => void;
  backend: boolean;
}) {
  const [menu, setMenu] = useState<'workspace' | 'account' | null>(null);
  const [newProject, setNewProject] = useState(false);
  const [projectName, setProjectName] = useState('');
  const [expanded, setExpanded] = useState(true);
  const navigation = useRef<HTMLElement>(null);
  useEffect(() => {
    if (!drawer) return;
    const previous = document.activeElement as HTMLElement;
    navigation.current?.querySelector<HTMLButtonElement>('button')?.focus();
    const trap = (event: KeyboardEvent) => {
      if (event.key !== 'Tab') return;
      const buttons = [
        ...(navigation.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input') ||
          []),
      ].filter((el) => el.getClientRects().length);
      const first = buttons[0],
        last = buttons.at(-1);
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      }
      if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    };
    document.addEventListener('keydown', trap);
    return () => {
      document.removeEventListener('keydown', trap);
      previous?.focus();
    };
  }, [drawer]);
  const t = (vi: string, en: string) => (lang === 'vi' ? vi : en);
  const name = account?.learner_name || t('Khách', 'Guest');
  const open = (p: Panel) => {
    setMenu(null);
    panel(p);
    closeDrawer();
  };
  return (
    <>
      {drawer && (
        <button
          className="sidebar-scrim"
          aria-label={t('Đóng thanh bên', 'Close sidebar')}
          onClick={closeDrawer}
        />
      )}
      <aside
        ref={navigation}
        className={`sidebar ${collapsed ? 'is-collapsed' : ''} ${drawer ? 'drawer-open' : ''}`}
        aria-label={t('Điều hướng chính', 'Main navigation')}
      >
        <div className="sidebar-top">
          <div className="workspace-anchor">
            <button
              className="brand-button"
              onClick={() => setMenu(menu === 'workspace' ? null : 'workspace')}
              aria-expanded={menu === 'workspace'}
              aria-haspopup="dialog"
              aria-label={t('Không gian Tris AI', 'Tris AI workspace')}
            >
              <TrisMark />
              <span className="sidebar-label brand-name">Tris AI</span>
              <ChevronDown className="sidebar-label" size={14} />
            </button>
            {menu === 'workspace' && (
              <Popover
                label={t('Không gian làm việc', 'Workspace')}
                close={() => setMenu(null)}
                className="workspace-popover"
              >
                <span className="popover-eyebrow">TRIS WORKSPACE</span>
                <button
                  className="menu-row"
                  onClick={() => {
                    setDemo(false);
                    setMenu(null);
                  }}
                >
                  <CloudOff size={17} />
                  <span>
                    AI local
                    <small>
                      {t('Trò chuyện với model trên máy', 'Chat with a model on your device')}
                    </small>
                  </span>
                  {!active.demo && <Check size={15} />}
                </button>
                <button
                  className="menu-row"
                  onClick={() => {
                    setDemo(true);
                    setMenu(null);
                  }}
                >
                  <Sparkles size={17} />
                  <span>
                    {t('Trải nghiệm mẫu', 'Sample experience')}
                    <small>{t('Thử giao diện, không gọi AI', 'Explore without calling AI')}</small>
                  </span>
                  {active.demo && <Check size={15} />}
                </button>
              </Popover>
            )}
          </div>
          <IconButton
            className="sidebar-collapse"
            label={
              collapsed
                ? t('Mở rộng thanh bên', 'Expand sidebar')
                : t('Thu gọn thanh bên', 'Collapse sidebar')
            }
            onClick={toggle}
          >
            <PanelLeft size={17} />
          </IconButton>
          <IconButton
            className="drawer-close"
            label={t('Đóng thanh bên', 'Close sidebar')}
            onClick={closeDrawer}
          >
            <X size={19} />
          </IconButton>
        </div>
        <nav className="primary-nav">
          <button
            className="nav-item"
            onClick={() => open('study')}
            title={t('Học tập & tài liệu', 'Study & documents')}
          >
            <BookOpen size={18} />
            <span className="sidebar-label">{t('Học tập & tài liệu', 'Study & documents')}</span>
          </button>
          <button
            className="nav-item new-chat"
            onClick={() => {
              create();
              closeDrawer();
            }}
            aria-label={t('Đoạn chat mới', 'New chat')}
            title={t('Đoạn chat mới', 'New chat')}
          >
            <SquarePen size={18} />
            <span className="sidebar-label">{t('Đoạn chat mới', 'New chat')}</span>
            <kbd className="sidebar-label">Ctrl N</kbd>
          </button>
          <button
            className="nav-item"
            onClick={() => open('search')}
            title={t('Tìm kiếm hội thoại', 'Search conversations')}
          >
            <Search size={18} />
            <span className="sidebar-label">{t('Tìm kiếm', 'Search chats')}</span>
            <kbd className="sidebar-label">Ctrl K</kbd>
          </button>
          <button
            className="nav-item"
            onClick={() => open('prompts')}
            title={t('Prompt yêu thích', 'Saved prompts')}
          >
            <Bookmark size={18} />
            <span className="sidebar-label">{t('Prompt yêu thích', 'Saved prompts')}</span>
          </button>
          <button
            className="nav-item"
            onClick={() => open('schedule')}
            title={t('Đã lên lịch', 'Scheduled')}
          >
            <CalendarClock size={18} />
            <span className="sidebar-label">{t('Đã lên lịch', 'Scheduled')}</span>
          </button>
          <button
            className="nav-item"
            onClick={() => open('plugins')}
            title={t('Công cụ', 'Tools')}
          >
            <Blocks size={18} />
            <span className="sidebar-label">{t('Công cụ', 'Tools')}</span>
          </button>
        </nav>
        <div className="sidebar-scroll" data-testid="sidebar-scroll">
          <section className="projects-section">
            <div className="sidebar-section-title">
              <button onClick={() => setExpanded(!expanded)} aria-expanded={expanded}>
                {t('Dự án', 'Projects')}
                <ChevronDown size={12} className={expanded ? '' : 'rotate-closed'} />
              </button>
              <IconButton
                label={t('Tạo dự án', 'Create project')}
                onClick={() => setNewProject(!newProject)}
              >
                <Plus size={14} />
              </IconButton>
            </div>
            {expanded &&
              projects.map((p, i) => (
                <button
                  key={p}
                  className={`project-item ${active.project === p ? 'project-active' : ''}`}
                  onClick={() => {
                    create(p);
                    closeDrawer();
                  }}
                >
                  <Folder size={16} className={i === 0 ? 'folder-lavender' : 'folder-teal'} />
                  <span>{p}</span>
                  <ChevronRight size={13} />
                </button>
              ))}
            {newProject && (
              <form
                className="inline-project"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (projectName.trim()) {
                    addProject(projectName.trim().slice(0, 60));
                    setProjectName('');
                    setNewProject(false);
                  }
                }}
              >
                <input
                  autoFocus
                  value={projectName}
                  onChange={(e) => setProjectName(e.target.value)}
                  placeholder={t('Tên dự án...', 'Project name...')}
                  aria-label={t('Tên dự án', 'Project name')}
                  maxLength={60}
                />
                <IconButton label={t('Lưu dự án', 'Save project')} type="submit">
                  <Check size={15} />
                </IconButton>
              </form>
            )}
          </section>
          <section className="recent-section">
            <div className="sidebar-section-title">
              <span>{t('Gần đây', 'Recent')}</span>
              <span className="history-count">{chats.filter((c) => c.messages.length).length}</span>
            </div>
            <div className="history-list">
              {chats
                .filter((c) => c.messages.length)
                .map((c) => (
                  <button
                    key={c.id}
                    className={`history-item ${c.id === active.id ? 'active' : ''}`}
                    onClick={() => {
                      select(c.id);
                      closeDrawer();
                    }}
                    title={c.title}
                  >
                    <span>{c.title}</span>
                    {c.demo ? <small>{t('Mẫu', 'Demo')}</small> : <MoreHorizontal size={16} />}
                  </button>
                ))}
            </div>
          </section>
        </div>
        <div className="sidebar-bottom">
          <button className="local-note" onClick={() => open('usage')}>
            <span className={`status-dot ${backend ? '' : 'offline'}`} />
            <span>
              {backend
                ? t('AI của bạn, trên máy bạn', 'Your AI, on your device')
                : t('Không gian riêng của bạn', 'Your personal workspace')}
            </span>
            <CircleHelp size={13} />
          </button>
          <div className="account-anchor">
            <button
              className="account-button"
              onClick={() => setMenu(menu === 'account' ? null : 'account')}
              aria-expanded={menu === 'account'}
              aria-haspopup="dialog"
              aria-label={t('Mở menu tài khoản', 'Open account menu')}
            >
              <span className="avatar">{name.slice(0, 1).toUpperCase()}</span>
              <span className="account-copy sidebar-label">
                <strong>{name}</strong>
                <small>Local workspace</small>
              </span>
              <MoreHorizontal className="sidebar-label" size={18} />
            </button>
            {menu === 'account' && (
              <Popover
                label={t('Menu tài khoản', 'Account menu')}
                className="account-popover"
                close={() => setMenu(null)}
              >
                <div className="account-menu-header">
                  <span className="avatar">{name.slice(0, 1).toUpperCase()}</span>
                  <div>
                    <strong>{name}</strong>
                    <small>
                      {account ? account.username : t('Chưa đăng nhập', 'Not signed in')}
                    </small>
                  </div>
                  <span className="local-badge">LOCAL</span>
                </div>
                <div className="menu-separator" />
                <button className="menu-row" onClick={() => open('usage')}>
                  <Gauge size={17} />
                  <span>{t('Mức sử dụng', 'Usage')}</span>
                  <small>Local</small>
                </button>
                <button
                  className="menu-row"
                  onClick={() => {
                    setMenu(null);
                    closeDrawer();
                    deviceMenu();
                  }}
                >
                  <Monitor size={17} />
                  <span>{t('Hiển thị thiết bị', 'Device preview')}</span>
                  <ChevronRight size={14} />
                </button>
                <button className="menu-row upgrade-row" onClick={() => open('upgrade')}>
                  <Sparkles size={17} />
                  <span>{t('Nâng cấp gói', 'Upgrade plan')}</span>
                </button>
                <button className="menu-row" onClick={() => open('settings')}>
                  <Settings2 size={17} />
                  <span>{t('Cài đặt', 'Settings')}</span>
                  <kbd>Ctrl ,</kbd>
                </button>
                <div className="menu-separator" />
                {account ? (
                  <button
                    className="menu-row"
                    onClick={() => {
                      logout();
                      setMenu(null);
                    }}
                  >
                    <LogOut size={17} />
                    <span>{t('Đăng xuất', 'Sign out')}</span>
                  </button>
                ) : (
                  <button className="menu-row" onClick={() => open('login')}>
                    <LogOut size={17} />
                    <span>{t('Đăng nhập', 'Sign in')}</span>
                  </button>
                )}
              </Popover>
            )}
          </div>
        </div>
      </aside>
    </>
  );
}
