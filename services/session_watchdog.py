"""Shut the desktop app down once every browser tab is gone.

Tris AI runs on an older laptop (GTX 1060, 8th-gen i7), so an idle server
holding VRAM after the learner closed the page is wasted heat. The watchdog
counts connected Gradio sessions: when the last tab unloads, a grace timer
starts, and expiry hands control to the app's shutdown routine.
"""

from __future__ import annotations

import threading
from collections.abc import Callable


class SessionWatchdog:
    """Count connected tabs and schedule shutdown when none remain."""

    def __init__(
        self,
        grace_seconds: int = 120,
        timer_factory: Callable[..., threading.Timer] = threading.Timer,
        on_expire: Callable[[], None] | None = None,
    ) -> None:
        self.grace_seconds = max(int(grace_seconds), 5)
        self._timer_factory = timer_factory
        self._on_expire = on_expire
        self._sessions = 0
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    @property
    def sessions(self) -> int:
        return self._sessions

    @property
    def shutdown_pending(self) -> bool:
        return self._timer is not None

    def connect(self) -> None:
        """One more tab opened; cancel any pending shutdown countdown."""
        with self._lock:
            self._sessions += 1
            self._cancel_timer_locked()

    def disconnect(self) -> None:
        """One tab closed or refreshed; start the countdown at zero tabs."""
        with self._lock:
            self._sessions = max(0, self._sessions - 1)
            if self._sessions == 0 and self._timer is None:
                self._timer = self._timer_factory(self.grace_seconds, self._expire)
                self._timer.daemon = True
                self._timer.start()

    def _cancel_timer_locked(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _expire(self) -> None:
        with self._lock:
            self._timer = None
        callback = self._on_expire or (lambda: None)
        callback()
