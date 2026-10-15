"""Authenticated bridges to the tutor features and data that predate React."""
from __future__ import annotations
import hashlib
import threading
import time
from collections import defaultdict
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse
from config.settings import DEFAULT_LEARNER_NAME, SHUTDOWN_GRACE_SECONDS
from services import exercises
from services.session_watchdog import SessionWatchdog


class QuizRequest(BaseModel):
    skill: str = exercises.AUTO_SKILL
    difficulty: Literal["Easy", "Medium", "Hard", "Adaptive"] = "Adaptive"
    question_count: Literal[3, 5, 10] = 5
    document_ids: list[int] = Field(default_factory=list, max_length=20)


class QuizAnswer(BaseModel):
    question_id: int
    answer: str = Field(max_length=2000)


class QuizSubmission(BaseModel):
    answers: list[QuizAnswer] = Field(max_length=10)


class FlagRequest(BaseModel):
    flagged: bool


class GoalRequest(BaseModel):
    daily_question_goal: int = Field(ge=1, le=200)


class PresenceRequest(BaseModel):
    tab: str = Field(min_length=10, max_length=80)
    closed: bool = False


class PreferencesRequest(BaseModel):
    theme: Literal["system", "light", "dark"] = "system"
    interface_language: Literal["vi", "en"] = "vi"
    language: Literal["vi", "en"] = "vi"
    adaptive_intelligence: bool = True
    voice_input: bool = False
    voice_output: bool = False


def install_feature_routes(backend):
    router = APIRouter(prefix="/v1/workspace")
    def scope(authorization: str | None = Header(default=None), x_api_token: str | None = Header(default=None)):
        backend.require_access(x_api_token, authorization)
        account = backend.bearer_account(authorization)
        if authorization and not account:
            raise HTTPException(401, "Phiên đã hết hạn. Hãy đăng nhập lại.")
        return account.learner_name if account else DEFAULT_LEARNER_NAME

    @router.get("/session")
    def session(learner: str = Depends(scope)):
        user_id = backend.user_id_for(learner)
        groups = defaultdict(list)
        for row in backend.database.workspace_history(user_id):
            groups[(row["mode"], row["scenario"])].append(row)
        chats = []
        for (mode, scenario), rows in groups.items():
            if mode not in {"Conversation", "Grammar", "Vocabulary", "Role Play"}:
                continue
            key = hashlib.sha256(f"{user_id}:{mode}:{scenario}".encode()).hexdigest()[:20]
            chats.append({"id": "history-" + key, "title": f"{mode} · {scenario or learner}",
                          "mode": mode, "scenario": scenario, "draft": "", "project": "",
                          "demo": False, "created": rows[0]["created_at"],
                          "messages": [{"id": f"db-{row['id']}", "role": row["role"], "content": row["content"]} for row in rows]})
        return {"learner_name": learner, "chats": chats, "settings": backend.database.get_user_preferences(user_id).__dict__}

    @router.get("/study")
    def study(learner: str = Depends(scope)):
        return {**backend.progress(learner), "history": backend.history(learner)["sessions"],
                "documents": backend.documents(learner)["documents"],
                "skills_available": exercises.EXERCISE_SKILLS}

    @router.post("/exercises")
    def create_quiz(body: QuizRequest, learner: str = Depends(scope)):
        return backend.create_exercise(backend.ExerciseRequest(learner_name=learner, **body.model_dump()))

    @router.post("/exercises/{session_id}/submit")
    def submit_quiz(session_id: int, body: QuizSubmission, learner: str = Depends(scope)):
        return backend.submit_exercise(session_id, backend.SubmitRequest(learner_name=learner, answers=[item.model_dump() for item in body.answers]))

    @router.put("/exercises/{session_id}/questions/{question_id}/flag")
    def flag(session_id: int, question_id: int, body: FlagRequest, learner: str = Depends(scope)):
        user_id = backend.user_id_for(learner)
        item = backend.safe_call(backend.database.get_exercise_session, user_id, session_id)
        if not any(int(q["question_id"]) == question_id for q in item["questions"]):
            raise HTTPException(404, "Không tìm thấy câu hỏi trong bài.")
        backend.safe_call(backend.database.set_exercise_question_flag, user_id, session_id, question_id, body.flagged)
        return {"flagged": body.flagged}

    @router.post("/review/{kind}")
    def review(kind: Literal["wrong", "flagged", "weak"], learner: str = Depends(scope)):
        user_id = backend.user_id_for(learner)
        questions = backend.safe_call(backend.database.get_review_questions, user_id, kind, 10)
        if not questions:
            raise HTTPException(400, "Chưa có câu phù hợp để ôn tập.")
        session_id, stored = backend.safe_call(backend.database.create_exercise_session, user_id, "Review", "Adaptive", questions)
        hidden = {"correct_answer", "accepted_answers", "explanation_vi"}
        return {"session_id": session_id, "questions": [{k: v for k, v in q.items() if k not in hidden} for q in stored]}

    @router.put("/goal")
    def goal(body: GoalRequest, learner: str = Depends(scope)):
        return backend.set_goal(learner, backend.GoalRequest(**body.model_dump()))

    @router.get("/export")
    def export(learner: str = Depends(scope)):
        return JSONResponse(backend.database.export_learner_data(backend.user_id_for(learner)),
                            headers={"Content-Disposition": 'attachment; filename="tris-learner.json"'})

    @router.post("/backup")
    def backup(learner: str = Depends(scope)):
        # Same explicitly requested local SQLite backup operation as the old UI.
        return backend.backup()

    @router.put("/preferences")
    def preferences(body: PreferencesRequest, learner: str = Depends(scope)):
        return backend.update_learner_settings(learner, backend.PreferencesRequest(**body.model_dump()))

    @router.get("/preferences")
    def read_preferences(learner: str = Depends(scope)):
        return backend.get_learner_settings(learner)

    @router.get('/voice-status')
    def voice_status(learner: str = Depends(scope)):
        import httpx
        from config.settings import XTTS_SERVER_URL, TTS_ENGINE
        if TTS_ENGINE != 'clone':
            return {'engine':'piper','speaker':False,'reference_count':0,'notice':'Stock voice explicitly configured'}
        try:
            response = httpx.get(f'{XTTS_SERVER_URL.rstrip("/")}/health',timeout=5,trust_env=False)
            response.raise_for_status()
            payload=response.json()
            return {key:payload.get(key) for key in ('engine','speaker','reference_count','reference_revision','model_loaded','error','device','gpu_name','device_notice','last_conversion_seconds')}
        except (httpx.HTTPError, ValueError):
            return {'engine':'openvoice-v2','speaker':False,'reference_count':0,'error':'Giọng mẫu local chưa kết nối. Không tự thay giọng.'}

    # Preserve the old app's last-tab-close shutdown behavior without Gradio sessions.
    tabs = {}
    guard = threading.RLock()
    def expire():
        from services.image_gen import ImageGenService
        try:
            ImageGenService._unload_ollama_models()
        except Exception:
            pass
        stop = getattr(backend.app.state, "stop_server", None)
        if stop:
            stop()
    watchdog = SessionWatchdog(SHUTDOWN_GRACE_SECONDS, on_expire=expire)

    @router.post("/presence")
    def presence(body: PresenceRequest, request: Request):
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            raise HTTPException(403, "Origin không hợp lệ.")
        with guard:
            if body.closed:
                if tabs.pop(body.tab, None) is not None:
                    watchdog.disconnect()
            else:
                if body.tab not in tabs:
                    if len(tabs) >= 100:
                        raise HTTPException(429, "Quá nhiều tab.")
                    watchdog.connect()
                tabs[body.tab] = time.monotonic()
        return {"ok": True}

    def sweep():
        while True:
            time.sleep(20)
            with guard:
                for tab in list(tabs):
                    if time.monotonic() - tabs[tab] > 90:
                        tabs.pop(tab)
                        watchdog.disconnect()
    threading.Thread(target=sweep, name="tris-tab-watchdog", daemon=True).start()
    backend.app.include_router(router)
