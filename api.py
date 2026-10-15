"""FastAPI surface shared by web clients and the future Kotlin app."""

from __future__ import annotations

import logging
import secrets
import time
from html import escape
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlencode

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import FileResponse, HTMLResponse, RedirectResponse

from ai.llm import LocalAIError, OllamaLLM
from auth import (
    Account,
    AccountError,
    AuthSessionManager,
    OAuthLoginCodeManager,
    PostgreSQLAccountStore,
    SocialOAuth,
)
from auth.runtime import ensure_local_postgres
from config.settings import (
    API_HOST,
    APP_ICON_PATH,
    API_PORT,
    API_TOKEN,
    AUTH_REQUIRED,
    DATABASE_PATH,
    MODEL_NAME,
    OAUTH_PUBLIC_BASE_URL,
    OAUTH_SESSION_SECRET,
    WEB_PUBLIC_BASE_URL,
    TTS_MAX_CHARACTERS,
)
from database import DatabaseError, TutorDatabase
from services import conversation, exercises, grammar, roleplay, skill_analysis, vocabulary
from services.study_hub import (
    StudyHub,
    StudyHubError,
    attachment_limit_bytes,
    create_backup,
    export_profile,
)
from services.local_tts import LocalTTSError
from services.voice_engine import get_speech_engine
from services.image_gen import ImageGenError, ImageGenService
from services.vision import VisionError, VisionService
from services.visual_search import VisualSearchError, VisualSearchService
from services.web_search import WebSearchError, WebSearchService


database = TutorDatabase(DATABASE_PATH)
database.initialize()
llm = OllamaLLM()
study_hub = StudyHub(database, llm)
visual_search_service = VisualSearchService()
vision_service = VisionService()
web_search_service = WebSearchService()
speech_engine = get_speech_engine()
imagegen_service = ImageGenService()
ensure_local_postgres()
account_store = PostgreSQLAccountStore()
auth_sessions = AuthSessionManager()
social_oauth = SocialOAuth()
social_login_codes = OAuthLoginCodeManager()
try:
    account_store.initialize()
except AccountError:
    pass

app = FastAPI(
    title="Tris AI Local API",
    version="1.3.0",
    description="Local-first REST API for Gradio and Kotlin clients.",
)
app.add_middleware(
    SessionMiddleware,
    secret_key=OAUTH_SESSION_SECRET or secrets.token_urlsafe(48),
    same_site="lax",
    https_only=OAUTH_PUBLIC_BASE_URL.startswith("https://"),
    max_age=600,
)


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> FileResponse:
    return FileResponse(APP_ICON_PATH, media_type="image/x-icon")


def require_api_token(x_api_token: Annotated[str | None, Header()] = None) -> None:
    if API_TOKEN and x_api_token != API_TOKEN:
        raise HTTPException(status_code=401, detail="API token không hợp lệ.")


def bearer_account(authorization: str | None) -> Account | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    return auth_sessions.get(authorization.removeprefix("Bearer ").strip())


def require_access(
    x_api_token: Annotated[str | None, Header()] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    require_api_token(x_api_token)
    if AUTH_REQUIRED and bearer_account(authorization) is None:
        raise HTTPException(status_code=401, detail="Bạn cần đăng nhập tài khoản.")


Protected = Annotated[None, Depends(require_api_token)]


def user_id_for(name: str) -> int:
    return database.get_or_create_user(" ".join(name.split())[:50] or "Local Learner")


def learner_context_for(user_id: int) -> tuple[list, str]:
    preferences = database.get_user_preferences(user_id)
    insights = (
        database.get_skill_insights(user_id)
        if preferences.adaptive_intelligence
        else []
    )
    parts = [skill_analysis.build_learner_context(insights)] if insights else []
    parts.append(
        "Respond and explain in English unless the learner asks otherwise."
        if preferences.language == "en"
        else "Giải thích bằng tiếng Việt, nhưng giữ ví dụ và phần luyện tập tiếng Anh."
    )
    return insights, "\n\n".join(parts)


def safe_call(function: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        return function(*args, **kwargs)
    except (DatabaseError, LocalAIError, StudyHubError, exercises.ExerciseError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class ChatRequest(BaseModel):
    learner_name: str = "Local Learner"
    mode: Literal["Conversation", "Grammar", "Vocabulary", "Role Play"] = "Conversation"
    scenario: str = "Coffee Shop"
    message: str = Field(min_length=1, max_length=4000)
    web_search: bool = False


class WebSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=400)
    max_results: int = Field(default=5, ge=1, le=10)


class MediaGenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=1000)
    mode: Literal["image", "gif", "video"] = "image"
    frames: int = Field(default=6, ge=2, le=16)


class ExerciseRequest(BaseModel):
    learner_name: str = "Local Learner"
    skill: str = exercises.AUTO_SKILL
    difficulty: str = "Adaptive"
    question_count: Literal[3, 5, 10] = 5
    document_ids: list[int] = Field(default_factory=list)


class AnswerItem(BaseModel):
    question_id: int
    answer: str


class SubmitRequest(BaseModel):
    learner_name: str = "Local Learner"
    answers: list[AnswerItem]


class GoalRequest(BaseModel):
    daily_question_goal: int = Field(ge=1, le=200)


class RAGRequest(BaseModel):
    learner_name: str = "Local Learner"
    question: str = Field(min_length=1, max_length=4000)
    document_ids: list[int] = Field(default_factory=list)


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=10, max_length=128)
    learner_name: str = Field(default="Local Learner", min_length=1, max_length=50)


class LoginRequest(BaseModel):
    username: str
    password: str


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10, max_length=128)


class PreferencesRequest(BaseModel):
    theme: Literal["system", "light", "dark"] = "system"
    interface_language: Literal["vi", "en"] = "vi"
    language: Literal["vi", "en"] = "vi"
    adaptive_intelligence: bool = True
    voice_input: bool = False
    voice_output: bool = False


class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=TTS_MAX_CHARACTERS)
    language: Literal["vi", "en"] = "vi"


@app.get("/health")
def health() -> dict:
    from services.local_stt import get_local_stt
    from services.ollama_runtime import (
        choose_model,
        current_ollama_host,
        installed_model_names,
    )
    ollama_host = current_ollama_host()
    ollama_models = installed_model_names(ollama_host, attempts=1)
    ready_model = choose_model(MODEL_NAME, ollama_models, MODEL_NAME)
    return {
        "status": "ok" if ready_model else "degraded",
        "version": "1.3.0",
        "storage": "local",
        "local_ai": {
            "ready": bool(ready_model),
            "model": ready_model or MODEL_NAME,
            "host": ollama_host,
        },
        "postgres_accounts": account_store.configured,
        "auth_required": AUTH_REQUIRED,
        "social_login": social_oauth.status(),
        "local_tts": {
            "vi": speech_engine.available("vi"),
            "en": speech_engine.available("en"),
        },
        "local_stt": get_local_stt().status(),
    }


@app.post("/v1/speech", dependencies=[Depends(require_access)])
def create_speech(request: SpeechRequest) -> FileResponse:
    """Synthesize a bounded local mascot response for web or Kotlin clients."""
    try:
        audio_path = speech_engine.synthesize(request.text, request.language)
    except LocalTTSError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return FileResponse(
        audio_path,
        media_type="audio/wav",
        filename="tris-ai-response.wav",
    )


@app.post("/v1/auth/register", dependencies=[Depends(require_api_token)])
def register(request: RegisterRequest) -> dict:
    try:
        account_store.initialize()
        account = account_store.register(
            request.username, request.password, request.learner_name
        )
        database.get_or_create_user(account.learner_name)
        token = auth_sessions.create(account)
        return {
            "access_token": token,
            "token_type": "bearer",
            "account": account.__dict__,
        }
    except (AccountError, DatabaseError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/v1/auth/login", dependencies=[Depends(require_api_token)])
def login(request: LoginRequest) -> dict:
    try:
        account = account_store.authenticate(request.username, request.password)
        return {
            "access_token": auth_sessions.create(account),
            "token_type": "bearer",
            "account": account.__dict__,
        }
    except AccountError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@app.get("/v1/auth/me", dependencies=[Depends(require_api_token)])
def me(authorization: Annotated[str | None, Header()] = None) -> dict:
    account = bearer_account(authorization)
    if account is None:
        raise HTTPException(status_code=401, detail="Phiên đăng nhập không hợp lệ.")
    return {"account": account.__dict__}


@app.post("/v1/auth/change-password", dependencies=[Depends(require_api_token)])
def change_password(
    request: PasswordChangeRequest,
    authorization: Annotated[str | None, Header()] = None,
) -> dict:
    account = bearer_account(authorization)
    if account is None:
        raise HTTPException(status_code=401, detail="Hãy đăng nhập trước.")
    try:
        account_store.change_password(
            account.account_id, request.current_password, request.new_password
        )
        return {"status": "password_changed"}
    except AccountError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/v1/auth/logout", dependencies=[Depends(require_api_token)])
def logout(authorization: Annotated[str | None, Header()] = None) -> dict:
    if authorization and authorization.startswith("Bearer "):
        auth_sessions.revoke(authorization.removeprefix("Bearer ").strip())
    return {"status": "logged_out"}


def _finish_browser_login(account: Account) -> RedirectResponse:
    database.get_or_create_user(account.learner_name)
    session_token = auth_sessions.create(account)
    one_time_code = social_login_codes.create(session_token, account)
    query = urlencode({"oauth_code": one_time_code, "provider": account.auth_provider})
    return RedirectResponse(f"{WEB_PUBLIC_BASE_URL}/?{query}", status_code=303)


def _auth_page(kind: str, csrf_token: str, error: str = "") -> str:
    is_login = kind == "login"
    title = "Đăng nhập" if is_login else "Tạo tài khoản"
    other_label = "Tạo tài khoản mới" if is_login else "Đã có tài khoản? Đăng nhập"
    other_path = "register" if is_login else "login"
    learner_field = "" if is_login else (
        '<label>Tên hồ sơ học<input name="learner_name" maxlength="50" '
        'value="Local Learner" required></label>'
    )
    confirm_field = "" if is_login else (
        '<label>Nhập lại mật khẩu<input name="confirm_password" '
        'type="password" minlength="10" maxlength="128" required></label>'
    )
    oauth_status = social_oauth.status()
    social_buttons = []
    # Facebook support remains in the backend but stays out of the interface
    # until its separate provider setup is completed.
    for provider, label in (("google", "Google"),):
        if oauth_status[provider]:
            social_buttons.append(
                f'<a class="social" href="/v1/auth/oauth/{provider}/start">'
                f'Tiếp tục với {label}</a>'
            )
        else:
            social_buttons.append(
                f'<span class="social disabled">{label} chưa cấu hình</span>'
            )
    error_html = f'<div class="error">{escape(error)}</div>' if error else ""
    return f"""<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<link rel="icon" type="image/x-icon" href="/favicon.ico">
<title>{title} · Tris AI</title><style>
*{{box-sizing:border-box}} body{{margin:0;font-family:Inter,Segoe UI,sans-serif;background:#f7f7f8;color:#171717}}
.top{{height:68px;display:flex;align-items:center;justify-content:space-between;padding:0 28px;border-bottom:1px solid #e5e5e5;background:white}}
.brand{{font-weight:700;text-decoration:none;color:#171717}} .back{{color:#555;text-decoration:none}}
.wrap{{min-height:calc(100vh - 68px);display:grid;place-items:center;padding:32px 16px}}
.card{{width:min(440px,100%);background:white;border:1px solid #dedede;border-radius:22px;padding:32px;box-shadow:0 18px 60px rgba(0,0,0,.07)}}
h1{{font-size:28px;margin:0 0 8px}} .sub{{color:#666;margin:0 0 24px}}
label{{display:block;font-size:14px;font-weight:600;margin:14px 0}} input{{width:100%;margin-top:7px;padding:13px 14px;border:1px solid #ccc;border-radius:11px;font-size:15px}}
button,.social{{width:100%;display:block;padding:13px 14px;border-radius:999px;text-align:center;text-decoration:none;font-weight:650;margin-top:12px}}
button{{border:0;background:#171717;color:white;cursor:pointer}} .social{{border:1px solid #d1d1d1;color:#222;background:white}}
.disabled{{color:#999;background:#f2f2f2}} .or{{display:flex;align-items:center;gap:12px;color:#888;margin:20px 0 10px}} .or:before,.or:after{{content:'';height:1px;background:#ddd;flex:1}}
.switch{{display:block;text-align:center;margin-top:20px;color:#333}} .error{{padding:11px;border-radius:10px;background:#fee2e2;color:#991b1b;margin:14px 0}}
</style></head><body><header class="top"><a class="brand" href="{WEB_PUBLIC_BASE_URL}">Tris AI · {escape(MODEL_NAME)}</a><a class="back" href="{WEB_PUBLIC_BASE_URL}">← Trở về chat</a></header>
<main class="wrap"><section class="card"><h1>{title}</h1><p class="sub">Tài khoản được bảo vệ trong PostgreSQL local.</p>{error_html}
{''.join(social_buttons)}<div class="or">hoặc</div>
<form method="post" action="/auth/{kind}"><input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
<label>Tên đăng nhập<input name="username" minlength="3" maxlength="32" autocomplete="username" required></label>
{learner_field}<label>Mật khẩu<input name="password" type="password" minlength="10" maxlength="128" autocomplete="{'current-password' if is_login else 'new-password'}" required></label>
{confirm_field}<button type="submit">{title}</button></form>
<a class="switch" href="/auth/{other_path}">{other_label}</a></section></main></body></html>"""


@app.get("/auth/login", response_class=HTMLResponse)
def login_page(request: Request) -> HTMLResponse:
    token = secrets.token_urlsafe(24)
    request.session["auth_form_csrf"] = token
    return HTMLResponse(_auth_page("login", token))


@app.post("/auth/login")
def login_page_submit(
    request: Request,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    csrf_token: Annotated[str, Form()],
):
    expected = request.session.pop("auth_form_csrf", "")
    if not expected or not secrets.compare_digest(expected, csrf_token):
        return HTMLResponse(_auth_page("login", "", "Phiên biểu mẫu đã hết hạn."), 400)
    try:
        return _finish_browser_login(account_store.authenticate(username, password))
    except AccountError as exc:
        fresh = secrets.token_urlsafe(24)
        request.session["auth_form_csrf"] = fresh
        return HTMLResponse(_auth_page("login", fresh, str(exc)), 401)


@app.get("/auth/register", response_class=HTMLResponse)
def register_page(request: Request) -> HTMLResponse:
    token = secrets.token_urlsafe(24)
    request.session["auth_form_csrf"] = token
    return HTMLResponse(_auth_page("register", token))


@app.post("/auth/register")
def register_page_submit(
    request: Request,
    username: Annotated[str, Form()],
    learner_name: Annotated[str, Form()],
    password: Annotated[str, Form()],
    confirm_password: Annotated[str, Form()],
    csrf_token: Annotated[str, Form()],
):
    expected = request.session.pop("auth_form_csrf", "")
    if not expected or not secrets.compare_digest(expected, csrf_token):
        return HTMLResponse(_auth_page("register", "", "Phiên biểu mẫu đã hết hạn."), 400)
    try:
        if password != confirm_password:
            raise AccountError("Hai lần nhập mật khẩu chưa khớp.")
        account_store.initialize()
        return _finish_browser_login(
            account_store.register(username, password, learner_name)
        )
    except (AccountError, DatabaseError) as exc:
        fresh = secrets.token_urlsafe(24)
        request.session["auth_form_csrf"] = fresh
        return HTMLResponse(_auth_page("register", fresh, str(exc)), 400)


@app.get("/v1/auth/oauth/status")
def oauth_status() -> dict:
    """Public capability check; never exposes OAuth secrets."""
    return {
        "providers": social_oauth.status(),
        "redirect_uris": {
            provider: (
                f"{OAUTH_PUBLIC_BASE_URL}/v1/auth/oauth/{provider}/callback"
            )
            for provider in ("google", "facebook")
        },
    }


@app.get("/v1/auth/oauth/{provider}/start")
async def oauth_start(provider: str, request: Request):
    """Start browser OAuth; Authlib stores anti-CSRF state in a signed cookie."""
    name = provider.casefold()
    try:
        redirect_uri = f"{OAUTH_PUBLIC_BASE_URL}/v1/auth/oauth/{name}/callback"
        return await social_oauth.authorize_redirect(name, request, redirect_uri)
    except AccountError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/v1/auth/oauth/{provider}/callback")
async def oauth_callback(provider: str, request: Request):
    """Verify provider response, create local account, then return to Gradio."""
    name = provider.casefold()
    try:
        profile = await social_oauth.fetch_profile(name, request)
        account_store.initialize()
        account = account_store.authenticate_social(
            profile.provider,
            profile.provider_user_id,
            profile.email,
            profile.email_verified,
            profile.display_name,
        )
        return _finish_browser_login(account)
    except Exception as exc:
        # Provider/transport details can contain secrets; log server-side and
        # redirect with a short reason so the UI can guide the fix.
        logging.getLogger("uvicorn.error").warning(
            "OAuth %s failed: %s: %s", name, type(exc).__name__, exc
        )
        reason = "credentials"
        text = str(exc).lower()
        if "state" in text:
            reason = "state"
        elif "redirect" in text:
            reason = "redirect"
        elif "email" in text or "verify" in text:
            reason = "email"
        query = urlencode({"oauth_error": name or "unknown", "oauth_reason": reason})
        return RedirectResponse(f"{WEB_PUBLIC_BASE_URL}/?{query}", status_code=302)


@app.post("/v1/chat", dependencies=[Depends(require_access)])
def chat(request: ChatRequest) -> dict:
    started_at = time.perf_counter()
    user_id = safe_call(user_id_for, request.learner_name)
    scenario = request.mode == "Role Play" and request.scenario or ""
    history = safe_call(database.load_history, user_id, request.mode, scenario, 20)
    _, context = safe_call(learner_context_for, user_id)
    web_citations = []
    if request.web_search:
        try:
            web_result = web_search_service.gather(request.message)
            if web_result.sources:
                context += (
                    "\n\n[KẾT QUẢ TÌM KIẾM WEB — chỉ dùng khi liên quan, "
                    "trích nguồn dạng [W1], [W2] sau mỗi ý lấy từ web]\n"
                    + web_result.context_block
                )
                web_citations = [
                    {
                        "label": source["label"],
                        "title": source["title"],
                        "url": source["url"],
                    }
                    for source in web_result.sources
                ]
        except WebSearchError:
            context += "\n\n[Thông báo: tìm kiếm web không thành công, hãy trả lời như bình thường.]"
    if request.mode == "Grammar":
        answer = safe_call(grammar.respond, llm, history, request.message, context)
    elif request.mode == "Vocabulary":
        answer = safe_call(vocabulary.respond, llm, history, request.message, context)
    elif request.mode == "Role Play":
        answer = safe_call(
            roleplay.respond, llm, history, request.message, request.scenario, context
        )
    else:
        answer = safe_call(conversation.respond, llm, history, request.message, context)
    safe_call(database.save_exchange, user_id, request.mode, scenario, request.message, answer)
    elapsed = max(0, int(round(time.perf_counter() - started_at)))
    minutes, seconds = divmod(elapsed, 60)
    return {
        "answer": answer,
        "mode": request.mode,
        "learner_id": user_id,
        "web_search_used": bool(web_citations),
        "web_sources": web_citations,
        "processing_seconds": elapsed,
        "processing_label": f"Đã xử lý trong {minutes} phút {seconds} giây",
    }


@app.post("/v1/web-search", dependencies=[Depends(require_access)])
def web_search(request: WebSearchRequest) -> dict:
    """Search DuckDuckGo and return cited hits for web/Kotlin clients."""
    try:
        hits = web_search_service.search(request.query, request.max_results)
    except WebSearchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"query": request.query, "results": hits}


@app.post("/v1/media-generate", dependencies=[Depends(require_access)])
def media_generate(request: MediaGenerateRequest) -> dict:
    """Create an image, GIF or short video fully locally."""
    try:
        path = imagegen_service.generate(
            request.prompt, mode=request.mode, frames=request.frames
        )
    except ImageGenError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "file_name": path.name,
        "file_url": f"/v1/media/{path.name}",
        "mode": request.mode,
    }


@app.get("/v1/media/{file_name}", dependencies=[Depends(require_access)])
def media_file(file_name: str) -> FileResponse:
    """Serve one previously generated media file by safe name lookup."""
    from services.image_gen import GENERATED_DIR

    safe = Path(file_name).name
    path = GENERATED_DIR / safe
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Không tìm thấy tệp đã tạo.")
    media_types = {
        ".png": "image/png",
        ".gif": "image/gif",
        ".mp4": "video/mp4",
    }
    media_type = media_types.get(path.suffix.casefold(), "application/octet-stream")
    return FileResponse(path, media_type=media_type, filename=safe)


@app.get("/v1/learners/{learner_name}/settings", dependencies=[Depends(require_access)])
def get_learner_settings(learner_name: str) -> dict:
    user_id = safe_call(user_id_for, learner_name)
    preferences = safe_call(database.get_user_preferences, user_id)
    return {"learner_id": user_id, "settings": preferences.__dict__}


@app.put("/v1/learners/{learner_name}/settings", dependencies=[Depends(require_access)])
def update_learner_settings(
    learner_name: str, request: PreferencesRequest
) -> dict:
    user_id = safe_call(user_id_for, learner_name)
    preferences = safe_call(
        database.save_user_preferences,
        user_id,
        request.theme,
        request.interface_language,
        request.language,
        request.adaptive_intelligence,
        request.voice_input,
        request.voice_output,
    )
    return {"learner_id": user_id, "settings": preferences.__dict__}


@app.post("/v1/exercises", dependencies=[Depends(require_access)])
def create_exercise(request: ExerciseRequest) -> dict:
    user_id = safe_call(user_id_for, request.learner_name)
    insights, context = safe_call(learner_context_for, user_id)
    selected_skill = exercises.choose_skill(request.skill, insights)
    if request.document_ids:
        chunks = safe_call(database.get_document_chunks, user_id, request.document_ids)
        source_context = "\n\n".join(str(chunk["content"]) for chunk in chunks[:8])
        context += (
            "\n\nCreate questions using only this selected learning material:\n"
            + source_context[:7000]
        )
    questions = safe_call(
        exercises.generate_questions,
        llm,
        selected_skill,
        request.difficulty,
        request.question_count,
        context,
    )
    session_id, stored = safe_call(
        database.create_exercise_session,
        user_id,
        selected_skill,
        request.difficulty,
        questions,
    )
    public_questions = [
        {key: value for key, value in item.items() if key not in {"correct_answer", "accepted_answers", "explanation_vi"}}
        for item in stored
    ]
    return {"session_id": session_id, "questions": public_questions}


@app.post("/v1/exercises/{session_id}/submit", dependencies=[Depends(require_access)])
def submit_exercise(session_id: int, request: SubmitRequest) -> dict:
    user_id = safe_call(user_id_for, request.learner_name)
    session = safe_call(database.get_exercise_session, user_id, session_id)
    answer_map = {item.question_id: item.answer for item in request.answers}
    attempts = []
    results = []
    for question in session["questions"]:
        question_id = int(question["question_id"])
        if question_id not in answer_map:
            raise HTTPException(status_code=400, detail="Bạn cần trả lời đủ tất cả câu.")
        answer = answer_map[question_id]
        correct = exercises.check_answer(question, answer)
        attempts.append(
            {"question_id": question_id, "user_answer": answer, "is_correct": correct, "skill": question["skill"]}
        )
        results.append(
            {
                "question_id": question_id,
                "is_correct": correct,
                "correct_answer": question["correct_answer"],
                "explanation_vi": question["explanation_vi"],
            }
        )
    safe_call(database.submit_exercise_session, user_id, session_id, attempts)
    return {"session_id": session_id, "correct_count": sum(item["is_correct"] for item in results), "total": len(results), "results": results}


@app.get("/v1/learners/{learner_name}/progress", dependencies=[Depends(require_access)])
def progress(learner_name: str) -> dict:
    user_id = safe_call(user_id_for, learner_name)
    stats = safe_call(database.get_exercise_stats, user_id)
    return {
        "exercise": {
            "sessions": stats.completed_sessions,
            "attempts": stats.total_attempts,
            "correct": stats.correct_attempts,
            "accuracy_percent": stats.accuracy_percent,
        },
        "daily_goal": safe_call(database.get_daily_goal, user_id),
        "days": [item.__dict__ | {"accuracy_percent": item.accuracy_percent} for item in safe_call(database.get_daily_progress, user_id, 30)],
        "skills": [item.__dict__ | {"level": item.level, "accuracy_percent": item.accuracy_percent} for item in safe_call(database.get_skill_insights, user_id, 20)],
    }


@app.put("/v1/learners/{learner_name}/goal", dependencies=[Depends(require_access)])
def set_goal(learner_name: str, request: GoalRequest) -> dict:
    user_id = safe_call(user_id_for, learner_name)
    return {"daily_question_goal": safe_call(database.set_daily_goal, user_id, request.daily_question_goal)}


@app.get("/v1/learners/{learner_name}/history", dependencies=[Depends(require_access)])
def history(learner_name: str) -> dict:
    user_id = safe_call(user_id_for, learner_name)
    return {"sessions": safe_call(database.list_exercise_history, user_id, 50)}


@app.get("/v1/learners/{learner_name}/review/{kind}", dependencies=[Depends(require_access)])
def review(learner_name: str, kind: Literal["wrong", "flagged", "weak"] = "wrong") -> dict:
    user_id = safe_call(user_id_for, learner_name)
    return {"questions": safe_call(database.get_review_questions, user_id, kind, 20)}


@app.get("/v1/documents/{learner_name}", dependencies=[Depends(require_access)])
def documents(learner_name: str) -> dict:
    user_id = safe_call(user_id_for, learner_name)
    return {"documents": safe_call(database.list_documents, user_id)}


@app.post("/v1/documents/{learner_name}", dependencies=[Depends(require_access)])
async def upload_document(
    learner_name: str,
    file: Annotated[UploadFile, File()],
) -> dict:
    from config.settings import PROJECT_ROOT

    user_id = safe_call(user_id_for, learner_name)
    temporary_dir = PROJECT_ROOT / "data" / "uploads"
    temporary_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(file.filename or "document.txt").name
    try:
        size_limit = attachment_limit_bytes(safe_name)
    except StudyHubError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    temporary_path = temporary_dir / f"{secrets.token_hex(8)}-{safe_name}"
    written = 0
    try:
        with temporary_path.open("wb") as destination:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > size_limit:
                    raise HTTPException(
                        status_code=413,
                        detail="Tệp tải lên vượt giới hạn cho định dạng này.",
                    )
                destination.write(chunk)
        return safe_call(
            study_hub.ingest, user_id, temporary_path, Path(safe_name).stem
        )
    finally:
        await file.close()
        temporary_path.unlink(missing_ok=True)


@app.post("/v1/visual-search", dependencies=[Depends(require_access)])
async def visual_search(
    file: Annotated[UploadFile, File()],
    allow_external: Annotated[bool, Form()] = False,
) -> dict:
    """Search from an image; external transmission requires an explicit flag."""
    from config.settings import PROJECT_ROOT

    safe_name = Path(file.filename or "image.png").name
    try:
        size_limit = attachment_limit_bytes(safe_name)
    except StudyHubError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    temporary_dir = PROJECT_ROOT / "data" / "uploads"
    temporary_dir.mkdir(parents=True, exist_ok=True)
    temporary_path = temporary_dir / f"{secrets.token_hex(8)}-{safe_name}"
    written = 0
    try:
        with temporary_path.open("wb") as destination:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > size_limit:
                    raise HTTPException(status_code=413, detail="Ảnh vượt giới hạn tải lên.")
                destination.write(chunk)
        try:
            result = visual_search_service.search(temporary_path, allow_external)
        except VisualSearchError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return result.as_dict()
    finally:
        await file.close()
        temporary_path.unlink(missing_ok=True)


@app.post("/v1/rag/ask", dependencies=[Depends(require_access)])
def rag_ask(request: RAGRequest) -> dict:
    user_id = safe_call(user_id_for, request.learner_name)
    return safe_call(study_hub.ask, user_id, request.question, request.document_ids or None)


@app.post("/v1/maintenance/backup", dependencies=[Depends(require_access)])
def backup() -> dict:
    return {"path": str(safe_call(create_backup))}


@app.get("/v1/learners/{learner_name}/export", dependencies=[Depends(require_access)])
def export(learner_name: str) -> dict:
    user_id = safe_call(user_id_for, learner_name)
    return {"path": str(safe_call(export_profile, database, user_id))}


def main() -> None:
    import uvicorn

    uvicorn.run("api:app", host=API_HOST, port=API_PORT, reload=False)


if __name__ == "__main__":
    main()
