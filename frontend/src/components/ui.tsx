import {
  useEffect,
  useLayoutEffect,
  useRef,
  type ReactNode,
  type ButtonHTMLAttributes,
} from 'react';
import { X } from 'lucide-react';

export function TrisMark({ className = '' }: { className?: string }) {
  return (
    <svg
      className={`tris-mark ${className}`}
      width="32"
      height="32"
      viewBox="0 0 48 48"
      fill="none"
      aria-hidden="true"
    >
      <path
        d="M24 5c2.2 10.7 8.3 16.8 19 19-10.7 2.2-16.8 8.3-19 19C21.8 32.3 15.7 26.2 5 24 15.7 21.8 21.8 15.7 24 5Z"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinejoin="round"
      />
      <path d="M24 16v16M16 24h16" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
    </svg>
  );
}
export function IconButton({
  label,
  children,
  className = '',
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { label: string; children: ReactNode }) {
  return (
    <button
      type="button"
      className={`icon-button ${className}`}
      title={label}
      aria-label={label}
      {...props}
    >
      {children}
    </button>
  );
}
export function Popover({
  children,
  close,
  className = '',
  label,
}: {
  children: ReactNode;
  close: () => void;
  className?: string;
  label: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const closeRef = useRef(close);
  closeRef.current = close;
  useLayoutEffect(() => {
    const el = ref.current;
    const frame = el?.closest('.app-frame');
    if (!el || !frame) return;
    const position = () => {
      const bounds = frame.getBoundingClientRect();
      el.style.translate = '0px 0px';
      el.style.maxHeight = `${Math.max(100, bounds.height - 24)}px`;
      el.style.overflowY = 'auto';
      const rect = el.getBoundingClientRect();
      const dx =
        rect.left < bounds.left + 12
          ? bounds.left + 12 - rect.left
          : Math.min(0, bounds.right - 12 - rect.right);
      const dy =
        rect.top < bounds.top + 12
          ? bounds.top + 12 - rect.top
          : Math.min(0, bounds.bottom - 12 - rect.bottom);
      el.style.translate = `${dx}px ${dy}px`;
    };
    position();
    const observer = new ResizeObserver(position);
    observer.observe(frame);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    const trigger = document.activeElement as HTMLElement;
    const first = ref.current?.querySelector<HTMLElement>('button:not(:disabled),input');
    first?.focus();
    const click = (event: PointerEvent) => {
      if (!ref.current?.parentElement?.contains(event.target as Node)) closeRef.current();
    };
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation();
        closeRef.current();
        trigger?.focus();
      }
      if (
        ['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key) &&
        ref.current?.contains(document.activeElement)
      ) {
        const items = [...ref.current.querySelectorAll<HTMLElement>('button:not(:disabled),input')];
        if (!items.length || document.activeElement?.tagName === 'INPUT') return;
        event.preventDefault();
        const index = items.indexOf(document.activeElement as HTMLElement);
        const next =
          event.key === 'Home'
            ? 0
            : event.key === 'End'
              ? items.length - 1
              : (index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
        items[next].focus();
      }
    };
    document.addEventListener('pointerdown', click);
    document.addEventListener('keydown', key);
    return () => {
      document.removeEventListener('pointerdown', click);
      document.removeEventListener('keydown', key);
    };
  }, []);
  return (
    <div ref={ref} className={`popover ${className}`} role="dialog" aria-label={label}>
      {children}
    </div>
  );
}
export function Modal({
  title,
  close,
  children,
  className = '',
}: {
  title: string;
  close: () => void;
  children: ReactNode;
  className?: string;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    ref.current?.showModal();
    return () => ref.current?.close();
  }, []);
  return (
    <dialog
      ref={ref}
      className={`modal ${className}`}
      aria-label={title}
      onCancel={(e) => {
        e.preventDefault();
        close();
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) close();
      }}
    >
      <div className="modal-card">
        <header className="modal-header">
          <h2>{title}</h2>
          <IconButton label="Đóng / Close" onClick={close}>
            <X size={19} />
          </IconButton>
        </header>
        {children}
      </div>
    </dialog>
  );
}
export function Toggle({
  value,
  change,
  label,
}: {
  value: boolean;
  change: (value: boolean) => void;
  label: string;
}) {
  return (
    <button
      className="toggle"
      role="switch"
      aria-checked={value}
      aria-label={label}
      onClick={() => change(!value)}
    >
      <span />
    </button>
  );
}
