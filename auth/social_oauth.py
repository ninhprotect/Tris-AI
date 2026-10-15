"""Google/Facebook OAuth login without persisting provider access tokens."""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from authlib.integrations.starlette_client import OAuth

from auth.postgres_auth import Account, AccountError
from config.settings import (
    FACEBOOK_GRAPH_VERSION,
    FACEBOOK_OAUTH_CLIENT_ID,
    FACEBOOK_OAUTH_CLIENT_SECRET,
    GOOGLE_OAUTH_CLIENT_ID,
    GOOGLE_OAUTH_CLIENT_SECRET,
)


SUPPORTED_PROVIDERS = ("google", "facebook")


@dataclass(frozen=True)
class SocialProfile:
    provider: str
    provider_user_id: str
    display_name: str
    email: str | None = None
    email_verified: bool = False


class SocialOAuth:
    """Authlib provider registry and normalized, verified profile retrieval."""

    def __init__(self) -> None:
        self.oauth = OAuth()
        if GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET:
            self.oauth.register(
                name="google",
                client_id=GOOGLE_OAUTH_CLIENT_ID,
                client_secret=GOOGLE_OAUTH_CLIENT_SECRET,
                server_metadata_url=(
                    "https://accounts.google.com/.well-known/openid-configuration"
                ),
                client_kwargs={"scope": "openid email profile"},
            )
        if FACEBOOK_OAUTH_CLIENT_ID and FACEBOOK_OAUTH_CLIENT_SECRET:
            graph_base = f"https://graph.facebook.com/{FACEBOOK_GRAPH_VERSION}/"
            self.oauth.register(
                name="facebook",
                client_id=FACEBOOK_OAUTH_CLIENT_ID,
                client_secret=FACEBOOK_OAUTH_CLIENT_SECRET,
                authorize_url=(
                    f"https://www.facebook.com/{FACEBOOK_GRAPH_VERSION}/dialog/oauth"
                ),
                access_token_url=f"{graph_base}oauth/access_token",
                api_base_url=graph_base,
                client_kwargs={"scope": "email public_profile"},
            )

    def configured(self, provider: str) -> bool:
        name = (provider or "").casefold()
        return name in SUPPORTED_PROVIDERS and self.oauth.create_client(name) is not None

    def status(self) -> dict[str, bool]:
        return {name: self.configured(name) for name in SUPPORTED_PROVIDERS}

    def client(self, provider: str) -> Any:
        name = (provider or "").casefold()
        if name not in SUPPORTED_PROVIDERS:
            raise AccountError("Nhà cung cấp đăng nhập không được hỗ trợ.")
        client = self.oauth.create_client(name)
        if client is None:
            raise AccountError(
                f"Đăng nhập {name.title()} chưa được cấu hình Client ID/Secret."
            )
        return client

    async def authorize_redirect(
        self, provider: str, request: Any, redirect_uri: str
    ) -> Any:
        return await self.client(provider).authorize_redirect(request, redirect_uri)

    async def fetch_profile(self, provider: str, request: Any) -> SocialProfile:
        name = (provider or "").casefold()
        client = self.client(name)
        token = await client.authorize_access_token(request)
        if name == "google":
            userinfo = dict(token.get("userinfo") or {})
            provider_id = str(userinfo.get("sub") or "")
            verified = bool(userinfo.get("email_verified"))
            if not provider_id or not verified:
                raise AccountError("Google chưa xác minh được email của tài khoản này.")
            return SocialProfile(
                provider="google",
                provider_user_id=provider_id,
                display_name=str(userinfo.get("name") or "Google Learner"),
                email=str(userinfo.get("email") or "") or None,
                email_verified=True,
            )

        response = await client.get(
            "me", params={"fields": "id,name,email"}, token=token
        )
        response.raise_for_status()
        userinfo = response.json()
        provider_id = str(userinfo.get("id") or "")
        if not provider_id:
            raise AccountError("Facebook chưa trả về danh tính hợp lệ.")
        # Facebook verifies ownership of the account through OAuth. The email
        # field is optional and may be absent depending on the Facebook account.
        return SocialProfile(
            provider="facebook",
            provider_user_id=provider_id,
            display_name=str(userinfo.get("name") or "Facebook Learner"),
            email=str(userinfo.get("email") or "") or None,
            # Meta's basic profile response does not include an explicit
            # email_verified claim, so do not infer it merely from presence.
            email_verified=False,
        )


class OAuthLoginCodeManager:
    """Short-lived, one-time bridge from OAuth callback to the Gradio session."""

    def __init__(self, lifetime_minutes: int = 3) -> None:
        self.lifetime = timedelta(minutes=max(1, min(lifetime_minutes, 10)))
        self._codes: dict[str, tuple[str, Account, datetime]] = {}
        self._lock = threading.RLock()

    def create(self, session_token: str, account: Account) -> str:
        code = secrets.token_urlsafe(32)
        with self._lock:
            self._purge_expired()
            self._codes[code] = (
                session_token,
                account,
                datetime.now(UTC) + self.lifetime,
            )
        return code

    def consume(self, code: str) -> tuple[str, Account] | None:
        with self._lock:
            self._purge_expired()
            record = self._codes.pop(code or "", None)
            return (record[0], record[1]) if record else None

    def _purge_expired(self) -> None:
        now = datetime.now(UTC)
        expired = [code for code, (*_, until) in self._codes.items() if until <= now]
        for code in expired:
            self._codes.pop(code, None)
