"""Secure PostgreSQL accounts with Argon2id password hashing."""

from __future__ import annotations

import re
import secrets
import threading
import uuid
from hashlib import sha256
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from config.settings import AUTH_SESSION_HOURS, POSTGRES_DSN


class AccountError(RuntimeError):
    """Safe account error suitable for API and UI responses."""


@dataclass(frozen=True)
class Account:
    account_id: str
    username: str
    learner_name: str
    auth_provider: str = "password"


class PostgreSQLAccountStore:
    """Keep credentials only in PostgreSQL; never in the learner SQLite file."""

    def __init__(self, dsn: str = POSTGRES_DSN) -> None:
        self.dsn = dsn.strip()
        self.password_hasher = PasswordHasher(
            time_cost=3,
            memory_cost=65536,
            parallelism=4,
            hash_len=32,
            salt_len=16,
        )
        self._dummy_hash = self.password_hasher.hash("not-a-real-password-123A")

    @property
    def configured(self) -> bool:
        return bool(self.dsn)

    def initialize(self) -> None:
        if not self.configured:
            return
        try:
            with self._connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS tutor_accounts (
                            id UUID PRIMARY KEY,
                            username VARCHAR(32) NOT NULL,
                            username_key VARCHAR(32) NOT NULL UNIQUE,
                            password_hash TEXT,
                            learner_name VARCHAR(50) NOT NULL,
                            email VARCHAR(320),
                            email_verified BOOLEAN NOT NULL DEFAULT FALSE,
                            is_active BOOLEAN NOT NULL DEFAULT TRUE,
                            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            last_login_at TIMESTAMPTZ
                        )
                        """
                    )
                    cursor.execute(
                        "ALTER TABLE tutor_accounts "
                        "ALTER COLUMN password_hash DROP NOT NULL"
                    )
                    cursor.execute(
                        "ALTER TABLE tutor_accounts "
                        "ADD COLUMN IF NOT EXISTS email VARCHAR(320)"
                    )
                    cursor.execute(
                        "ALTER TABLE tutor_accounts ADD COLUMN IF NOT EXISTS "
                        "email_verified BOOLEAN NOT NULL DEFAULT FALSE"
                    )
                    cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS tutor_social_identities (
                            id UUID PRIMARY KEY,
                            account_id UUID NOT NULL REFERENCES tutor_accounts(id)
                                ON DELETE CASCADE,
                            provider VARCHAR(20) NOT NULL,
                            provider_user_id VARCHAR(255) NOT NULL,
                            email VARCHAR(320),
                            email_verified BOOLEAN NOT NULL DEFAULT FALSE,
                            display_name VARCHAR(100),
                            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            last_login_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            UNIQUE(provider, provider_user_id),
                            UNIQUE(account_id, provider)
                        )
                        """
                    )
                    cursor.execute(
                        "CREATE INDEX IF NOT EXISTS idx_tutor_accounts_active "
                        "ON tutor_accounts(username_key) WHERE is_active = TRUE"
                    )
        except Exception as exc:
            raise AccountError(
                "Không kết nối được PostgreSQL cho hệ thống tài khoản."
            ) from exc

    def register(self, username: str, password: str, learner_name: str) -> Account:
        display_username, username_key = self._validate_username(username)
        self._validate_password(password)
        clean_learner_name = " ".join((learner_name or display_username).split())[:50]
        if not clean_learner_name:
            clean_learner_name = display_username
        password_hash = self.password_hasher.hash(password)
        account_id = str(uuid.uuid4())
        try:
            with self._connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO tutor_accounts(
                            id, username, username_key, password_hash, learner_name
                        ) VALUES (%s, %s, %s, %s, %s)
                        """,
                        (
                            account_id,
                            display_username,
                            username_key,
                            password_hash,
                            clean_learner_name,
                        ),
                    )
            return Account(account_id, display_username, clean_learner_name)
        except AccountError:
            raise
        except Exception as exc:
            if "unique" in str(exc).casefold() or "duplicate" in str(exc).casefold():
                raise AccountError("Tên đăng nhập này đã được sử dụng.") from exc
            raise AccountError("Không thể tạo tài khoản PostgreSQL.") from exc

    def authenticate(self, username: str, password: str) -> Account:
        _, username_key = self._validate_username(username)
        row = None
        try:
            with self._connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT id, username, password_hash, learner_name
                        FROM tutor_accounts
                        WHERE username_key = %s AND is_active = TRUE
                        """,
                        (username_key,),
                    )
                    row = cursor.fetchone()
                    stored_hash = (
                        str(row[2]) if row and row[2] is not None else self._dummy_hash
                    )
                    try:
                        verified = self.password_hasher.verify(stored_hash, password)
                    except (VerifyMismatchError, InvalidHashError):
                        verified = False
                    if row is None or not verified:
                        raise AccountError("Tên đăng nhập hoặc mật khẩu không đúng.")
                    if self.password_hasher.check_needs_rehash(stored_hash):
                        cursor.execute(
                            "UPDATE tutor_accounts SET password_hash = %s, "
                            "updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                            (self.password_hasher.hash(password), row[0]),
                        )
                    cursor.execute(
                        "UPDATE tutor_accounts SET last_login_at = CURRENT_TIMESTAMP "
                        "WHERE id = %s",
                        (row[0],),
                    )
            return Account(str(row[0]), str(row[1]), str(row[3]))
        except AccountError:
            raise
        except Exception as exc:
            raise AccountError("Không thể đăng nhập bằng PostgreSQL.") from exc

    def change_password(
        self,
        account_id: str,
        current_password: str,
        new_password: str,
    ) -> None:
        self._validate_password(new_password)
        try:
            with self._connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT password_hash FROM tutor_accounts "
                        "WHERE id = %s AND is_active = TRUE",
                        (account_id,),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        raise AccountError("Tài khoản không còn hoạt động.")
                    if row[0] is None:
                        raise AccountError(
                            "Tài khoản này đăng nhập bằng Google/Facebook và chưa có mật khẩu."
                        )
                    try:
                        valid = self.password_hasher.verify(
                            str(row[0]), current_password
                        )
                    except (VerifyMismatchError, InvalidHashError):
                        valid = False
                    if not valid:
                        raise AccountError("Mật khẩu hiện tại không đúng.")
                    cursor.execute(
                        """
                        UPDATE tutor_accounts
                        SET password_hash = %s, updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                        """,
                        (self.password_hasher.hash(new_password), account_id),
                    )
        except AccountError:
            raise
        except Exception as exc:
            raise AccountError("Không thể đổi mật khẩu trong PostgreSQL.") from exc

    def authenticate_social(
        self,
        provider: str,
        provider_user_id: str,
        email: str | None,
        email_verified: bool,
        display_name: str,
    ) -> Account:
        """Find or create an account from a provider-verified identity.

        Email is metadata only. Accounts are keyed by provider + provider user ID,
        so a matching email can never silently take over a password account.
        """
        clean_provider = (provider or "").strip().casefold()
        if clean_provider not in {"google", "facebook"}:
            raise AccountError("Nhà cung cấp đăng nhập không được hỗ trợ.")
        clean_provider_id = (provider_user_id or "").strip()
        if not clean_provider_id or len(clean_provider_id) > 255:
            raise AccountError("Danh tính từ nhà cung cấp không hợp lệ.")
        clean_name = " ".join((display_name or "Người học").split())[:50]
        clean_email = (email or "").strip().casefold()[:320] or None
        digest = sha256(
            f"{clean_provider}:{clean_provider_id}".encode("utf-8")
        ).hexdigest()[:16]
        username = f"{clean_provider}_{digest}"[:32]
        try:
            with self._connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT a.id, a.username, a.learner_name
                        FROM tutor_social_identities AS s
                        JOIN tutor_accounts AS a ON a.id = s.account_id
                        WHERE s.provider = %s AND s.provider_user_id = %s
                          AND a.is_active = TRUE
                        """,
                        (clean_provider, clean_provider_id),
                    )
                    row = cursor.fetchone()
                    if row is not None:
                        cursor.execute(
                            """
                            UPDATE tutor_social_identities
                            SET email = %s, email_verified = %s,
                                display_name = %s,
                                last_login_at = CURRENT_TIMESTAMP
                            WHERE provider = %s AND provider_user_id = %s
                            """,
                            (
                                clean_email,
                                bool(email_verified),
                                clean_name,
                                clean_provider,
                                clean_provider_id,
                            ),
                        )
                        cursor.execute(
                            """
                            UPDATE tutor_accounts
                            SET email = COALESCE(%s, email),
                                email_verified = email_verified OR %s,
                                last_login_at = CURRENT_TIMESTAMP,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE id = %s
                            """,
                            (clean_email, bool(email_verified), row[0]),
                        )
                        return Account(
                            str(row[0]), str(row[1]), str(row[2]), clean_provider
                        )

                    account_id = str(uuid.uuid4())
                    cursor.execute(
                        """
                        INSERT INTO tutor_accounts(
                            id, username, username_key, password_hash, learner_name,
                            email, email_verified, last_login_at
                        ) VALUES (%s, %s, %s, NULL, %s, %s, %s, CURRENT_TIMESTAMP)
                        """,
                        (
                            account_id,
                            username,
                            username,
                            clean_name,
                            clean_email,
                            bool(email_verified),
                        ),
                    )
                    cursor.execute(
                        """
                        INSERT INTO tutor_social_identities(
                            id, account_id, provider, provider_user_id, email,
                            email_verified, display_name
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            str(uuid.uuid4()),
                            account_id,
                            clean_provider,
                            clean_provider_id,
                            clean_email,
                            bool(email_verified),
                            clean_name,
                        ),
                    )
            return Account(account_id, username, clean_name, clean_provider)
        except AccountError:
            raise
        except Exception as exc:
            raise AccountError(
                "Không thể tạo hoặc đăng nhập tài khoản xã hội."
            ) from exc

    @staticmethod
    def _validate_username(username: str) -> tuple[str, str]:
        display = (username or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_.-]{3,32}", display):
            raise AccountError(
                "Tên đăng nhập cần 3–32 ký tự: chữ, số, dấu chấm, gạch dưới hoặc gạch ngang."
            )
        return display, display.casefold()

    @staticmethod
    def _validate_password(password: str) -> None:
        value = password or ""
        if len(value) < 10 or len(value) > 128:
            raise AccountError("Mật khẩu cần từ 10 đến 128 ký tự.")
        if not re.search(r"[a-z]", value) or not re.search(r"[A-Z]", value):
            raise AccountError("Mật khẩu cần có chữ thường và chữ hoa.")
        if not re.search(r"\d", value):
            raise AccountError("Mật khẩu cần có ít nhất một chữ số.")

    def _connection(self):
        if not self.configured:
            raise AccountError(
                "PostgreSQL chưa được cấu hình. Hãy đặt TUTOR_POSTGRES_DSN."
            )
        try:
            import psycopg

            return psycopg.connect(self.dsn, connect_timeout=5)
        except Exception as exc:
            raise AccountError("Không kết nối được PostgreSQL.") from exc


class AuthSessionManager:
    """Short-lived opaque sessions; passwords never become session data."""

    def __init__(self, lifetime_hours: int = AUTH_SESSION_HOURS) -> None:
        self.lifetime = timedelta(hours=max(1, min(int(lifetime_hours), 168)))
        self._sessions: dict[str, tuple[Account, datetime]] = {}
        self._lock = threading.RLock()

    def create(self, account: Account) -> str:
        token = secrets.token_urlsafe(48)
        with self._lock:
            self._purge_expired()
            self._sessions[token] = (account, datetime.now(UTC) + self.lifetime)
        return token

    def get(self, token: str) -> Account | None:
        with self._lock:
            self._purge_expired()
            record = self._sessions.get(token or "")
            return record[0] if record else None

    def revoke(self, token: str) -> None:
        with self._lock:
            self._sessions.pop(token or "", None)

    def _purge_expired(self) -> None:
        now = datetime.now(UTC)
        expired = [token for token, (_, until) in self._sessions.items() if until <= now]
        for token in expired:
            self._sessions.pop(token, None)
