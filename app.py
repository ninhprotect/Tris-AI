"""Gradio web interface for Tris AI v1.3."""

import base64
import os
import re
import socket
import threading
import time
from pathlib import Path
from typing import Any

import gradio as gr

from ai.llm import ChatMessage, LocalAIError, OllamaLLM
from auth import (
    AccountError,
    AuthSessionManager,
    OAuthLoginCodeManager,
    PostgreSQLAccountStore,
    SocialOAuth,
)
from auth.runtime import ensure_local_postgres
from config.settings import (
    APP_HOST,
    APP_ICON_PATH,
    APP_OPEN_BROWSER,
    APP_PORT,
    DATABASE_PATH,
    DEFAULT_LEARNER_NAME,
    MAX_ATTACHMENT_FILES,
    MAX_ATTACHMENT_TOTAL_BYTES,
    MAX_DOCUMENT_BYTES,
    MAX_HISTORY_MESSAGES,
    MAX_IMAGE_BYTES,
    MAX_VIDEO_BYTES,
    MODEL_NAME,
    OAUTH_PUBLIC_BASE_URL,
    SHUTDOWN_GRACE_SECONDS,
)
from database import DatabaseError, ExerciseStats, LearningStats, TutorDatabase
from services import conversation, exercises, grammar, roleplay, skill_analysis, vocabulary
from services.study_hub import (
    DocumentParser,
    IMAGE_SUFFIXES,
    StudyHub,
    StudyHubError,
    VIDEO_SUFFIXES,
    create_backup,
    export_profile,
    validate_attachment_batch,
)
from services.local_tts import LocalTTSError, tris_voice
from services.voice_engine import get_speech_engine
from services.voice_lines import VoiceLineService
from services.image_gen import ImageGenError, ImageGenService
from services.session_watchdog import SessionWatchdog
from services.vision import VisionError, VisionService
from services.visual_search import VisualSearchError, VisualSearchService
from services.web_search import WebSearchError, WebSearchService

MODE_CONVERSATION = "Conversation"
MODE_GRAMMAR = "Grammar"
MODE_VOCABULARY = "Vocabulary"
MODE_ROLEPLAY = "Role Play"
MODE_EXERCISES = "Exercises"
MODES = [
    MODE_CONVERSATION,
    MODE_GRAMMAR,
    MODE_VOCABULARY,
    MODE_ROLEPLAY,
    MODE_EXERCISES,
]
MAX_QUESTION_BUTTONS = max(exercises.QUESTION_COUNTS)
APP_CSS = """
/* ================= Tris AI Design System ================= */
:root {
  --tris-orange: #f97316;
  --tris-orange-deep: #ea580c;
  --tris-rose: #f43f5e;
  --tris-pink: #ec4899;
  --tris-grad: linear-gradient(120deg, #f97316, #f43f5e 55%, #ec4899);
  --tris-radius: 14px;
  --tris-radius-lg: 18px;
}

html, body, .gradio-container {
  font-family: "Segoe UI Variable Text", "Segoe UI", system-ui,
               -apple-system, "Helvetica Neue", Arial, sans-serif !important;
}

/* Thanh cuộn mảnh, mềm */
.gradio-container *::-webkit-scrollbar {width: 9px; height: 9px;}
.gradio-container *::-webkit-scrollbar-thumb {
  background: rgba(150, 135, 120, .35); border-radius: 999px;
  border: 2px solid transparent; background-clip: content-box;}
.gradio-container *::-webkit-scrollbar-thumb:hover {
  background: rgba(150, 135, 120, .6); background-clip: content-box;}
.gradio-container *::-webkit-scrollbar-track {background: transparent;}

/* ---------- HEADER ---------- */
#app-header {align-items: center; padding: 10px 4px 16px; margin-bottom: 8px;
             border-bottom: 0; position: relative;}
#app-header::after {content: ""; position: absolute; left: 2px; right: 2px; bottom: 0;
                    height: 2.5px; border-radius: 999px;
                    background: var(--tris-grad); opacity: .9;}
#brand-block, #brand-block * {color: var(--body-text-color) !important; opacity: 1 !important;}
#brand-block h3 {margin: 0 0 4px; font-size: 23px !important; font-weight: 800;
                 letter-spacing: .2px; line-height: 1.15;}
html.dark #brand-block h3, html.dark #brand-block h3 * {
  color: #fb923c !important;}
html:not(.dark) #brand-block h3, html:not(.dark) #brand-block h3 * {
  color: #ea580c !important;}
#brand-block code {display: inline-block; margin-top: 2px; padding: 3px 12px;
                   font-size: 11.5px !important; border-radius: 999px;
                   border: 1px solid var(--border-color-primary);
                   background: var(--block-background-fill) !important;}
#brand-icon {width: 50px !important; min-width: 50px !important; max-width: 50px !important;
             height: 50px !important; align-self: center; flex-grow: 0 !important;
             filter: drop-shadow(0 4px 12px rgba(249, 115, 22, .38));}
#brand-icon img {width: 46px; height: 46px; object-fit: contain; display: block;}
#header-actions {justify-content: flex-end; align-items: center; flex-grow: 0 !important;
                 width: 350px; min-width: 350px; gap: 10px;
                 flex-wrap: nowrap !important;}
#header-actions > * {flex: 1 1 0 !important; min-width: 0 !important; max-width: 46% !important;}
#header-actions a, #header-actions button {width: 100% !important; min-width: 0 !important;}
#header-account {display: flex !important; align-items: center; min-width: 0;
                 border: 0 !important; background: transparent !important;
                 box-shadow: none !important; padding: 0 !important;}
#header-account .prose {
  width: 100%; text-align: center; padding: 6px 12px; border-radius: 999px;
  border: 1.5px solid var(--tris-orange);
  background: linear-gradient(120deg, rgba(249, 115, 22, .14), rgba(236, 72, 153, .12));
  font-weight: 700; font-size: 13px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;}
#header-account .prose .prose {
  border: 0 !important; background: transparent !important;
  border-radius: 0 !important; padding: 0 !important; width: auto !important;}
#header-account .prose p {margin: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;}

/* ---------- NÚT ---------- */
.gradio-container button, #header-actions a {
  border-radius: 12px !important; font-weight: 600;
  transition: transform .12s ease, box-shadow .12s ease, filter .12s ease !important;}
.gradio-container button:hover, #header-actions a:hover {transform: translateY(-1px);}
.gradio-container button.primary, .gradio-container a.primary {
  background: var(--tris-grad) !important; border: 0 !important; color: #fff !important;
  box-shadow: 0 6px 16px rgba(244, 63, 94, .30) !important;}
.gradio-container button.primary:hover, .gradio-container a.primary:hover {
  filter: brightness(1.07);
  box-shadow: 0 8px 22px rgba(244, 63, 94, .42) !important;}
.gradio-container button.secondary, .gradio-container a.secondary {
  border: 1.5px solid var(--border-color-primary) !important;}

/* ---------- BO GÓC BLOCK ---------- */
.gradio-container .block, .gradio-container .form {
  border-radius: var(--tris-radius) !important;}
.gradio-container input, .gradio-container textarea {
  border-radius: 10px !important;}
.gradio-container input:focus, .gradio-container textarea:focus {
  box-shadow: 0 0 0 3px rgba(249, 115, 22, .18) !important;
  border-color: var(--tris-orange) !important;}
.gradio-container details, .gradio-container .accordion {
  border-radius: var(--tris-radius) !important; overflow: hidden;}

/* ---------- RADIO CHẾ ĐỘ HỌC (pill) ---------- */
label[data-testid$="-radio-label"] {
  border-radius: 999px !important; padding: 8px 15px !important;
  border: 1.5px solid var(--border-color-primary) !important;
  transition: border-color .15s ease, background .15s ease, box-shadow .15s ease;}
label[data-testid$="-radio-label"]:hover {border-color: var(--tris-orange) !important;}
label[data-testid$="-radio-label"].selected {
  border-color: transparent !important;
  background: linear-gradient(120deg, rgba(249,115,22,.16), rgba(236,72,153,.15)) !important;
  box-shadow: inset 0 0 0 1.6px var(--tris-orange);}
label[data-testid$="-radio-label"] input {accent-color: var(--tris-orange);}

/* ---------- KHUNG CHAT ---------- */
.chatbot {
  border-radius: var(--tris-radius-lg) !important;
  border: 1px solid var(--border-color-primary) !important;
  box-shadow: 0 10px 30px rgba(0, 0, 0, .10) !important;}
[data-testid="user"], [data-testid="bot"] {border-radius: 16px !important;}
[data-testid="bot"] {background: var(--block-background-fill) !important;}
[data-testid="user"] {
  background: linear-gradient(120deg, rgba(249,115,22,.15), rgba(236,72,153,.12)) !important;
  box-shadow: inset 0 0 0 1px rgba(249,115,22,.38);}

/* ---------- COMPOSER ---------- */
#composer-shell {width: 100% !important; max-width: 980px; margin: 0 auto;
                 align-self: center;}
#composer-shell .block, #composer-shell .form {border-radius: 16px !important;}
#composer-shell .block:focus-within, #composer-shell .form:focus-within {
  border-color: var(--tris-orange) !important;
  box-shadow: 0 0 0 3px rgba(249, 115, 22, .16) !important;}
#attachment-menu {max-width: 560px; margin: 0 auto 10px;
                  border-radius: var(--tris-radius) !important;}
[data-testid="submit-button"] {
  background: var(--tris-grad) !important; color: #fff !important;
  border: 0 !important; border-radius: 12px !important;
  box-shadow: 0 4px 12px rgba(244, 63, 94, .30) !important;}
[data-testid="submit-button"]:hover {filter: brightness(1.08);}

/* ---------- SIDEBAR CÀI ĐẶT ---------- */
#settings-panel {border-left: 1px solid var(--border-color-primary); padding: 14px 18px;
                 backdrop-filter: blur(6px);}
.settings-row {padding: 10px 0; border-bottom: 1px dashed var(--border-color-primary);}

/* ---------- BÀI TẬP ---------- */
#exercise-card {border: 1px solid var(--border-color-primary); border-radius: 18px;
                padding: 20px; background: var(--block-background-fill);
                box-shadow: 0 8px 24px rgba(0, 0, 0, .08);}
#exercise-options label {padding: 10px 14px; border-radius: 12px;}
#exercise-feedback {border-left: 4px solid var(--tris-orange); padding-left: 14px;
                    border-radius: 4px;}
#exercise-layout {align-items: flex-start; gap: 18px;}
#question-main {min-width: 0;}
#question-sidebar {border: 1px solid var(--border-color-primary); border-radius: 14px;
                   padding: 14px; align-self: flex-start;
                   background: linear-gradient(180deg,
                     rgba(249, 115, 22, .05), rgba(236, 72, 153, .04));}
.question-nav-button button {min-width: 42px; padding: 6px 4px; font-weight: 700;
                             border-radius: 10px !important;}
.question-nav-button button[aria-checked="true"],
.question-nav-button button.selected {background: var(--tris-grad) !important;
                                      color: #fff !important; border: 0 !important;}
#exercise-report {border: 1px solid #ef4444; border-left: 6px solid #dc2626;
                  border-radius: 14px; padding: 16px; background: rgba(239, 68, 68, .08);}

/* ---------- GIỌNG LINH VẬT ---------- */
#mascot-audio {width: 74px !important; min-width: 74px !important;
               max-width: 74px !important; height: 58px !important;
               border: 0 !important; overflow: visible !important;
               margin: 2px 0 8px 10px !important; padding: 0 !important;}
#mascot-audio label, #mascot-audio .icon-button-wrapper,
#mascot-audio .waveform-container, #mascot-audio .timestamps,
#mascot-audio .subtitle-display, #mascot-audio .control-wrapper,
#mascot-audio .rewind, #mascot-audio .skip {display: none !important;}
#mascot-audio .component-wrapper, #mascot-audio .controls,
#mascot-audio .play-pause-wrapper {width: 74px !important; height: 58px !important;
                                  min-height: 58px !important; margin: 0 !important;
                                  padding: 0 !important; display: flex !important;
                                  align-items: center !important; justify-content: center !important;}
#mascot-audio .play-pause-button {width: 64px !important; height: 52px !important;
                                  border: 0 !important; background: transparent !important;
                                  box-shadow: none !important; color: #f43f72 !important;
                                  position: relative !important; overflow: visible !important;}
#mascot-audio .play-pause-button svg {display: none !important;}
#mascot-audio .play-pause-button::before {content: "🔊"; font-size: 30px; line-height: 1;}
#mascot-audio .play-pause-button::after {content: ")))"; position: absolute; left: 45px;
                                          top: 16px; font-size: 17px; letter-spacing: -5px;
                                          transform-origin: left center; opacity: .75;}
#mascot-audio .play-pause-button:hover::after,
#mascot-audio .play-pause-button[aria-label="Pause"]::after {
  animation: tris-sound-wave .85s ease-in-out infinite;
}
#mascot-audio .play-pause-button:hover {transform: scale(1.06);}
@keyframes tris-sound-wave {
  0%, 100% {transform: scaleX(.55) scaleY(.72); opacity: .4;}
  50% {transform: scaleX(1.18) scaleY(1.15); opacity: 1;}
}

/* ---------- CHECKBOX ---------- */
input[data-testid="checkbox"] {
  border: 1px solid var(--border-color-primary) !important;
  background-color: transparent !important;}
input[data-testid="checkbox"]:checked {
  border-color: #f97316 !important;
  background-color: #f97316 !important;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Cpath d='M3 8.5 6.5 12 13 4.5' fill='none' stroke='white' stroke-width='2.2' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E") !important;
  background-position: center !important;
  background-repeat: no-repeat !important;
  background-size: 13px 13px !important;}
input[data-testid="checkbox"]:focus-visible {
  outline: 2px solid #fb923c !important; outline-offset: 2px;}

/* ---------- CHỦ ĐỀ TỐI ---------- */
html.dark, html.dark body, html.dark .gradio-container {
  color-scheme: dark;
  --body-background-fill: #0b0e14;
  --body-background-fill-dark: #0b0e14;
  --block-background-fill: #151a23;
  --block-background-fill-dark: #151a23;
  --block-border-color: #2a3140;
  --border-color-primary: #2a3140;
  --body-text-color: #eef1f6;
  --body-text-color-subdued: #a7aebc;
  background: #0b0e14 !important;
  color: #eef1f6 !important;}
html.dark body {
  background:
    radial-gradient(1100px 480px at 82% -10%, rgba(249, 115, 22, .09), transparent 60%),
    radial-gradient(900px 420px at 8% 112%, rgba(236, 72, 153, .07), transparent 60%),
    #0b0e14 !important;}
html.dark .chatbot {box-shadow: 0 12px 34px rgba(0, 0, 0, .38) !important;}
html.dark #exercise-card {box-shadow: 0 10px 28px rgba(0, 0, 0, .34);}
html.dark input, html.dark textarea, html.dark select {
  background: #10141c !important; color: #eef1f6 !important;}

/* ---------- CHỦ ĐỀ SÁNG ---------- */
html:not(.dark) .gradio-container {
  --body-background-fill: #f6f3ef;
  --block-background-fill: #ffffff;
  --border-color-primary: #e6e0d8;
  --body-text-color: #23272f;
  --body-text-color-subdued: #6b7280;}
html:not(.dark) body {
  background:
    radial-gradient(1000px 460px at 85% -8%, rgba(249, 115, 22, .10), transparent 60%),
    radial-gradient(820px 400px at 6% 110%, rgba(236, 72, 153, .08), transparent 60%),
    #f6f3ef !important;}
html:not(.dark) .chatbot {box-shadow: 0 12px 32px rgba(120, 90, 60, .12) !important;}
html:not(.dark) #exercise-card {box-shadow: 0 10px 26px rgba(120, 90, 60, .10);}

/* ---------- FOOTER ---------- */
.gradio-container .footer {opacity: .55;}
.gradio-container .footer:hover {opacity: .85;}
"""

APPLY_THEME_JS = """
(theme) => {
    const requested = ['light', 'dark'].includes(theme) ? theme : 'system';
    const resolved = requested === 'system'
        ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
        : requested;
    document.documentElement.classList.toggle('dark', resolved === 'dark');
    if (document.body) document.body.classList.toggle('dark', resolved === 'dark');
    document.documentElement.dataset.trisTheme = resolved;
    localStorage.setItem('tris-ai-theme', requested);
    const url = new URL(window.location.href);
    if (requested === 'system') url.searchParams.delete('__theme');
    else url.searchParams.set('__theme', requested);
    window.history.replaceState({}, '', url.toString());
    return [];
}
"""

UI_TEXT = {
    "vi": {
        "brand": "### Tris AI ▾\n`{model}` · chạy local",
        "login": "Đăng nhập", "register": "Đăng ký",
        "settings_title": "## Cài đặt chung",
        "local_account": "Bạn đang dùng chế độ local chưa đăng nhập. Tài khoản và mật khẩu được lưu riêng trong PostgreSQL.",
        "learner": "Hồ sơ người học", "learner_info": "Dữ liệu học của mỗi hồ sơ được tách riêng trên máy.",
        "appearance": "Giao diện",
        "theme": "Chủ đề", "system_language": "Ngôn ngữ hệ thống",
        "ai_language": "Ngôn ngữ phản hồi của AI",
        "adaptive": "Cá nhân hóa theo kỹ năng và lỗi đã học",
        "voice_input": "Bật nhập bằng giọng nói",
        "voice_output": "Bật giọng linh vật Tris đọc phản hồi",
        "save_settings": "Lưu cài đặt",
        "account": "Tài khoản & bảo mật", "open_login": "Mở trang đăng nhập",
        "open_register": "Mở trang đăng ký", "current_password": "Mật khẩu hiện tại",
        "new_password": "Mật khẩu mới", "confirm_password": "Nhập lại mật khẩu mới",
        "change_password": "Đổi mật khẩu", "logout": "Đăng xuất",
        "data": "Dữ liệu & backup", "backup": "Tạo backup SQLite", "export": "Xuất dữ liệu JSON",
        "created_file": "Tệp vừa tạo", "documents": "Tài liệu đã tải",
        "selected_documents": "Tài liệu dùng để tạo bài tập", "skill": "Kỹ năng",
        "difficulty": "Độ khó", "question_count": "Số câu", "create_from_docs": "Tạo bài từ tài liệu",
        "mode": "Chế độ học", "scenario": "Tình huống", "create_exercise": "Tạo bài tập",
        "choose_answer": "Chọn đáp án", "your_answer": "Câu trả lời của bạn",
        "answer_placeholder": "Nhập câu trả lời...", "previous": "← Câu trước", "flag": "🚩 Cắm cờ",
        "next": "Câu sau →", "question_board": "### Bảng câu hỏi", "submit_all": "Nộp toàn bộ bài",
        "progress": "Tiến độ & ôn tập", "daily_goal": "Mục tiêu câu/ngày",
        "save_goal": "Lưu mục tiêu", "refresh": "Làm mới thống kê", "review_source": "Nguồn ôn tập",
        "max_questions": "Số câu tối đa", "start_review": "Bắt đầu ôn",
        "chat_label": "Tris AI", "chat_placeholder": "Mình có thể giúp gì cho việc học tiếng Anh của bạn?",
        "attach": "＋ Đính kèm", "attach_help": "Chọn đúng loại hoặc kéo thả trực tiếp vào khung nhập bên dưới.",
        "file": "📄 Gửi tệp", "image": "🖼️ Gửi ảnh", "video": "🎬 Gửi video",
        "visual_consent": "Cho phép gửi ảnh đã chọn tới Google để tìm ảnh tương tự",
        "visual_search": "🔎 Tìm ảnh tương tự trên web",
        "web_search_toggle": "🌐 Tìm kiếm web để trả lời (kèm nguồn [W1], [W2])",
        "gen_title": "🎨 Tạo ảnh / GIF / video ngắn",
        "gen_prompt_label": "Mô tả nội dung muốn tạo (tiếng Việt hoặc English)",
        "gen_prompt_placeholder": "Ví dụ: một chú mộc tinta dễ thương đang đọc sách...",
        "gen_mode_label": "Kiểu nội dung",
        "gen_button": "✨ Tạo ngay",
        "gen_mode_image": "🖼️ Ảnh", "gen_mode_gif": "🎞️ GIF", "gen_mode_video": "🎬 Video ngắn",
        "message_placeholder": "Nhắn cho Tris AI...", "clear": "Xóa cuộc trò chuyện hiện tại",
    },
    "en": {
        "brand": "### Tris AI ▾\n`{model}` · running locally",
        "login": "Log in", "register": "Sign up",
        "settings_title": "## General settings",
        "local_account": "You are using local mode without signing in. Accounts and passwords are stored separately in PostgreSQL.",
        "learner": "Learner profile", "learner_info": "Learning data is stored separately for each local profile.",
        "appearance": "Appearance",
        "theme": "Theme", "system_language": "System language",
        "ai_language": "AI response language",
        "adaptive": "Personalize using learned skills and mistakes",
        "voice_input": "Enable voice input",
        "voice_output": "Let the Tris mascot read responses",
        "save_settings": "Save settings",
        "account": "Account & security", "open_login": "Open login page",
        "open_register": "Open sign-up page", "current_password": "Current password",
        "new_password": "New password", "confirm_password": "Confirm new password",
        "change_password": "Change password", "logout": "Log out",
        "data": "Data & backup", "backup": "Create SQLite backup", "export": "Export JSON data",
        "created_file": "Created file", "documents": "Uploaded documents",
        "selected_documents": "Documents used for exercises", "skill": "Skill",
        "difficulty": "Difficulty", "question_count": "Questions", "create_from_docs": "Create from documents",
        "mode": "Learning mode", "scenario": "Scenario", "create_exercise": "Create exercise",
        "choose_answer": "Choose an answer", "your_answer": "Your answer",
        "answer_placeholder": "Enter your answer...", "previous": "← Previous", "flag": "🚩 Flag",
        "next": "Next →", "question_board": "### Question board", "submit_all": "Submit all answers",
        "progress": "Progress & review", "daily_goal": "Daily question goal",
        "save_goal": "Save goal", "refresh": "Refresh statistics", "review_source": "Review source",
        "max_questions": "Maximum questions", "start_review": "Start review",
        "chat_label": "Tris AI", "chat_placeholder": "How can I help with your English learning?",
        "attach": "＋ Attach", "attach_help": "Choose a type or drag files directly into the composer below.",
        "file": "📄 Add files", "image": "🖼️ Add images", "video": "🎬 Add videos",
        "visual_consent": "Allow the selected image to be sent to Google for visual search",
        "visual_search": "🔎 Find similar images on the web",
        "web_search_toggle": "🌐 Search the web to answer (with [W1], [W2] sources)",
        "gen_title": "🎨 Create image / GIF / short video",
        "gen_prompt_label": "Describe what to create (Vietnamese or English)",
        "gen_prompt_placeholder": "Example: a cute shiba inu reading a book...",
        "gen_mode_label": "Content type",
        "gen_button": "✨ Create",
        "gen_mode_image": "🖼️ Image", "gen_mode_gif": "🎞️ GIF", "gen_mode_video": "🎬 Short video",
        "message_placeholder": "Message Tris AI...", "clear": "Clear current conversation",
    },
}


def _ui_text(language: str) -> dict[str, str]:
    return UI_TEXT["en" if language == "en" else "vi"]


def _theme_choices(language: str) -> list[tuple[str, str]]:
    if language == "en":
        return [("System", "system"), ("Light", "light"), ("Dark", "dark")]
    return [("Hệ thống", "system"), ("Sáng", "light"), ("Tối", "dark")]


def _mode_choices(language: str) -> list[tuple[str, str]]:
    if language == "en":
        return [(value, value) for value in MODES]
    labels = ["Hội thoại", "Ngữ pháp", "Từ vựng", "Nhập vai", "Bài tập"]
    return list(zip(labels, MODES))


def _upload_limits_text(language: str = "vi") -> str:
    document_mb = MAX_DOCUMENT_BYTES // (1024 * 1024)
    image_mb = MAX_IMAGE_BYTES // (1024 * 1024)
    video_mb = MAX_VIDEO_BYTES // (1024 * 1024)
    total_mb = MAX_ATTACHMENT_TOTAL_BYTES // (1024 * 1024)
    if language == "en":
        return (
            f"Up to {MAX_ATTACHMENT_FILES} files/message · documents {document_mb} MB · "
            f"images {image_mb} MB · videos {video_mb} MB · total {total_mb} MB"
        )
    return (
        f"Tối đa {MAX_ATTACHMENT_FILES} tệp/lần · tài liệu {document_mb} MB · "
        f"ảnh {image_mb} MB · video {video_mb} MB · tổng {total_mb} MB"
    )

llm = OllamaLLM()
database = TutorDatabase(DATABASE_PATH)
database.initialize()
study_hub = StudyHub(database, llm)
visual_search_service = VisualSearchService()
vision_service = VisionService()
web_search_service = WebSearchService()
imagegen_service = ImageGenService()
speech_engine = get_speech_engine()
voice_line_service = VoiceLineService(speech_engine, fallback=tris_voice)


def perform_app_shutdown() -> None:
    """Release Ollama VRAM, then exit so nothing keeps running in the background."""
    def _release_and_exit() -> None:
        try:
            ImageGenService._unload_ollama_models()
        except Exception:
            pass
        time.sleep(2.0)
        os._exit(0)

    threading.Thread(target=_release_and_exit, daemon=True).start()


session_watchdog = SessionWatchdog(
    grace_seconds=SHUTDOWN_GRACE_SECONDS,
    on_expire=perform_app_shutdown,
)
ensure_local_postgres()
account_store = PostgreSQLAccountStore()
auth_sessions = AuthSessionManager()
social_oauth = SocialOAuth()
social_login_codes = OAuthLoginCodeManager()
try:
    account_store.initialize()
except AccountError:
    # The account panel reports configuration/connectivity details on demand.
    pass


def register_account_ui(
    username: str,
    password: str,
    confirm_password: str,
    display_name: str,
) -> tuple[dict[str, str], str, dict, str, str]:
    """Create a PostgreSQL account and immediately start a local session."""
    try:
        if password != confirm_password:
            raise AccountError("Hai lần nhập mật khẩu chưa khớp.")
        account_store.initialize()
        account = account_store.register(username, password, display_name)
        token = auth_sessions.create(account)
        database.get_or_create_user(account.learner_name)
        state = {
            "token": token,
            "account_id": account.account_id,
            "username": account.username,
            "learner_name": account.learner_name,
        }
        return (
            state,
            f"✅ Đã đăng ký và đăng nhập: **{account.username}**",
            gr.update(value=account.learner_name, interactive=False),
            "",
            "",
        )
    except (AccountError, DatabaseError) as exc:
        return {}, f"⚠️ {exc}", gr.update(), "", ""


def login_account_ui(
    username: str,
    password: str,
) -> tuple[dict[str, str], str, dict, str]:
    """Verify Argon2id credentials against PostgreSQL."""
    try:
        account_store.initialize()
        account = account_store.authenticate(username, password)
        token = auth_sessions.create(account)
        database.get_or_create_user(account.learner_name)
        state = {
            "token": token,
            "account_id": account.account_id,
            "username": account.username,
            "learner_name": account.learner_name,
        }
        return (
            state,
            f"✅ Đang đăng nhập: **{account.username}**",
            gr.update(value=account.learner_name, interactive=False),
            "",
        )
    except (AccountError, DatabaseError) as exc:
        return {}, f"⚠️ {exc}", gr.update(), ""


def logout_account_ui(
    auth_state: dict[str, str] | None,
) -> tuple[dict, str, dict]:
    state = dict(auth_state or {})
    auth_sessions.revoke(str(state.get("token", "")))
    return {}, "Bạn đang dùng chế độ local chưa đăng nhập.", gr.update(interactive=True)


def change_password_ui(
    auth_state: dict[str, str] | None,
    current_password: str,
    new_password: str,
    confirm_password: str,
) -> tuple[str, str, str, str]:
    try:
        state = dict(auth_state or {})
        account = auth_sessions.get(str(state.get("token", "")))
        if account is None:
            raise AccountError("Hãy đăng nhập trước khi đổi mật khẩu.")
        if new_password != confirm_password:
            raise AccountError("Hai lần nhập mật khẩu mới chưa khớp.")
        account_store.change_password(
            account.account_id, current_password, new_password
        )
        return "✅ Đã đổi mật khẩu PostgreSQL.", "", "", ""
    except AccountError as exc:
        return f"⚠️ {exc}", "", "", ""


def social_login_callback_ui(
    request: gr.Request,
) -> tuple[dict[str, str], str | dict, dict]:
    """Consume the one-time OAuth bridge code when the provider returns."""
    query = getattr(request, "query_params", {}) or {}
    error_provider = str(query.get("oauth_error", "")).casefold()
    if error_provider:
        label = "Google" if error_provider == "google" else "Facebook"
        reason = str(query.get("oauth_reason", "")).casefold()
        if reason == "credentials":
            hint = (
                "Nguyên nhân thường gặp: Client ID/Secret trong máy không còn hợp lệ. "
                "Hãy vào Google Cloud Console → Credentials tạo lại Client Secret, "
                "rồi chạy scripts\\setup_google_oauth.ps1 để lưu."
            )
        elif reason == "redirect":
            hint = (
                "Google Cloud Console chưa khai báo đúng redirect URI. "
                "Thêm chính xác: http://127.0.0.1:8000/v1/auth/oauth/google/callback"
            )
        elif reason == "email":
            hint = "Email Google chưa được xác minh. Hãy xác minh email rồi thử lại."
        else:
            hint = "Hãy thử lại hoặc dùng đăng nhập bằng mật khẩu."
        return (
            {},
            f"⚠️ Không thể xác minh bằng {label}. {hint}",
            gr.update(),
        )
    code = str(query.get("oauth_code", ""))
    if not code:
        return {}, gr.update(), gr.update()
    result = social_login_codes.consume(code)
    if result is None:
        return (
            {},
            "⚠️ Mã đăng nhập đã hết hạn hoặc đã được sử dụng. Hãy đăng nhập lại.",
            gr.update(),
        )
    token, account = result
    state = {
        "token": token,
        "account_id": account.account_id,
        "username": account.username,
        "learner_name": account.learner_name,
        "auth_provider": account.auth_provider,
    }
    labels = {"google": "Google", "facebook": "Facebook"}
    label = labels.get(account.auth_provider, "tài khoản PostgreSQL")
    return (
        state,
        f"✅ Đã đăng nhập bằng **{label}**: {account.learner_name}",
        gr.update(value=account.learner_name, interactive=False),
    )


def social_login_status_markdown() -> str:
    status = social_oauth.status()
    google = "sẵn sàng" if status["google"] else "chưa có Client ID/Secret"
    return (
        f"**Google:** {google}. Facebook sẽ được bật ở giai đoạn sau. "
        "Thông tin bí mật chỉ đọc từ biến môi trường trên máy."
    )


def header_auth_ui(
    auth_state: dict[str, str] | None,
    interface_language: str = "vi",
) -> tuple[dict, dict, dict, dict]:
    """Mirror the login state into the header: auth buttons out, profile in."""
    state = dict(auth_state or {})
    logged_in = bool(state.get("username"))
    username = str(state.get("username") or "")
    language = "en" if interface_language == "en" else "vi"
    badge = f"● **{username}**" if logged_in else ""
    logout_label = "Đăng xuất" if language == "vi" else "Log out"
    return (
        gr.update(visible=not logged_in),
        gr.update(visible=not logged_in),
        gr.update(value=badge, visible=logged_in),
        gr.update(visible=logged_in, value=logout_label),
    )


def normalize_learner_name(learner_name: str) -> str:
    """Keep local profile names readable and bounded."""
    normalized = " ".join((learner_name or "").split())
    return normalized[:50] or DEFAULT_LEARNER_NAME


def context_scenario(mode: str, scenario: str) -> str:
    """Only Role Play needs a scenario key in SQLite."""
    return scenario if mode == MODE_ROLEPLAY else ""


def initial_history(mode: str, scenario: str) -> list[ChatMessage]:
    """Start role play with a greeting; other empty modes start blank."""
    if mode == MODE_ROLEPLAY:
        return [{"role": "assistant", "content": roleplay.opening_message(scenario)}]
    if mode == MODE_EXERCISES:
        return [
            {
                "role": "assistant",
                "content": (
                    "Chọn kỹ năng, độ khó và số câu ở phía trên, rồi nhấn "
                    "**Tạo bài tập**. Chế độ Auto sẽ ưu tiên điểm yếu trong hồ sơ v0.3."
                ),
            }
        ]
    return []


def load_history(user_id: int, mode: str, scenario: str) -> list[ChatMessage]:
    """Restore recent SQLite history for one mode and scenario."""
    if mode == MODE_EXERCISES:
        return initial_history(mode, scenario)
    history = database.load_history(
        user_id,
        mode,
        context_scenario(mode, scenario),
        MAX_HISTORY_MESSAGES,
    )
    if mode == MODE_ROLEPLAY:
        opening = roleplay.opening_message(scenario)
        if not history or history[0].get("content") != opening:
            history.insert(0, {"role": "assistant", "content": opening})
    return history


def progress_markdown(user_id: int) -> str:
    """Build a compact local learning dashboard."""
    stats: LearningStats = database.get_stats(user_id)
    exercise_stats: ExerciseStats = database.get_exercise_stats(user_id)
    recent_words = database.get_recent_vocabulary(user_id)
    skill_insights = database.get_skill_insights(user_id)
    words_text = ", ".join(f"`{word}`" for word in recent_words) or "Chưa có"
    level_icons = {
        "Yếu": "🔴",
        "Đang cải thiện": "🟡",
        "Tốt": "🟢",
        "Chưa đủ dữ liệu": "⚪",
    }
    if skill_insights:
        skill_lines = [
            (
                f"- {level_icons[insight.level]} **{insight.skill_name}**: "
                f"{insight.level} — {insight.correct_count} tốt / "
                f"{insight.error_count} cần sửa"
            )
            for insight in skill_insights
        ]
        skills_text = "\n".join(skill_lines)
    else:
        skills_text = "- ⚪ Chưa đủ dữ liệu. Hãy luyện Grammar hoặc Vocabulary."

    return (
        f"### Tiến độ — {stats.learner_name}\n"
        f"- Lượt luyện tập đã lưu: **{stats.message_count}**\n"
        f"- Từ vựng đang học: **{stats.vocabulary_count}**\n"
        f"- Lỗi ngữ pháp đã ghi nhận: **{stats.grammar_mistake_count}**\n"
        f"- Bộ bài tập đã hoàn thành: **{exercise_stats.completed_sessions}**\n"
        f"- Độ chính xác bài tập: **{exercise_stats.accuracy_percent}%** "
        f"({exercise_stats.correct_attempts}/{exercise_stats.total_attempts})\n"
        f"- Từ gần đây: {words_text}\n\n"
        f"### Hồ sơ kỹ năng v1.1\n{skills_text}\n\n"
        f"Dữ liệu local: `{DATABASE_PATH}`"
    )


def review_dashboard(learner_name: str) -> str:
    """Render v0.7 goals, recent history, and review inventory."""
    try:
        user_id = database.get_or_create_user(normalize_learner_name(learner_name))
        goal = database.get_daily_goal(user_id)
        days = database.get_daily_progress(user_id, 7)
        history = database.list_exercise_history(user_id, 8)
        wrong_count = len(database.get_review_questions(user_id, "wrong", 50))
        flagged_count = len(database.get_review_questions(user_id, "flagged", 50))
        today = days[0] if days else None
        today_answered = today.answered_questions if today else 0
        lines = [
            "### Ôn tập thông minh v0.7",
            f"- Mục tiêu hôm nay: **{today_answered}/{goal} câu**",
            f"- Câu sai có thể ôn lại: **{wrong_count}**",
            f"- Câu đã cắm cờ: **{flagged_count}**",
            "",
            "#### 7 ngày gần đây",
        ]
        if days:
            lines.extend(
                f"- `{item.day}`: {item.answered_questions} câu · "
                f"{item.accuracy_percent}% · {item.completed_sessions} bộ"
                for item in days
            )
        else:
            lines.append("- Chưa có bài đã nộp.")
        lines.append("\n#### Bài gần đây")
        if history:
            lines.extend(
                f"- #{item['id']} · **{item['skill']}** · {item['difficulty']} · "
                f"{item['correct_count']}/{item['total_questions']}"
                for item in history
            )
        else:
            lines.append("- Chưa có lịch sử bài tập.")
        return "\n".join(lines)
    except DatabaseError as exc:
        return f"⚠️ {exc}"


def save_daily_goal(learner_name: str, goal: int) -> tuple[str, str]:
    try:
        user_id = database.get_or_create_user(normalize_learner_name(learner_name))
        saved = database.set_daily_goal(user_id, int(goal))
        return f"✅ Đã lưu mục tiêu **{saved} câu/ngày**.", review_dashboard(learner_name)
    except (DatabaseError, TypeError, ValueError) as exc:
        return f"⚠️ {exc}", review_dashboard(learner_name)


def start_review_exercise(
    learner_name: str,
    review_kind: str,
    question_count: int,
) -> tuple[Any, ...]:
    """Create a fresh quiz from persisted wrong/flagged questions."""
    try:
        user_id = database.get_or_create_user(normalize_learner_name(learner_name))
        questions = database.get_review_questions(
            user_id, review_kind, int(question_count)
        )
        if not questions:
            raise DatabaseError("Chưa có câu phù hợp để tạo bài ôn tập này.")
        label = {
            "wrong": "Ôn câu sai",
            "flagged": "Ôn câu cắm cờ",
            "weak": "Ôn điểm yếu",
        }.get(review_kind, "Ôn tập")
        session_id, stored = database.create_exercise_session(
            user_id, label, "Review", questions
        )
        state: dict[str, Any] = {
            "session_id": session_id,
            "skill": label,
            "difficulty": "Review",
            "questions": stored,
            "current_index": 0,
            "correct_count": 0,
            "draft_answers": {},
            "graded": {},
            "results": {},
            "feedbacks": {},
            "flags": [],
            "completed": False,
        }
        return (
            gr.update(value=MODE_EXERCISES),
            gr.update(visible=False),
            gr.update(visible=True),
            gr.update(visible=False),
            state,
            *exercise_view(state),
            progress_markdown(user_id),
            f"✅ Đã nạp **{len(stored)} câu** vào khu vực Exercises.",
        )
    except DatabaseError as exc:
        return (
            gr.update(value=MODE_EXERCISES),
            gr.update(visible=False),
            gr.update(visible=True),
            gr.update(visible=False),
            {},
            *empty_exercise_view(f"⚠️ {exc}"),
            review_dashboard(learner_name),
            f"⚠️ {exc}",
        )


def document_library_view(learner_name: str) -> tuple[str, dict]:
    """Return readable document cards and selectable ids."""
    try:
        user_id = database.get_or_create_user(normalize_learner_name(learner_name))
        documents = database.list_documents(user_id)
        if documents:
            lines = ["### Thư viện tài liệu v0.8"] + [
                f"- **#{item['id']} · {item['title']}** — {item['file_type'].upper()} · "
                f"{item['chunk_count']} đoạn · {item['extraction_engine']}"
                for item in documents
            ]
        else:
            lines = ["### Thư viện tài liệu v0.8", "Chưa có tài liệu."]
        choices = [
            (f"#{item['id']} · {item['title']}", int(item["id"]))
            for item in documents
        ]
        return "\n".join(lines), gr.update(choices=choices, value=[])
    except DatabaseError as exc:
        return f"⚠️ {exc}", gr.update(choices=[], value=[])


def ingest_document_ui(
    learner_name: str,
    file_value: Any,
    title: str,
) -> tuple[str, str, dict]:
    try:
        file_path = getattr(file_value, "name", None) or str(file_value or "")
        if not file_path:
            raise StudyHubError("Hãy chọn một file tài liệu.")
        user_id = database.get_or_create_user(normalize_learner_name(learner_name))
        result = study_hub.ingest(user_id, file_path, title)
        library, choices = document_library_view(learner_name)
        status = (
            f"✅ Đã thêm **{result['title']}** bằng {result['engine']}: "
            f"{result['chunks']} đoạn, {result['indexed']} vector Qdrant."
        )
        return status, library, choices
    except (DatabaseError, StudyHubError) as exc:
        library, choices = document_library_view(learner_name)
        return f"⚠️ {exc}", library, choices


def ask_documents_ui(
    learner_name: str,
    document_ids: list[int] | None,
    question: str,
) -> str:
    try:
        user_id = database.get_or_create_user(normalize_learner_name(learner_name))
        result = study_hub.ask(user_id, question, document_ids or None)
        source_lines = [
            f"- **[{item['label']}] {item['title']}** · độ liên quan {item['score']:.3f} · "
            f"đoạn #{item['chunk_id']}"
            for item in result["sources"]
        ]
        return f"## Trả lời RAG\n\n{result['answer']}\n\n### Nguồn đã dùng\n" + "\n".join(source_lines)
    except (DatabaseError, LocalAIError, StudyHubError) as exc:
        return f"⚠️ {exc}"


def generate_document_exercise_ui(
    learner_name: str,
    document_ids: list[int] | None,
    requested_skill: str,
    difficulty: str,
    question_count: int,
) -> tuple[Any, ...]:
    """Generate a quiz grounded only in selected local document chunks."""
    try:
        if not document_ids:
            raise StudyHubError("Hãy chọn ít nhất một tài liệu để tạo bài.")
        user_id = database.get_or_create_user(normalize_learner_name(learner_name))
        chunks = database.get_document_chunks(user_id, document_ids)
        if not chunks:
            raise StudyHubError("Không tìm thấy nội dung trong tài liệu đã chọn.")
        preferences = database.get_user_preferences(user_id)
        insights = (
            database.get_skill_insights(user_id)
            if preferences.adaptive_intelligence
            else []
        )
        selected_skill = exercises.choose_skill(requested_skill, insights)
        context = learner_prompt_context(user_id)
        source_context = "\n\n".join(
            f"[{chunk['title']} — đoạn {chunk['chunk_index'] + 1}]\n{chunk['content']}"
            for chunk in chunks[:10]
        )
        context += (
            "\n\nCreate every question using only the following selected learning "
            "material. Do not introduce facts outside it:\n" + source_context[:8000]
        )
        questions = exercises.generate_questions(
            llm, selected_skill, difficulty, int(question_count), context
        )
        session_id, stored = database.create_exercise_session(
            user_id, selected_skill, difficulty, questions
        )
        state: dict[str, Any] = {
            "session_id": session_id,
            "skill": selected_skill,
            "difficulty": difficulty,
            "questions": stored,
            "current_index": 0,
            "correct_count": 0,
            "draft_answers": {},
            "graded": {},
            "results": {},
            "feedbacks": {},
            "flags": [],
            "completed": False,
        }
        return (
            gr.update(value=MODE_EXERCISES),
            gr.update(visible=False),
            gr.update(visible=True),
            gr.update(visible=False),
            state,
            *exercise_view(state),
            progress_markdown(user_id),
            f"✅ Đã tạo **{len(stored)} câu** từ tài liệu đã chọn.",
        )
    except (DatabaseError, LocalAIError, StudyHubError, exercises.ExerciseError) as exc:
        return (
            gr.update(value=MODE_EXERCISES),
            gr.update(visible=False),
            gr.update(visible=True),
            gr.update(visible=False),
            {},
            *empty_exercise_view(f"⚠️ {exc}"),
            review_dashboard(learner_name),
            f"⚠️ {exc}",
        )


def maintenance_files(learner_name: str, action: str) -> tuple[str, str | None]:
    try:
        if action == "backup":
            path = create_backup()
            return f"✅ Backup đã tạo: `{path}`", str(path)
        user_id = database.get_or_create_user(normalize_learner_name(learner_name))
        path = export_profile(database, user_id)
        return f"✅ Dữ liệu hồ sơ đã xuất: `{path}`", str(path)
    except (DatabaseError, StudyHubError, OSError) as exc:
        return f"⚠️ {exc}", None


def _composer_sources(voice_input: bool) -> list[str]:
    return ["upload", "microphone"] if voice_input else ["upload"]


def load_general_settings(
    learner_name: str,
) -> tuple[str, str, str, bool, bool, bool, str | dict, dict]:
    """Load persistent preferences for the selected local learner."""
    try:
        user_id = database.get_or_create_user(normalize_learner_name(learner_name))
        preferences = database.get_user_preferences(user_id)
        return (
            preferences.theme,
            preferences.interface_language,
            preferences.language,
            preferences.adaptive_intelligence,
            preferences.voice_input,
            preferences.voice_output,
            gr.update(),
            gr.update(sources=_composer_sources(preferences.voice_input)),
        )
    except DatabaseError as exc:
        return (
            "system",
            "vi",
            "vi",
            True,
            False,
            False,
            f"⚠️ {exc}",
            gr.update(sources=["upload"]),
        )


def save_general_settings(
    learner_name: str,
    theme: str,
    interface_language: str,
    language: str,
    adaptive_intelligence: bool,
    voice_input: bool,
    voice_output: bool,
) -> tuple[str, dict]:
    """Persist settings and update composer capabilities immediately."""
    try:
        user_id = database.get_or_create_user(normalize_learner_name(learner_name))
        preferences = database.save_user_preferences(
            user_id,
            theme,
            interface_language,
            language,
            adaptive_intelligence,
            voice_input,
            voice_output,
        )
        language_label = "Tiếng Việt" if preferences.language == "vi" else "English"
        adaptive_label = "bật" if preferences.adaptive_intelligence else "tắt"
        voice_label = "bật" if preferences.voice_input else "tắt"
        output_voice_label = "bật" if preferences.voice_output else "tắt"
        if preferences.interface_language == "en":
            status = (
                f"✅ Saved: AI responses **{language_label}**, personalization "
                f"**{'on' if preferences.adaptive_intelligence else 'off'}**, "
                f"microphone **{'on' if preferences.voice_input else 'off'}**, "
                f"mascot voice **{'on' if preferences.voice_output else 'off'}**."
            )
        else:
            status = (
                f"✅ Đã lưu: phản hồi **{language_label}**, cá nhân hóa "
                f"**{adaptive_label}**, microphone **{voice_label}**."
                f" Giọng linh vật **{output_voice_label}**."
            )
        return status, gr.update(sources=_composer_sources(preferences.voice_input))
    except DatabaseError as exc:
        return f"⚠️ {exc}", gr.update()


def interface_language_updates(
    language: str, auth_state: dict[str, str] | None = None
) -> tuple[dict, ...]:
    """Translate stable interface chrome while preserving component values."""
    selected = "en" if language == "en" else "vi"
    text = _ui_text(selected)
    review_choices = (
        [("Wrong answers", "wrong"), ("Flagged questions", "flagged"), ("Recent weaknesses", "weak")]
        if selected == "en"
        else [("Câu đã làm sai", "wrong"), ("Câu đã cắm cờ", "flagged"), ("Điểm yếu gần đây", "weak")]
    )
    footer = _upload_limits_text(selected)
    account = dict(auth_state or {})
    if account.get("username"):
        account_text = (
            f"✅ Signed in as: **{account['username']}**"
            if selected == "en"
            else f"✅ Đang đăng nhập: **{account['username']}**"
        )
    else:
        account_text = text["local_account"]
    return (
        gr.update(value=text["brand"].format(model=MODEL_NAME)),
        gr.update(value=text["login"]),
        gr.update(value=text["register"]),
        gr.update(value=text["settings_title"]),
        gr.update(value=account_text),
        gr.update(label=text["learner"], info=text["learner_info"]),
        gr.update(label=text["appearance"]),
        gr.update(label=text["theme"], choices=_theme_choices(selected)),
        gr.update(label=text["system_language"]),
        gr.update(label=text["ai_language"]),
        gr.update(label=text["adaptive"]),
        gr.update(label=text["voice_input"]),
        gr.update(label=text["voice_output"]),
        gr.update(value=text["save_settings"]),
        gr.update(label=text["account"]),
        gr.update(value=text["open_login"]),
        gr.update(value=text["open_register"]),
        gr.update(label=text["current_password"]),
        gr.update(label=text["new_password"]),
        gr.update(label=text["confirm_password"]),
        gr.update(value=text["change_password"]),
        gr.update(value=text["logout"]),
        gr.update(label=text["data"]),
        gr.update(value=text["backup"]),
        gr.update(value=text["export"]),
        gr.update(label=text["created_file"]),
        gr.update(label=text["documents"]),
        gr.update(label=text["selected_documents"]),
        gr.update(label=text["skill"]),
        gr.update(label=text["difficulty"]),
        gr.update(label=text["question_count"]),
        gr.update(value=text["create_from_docs"]),
        gr.update(label=text["mode"], choices=_mode_choices(selected)),
        gr.update(label=text["scenario"]),
        gr.update(label=text["skill"]),
        gr.update(label=text["difficulty"]),
        gr.update(label=text["question_count"]),
        gr.update(value=text["create_exercise"]),
        gr.update(label=text["choose_answer"]),
        gr.update(label=text["your_answer"], placeholder=text["answer_placeholder"]),
        gr.update(value=text["previous"]),
        gr.update(value=text["flag"]),
        gr.update(value=text["next"]),
        gr.update(value=text["question_board"]),
        gr.update(value=text["submit_all"]),
        gr.update(label=text["progress"]),
        gr.update(label=text["daily_goal"]),
        gr.update(value=text["save_goal"]),
        gr.update(value=text["refresh"]),
        gr.update(label=text["review_source"], choices=review_choices),
        gr.update(label=text["max_questions"]),
        gr.update(value=text["start_review"]),
        gr.update(label=text["chat_label"], placeholder=text["chat_placeholder"]),
        gr.update(label=text["attach"]),
        gr.update(
            value=f"{text['attach_help']}\n\n**Limits:** {_upload_limits_text(selected)}"
            if selected == "en"
            else f"{text['attach_help']}\n\n**Giới hạn:** {_upload_limits_text(selected)}"
        ),
        gr.update(label=text["file"]),
        gr.update(label=text["image"]),
        gr.update(label=text["video"]),
        gr.update(label=text["visual_consent"]),
        gr.update(value=text["visual_search"]),
        gr.update(label=text["web_search_toggle"]),
        gr.update(placeholder=text["message_placeholder"]),
        gr.update(value=footer),
        gr.update(value=text["clear"]),
        gr.update(label=text["gen_title"]),
        gr.update(
            label=text["gen_prompt_label"],
            placeholder=text["gen_prompt_placeholder"],
        ),
        gr.update(
            label=text["gen_mode_label"],
            choices=[
                (text["gen_mode_image"], "image"),
                (text["gen_mode_gif"], "gif"),
                (text["gen_mode_video"], "video"),
            ],
        ),
        gr.update(value=text["gen_button"]),
    )


def learner_prompt_context(user_id: int) -> str:
    """Build the prompt additions controlled by the learner's settings."""
    preferences = database.get_user_preferences(user_id)
    parts: list[str] = []
    if preferences.adaptive_intelligence:
        parts.append(
            skill_analysis.build_learner_context(database.get_skill_insights(user_id))
        )
    if preferences.language == "en":
        parts.append("Respond and explain in English unless the learner asks otherwise.")
    else:
        parts.append(
            "Giải thích bằng tiếng Việt, nhưng giữ ví dụ và phần luyện tập tiếng Anh."
        )
    return "\n\n".join(part for part in parts if part)


def load_workspace(
    learner_name: str,
    mode: str,
    scenario: str,
) -> tuple[list[ChatMessage], str]:
    """Load a learner's conversation and progress from SQLite."""
    try:
        user_id = database.get_or_create_user(normalize_learner_name(learner_name))
        return load_history(user_id, mode, scenario), progress_markdown(user_id)
    except DatabaseError as exc:
        return initial_history(mode, scenario), f"⚠️ {exc}"


def load_workspace_with_state(
    learner_name: str,
    mode: str,
    scenario: str,
) -> tuple[Any, ...]:
    """Load a profile and reset any browser-only active exercise state."""
    history, progress = load_workspace(learner_name, mode, scenario)
    return history, progress, {}, *empty_exercise_view()


def is_vocabulary_lookup(message: str) -> bool:
    """Recognize a short word/phrase, not the learner's example sentence."""
    clean_message = message.strip()
    if not clean_message or len(clean_message) > 60:
        return False
    if any(mark in clean_message for mark in ".?!,;:"):
        return False
    words = clean_message.split()
    return 1 <= len(words) <= 3 and bool(
        re.fullmatch(r"[A-Za-zÀ-ỹ' -]+", clean_message)
    )


def contains_correction(answer: str) -> bool:
    """Detect explicit tutor corrections for the mistake notebook."""
    normalized = answer.casefold()
    markers = (
        "correction:",
        "❌",
        "→",
        "small correction",
        "một chỉnh sửa",
        "sai vì",
    )
    return any(marker in normalized for marker in markers)


def save_learning_records(
    user_id: int,
    mode: str,
    scenario: str,
    user_message: str,
    assistant_message: str,
) -> None:
    """Persist the exchange plus mode-specific learning records."""
    database.save_exchange(
        user_id,
        mode,
        context_scenario(mode, scenario),
        user_message,
        assistant_message,
    )
    correction_found = contains_correction(assistant_message)

    if mode == MODE_VOCABULARY:
        if is_vocabulary_lookup(user_message):
            database.save_vocabulary(user_id, user_message, assistant_message)
        else:
            database.record_skill_attempt(
                user_id,
                "Vocabulary Usage",
                is_error=correction_found,
            )

    if mode == MODE_GRAMMAR:
        grammar_skill = skill_analysis.classify_grammar_skill(
            user_message,
            assistant_message,
        )
        database.record_skill_attempt(
            user_id,
            grammar_skill,
            is_error=correction_found,
        )

    if mode in {MODE_CONVERSATION, MODE_GRAMMAR, MODE_ROLEPLAY} and correction_found:
        database.save_grammar_mistake(
            user_id,
            mode,
            user_message,
            assistant_message,
        )
        if mode in {MODE_CONVERSATION, MODE_ROLEPLAY}:
            grammar_skill = skill_analysis.classify_grammar_skill(
                user_message,
                assistant_message,
            )
            database.record_skill_attempt(user_id, grammar_skill, is_error=True)


def generate_reply(
    message: str,
    history: list[ChatMessage] | None,
    mode: str,
    scenario: str,
    learner_name: str,
    vision_context: str = "",
    web_result: Any = None,
) -> tuple[str, list[ChatMessage], str]:
    """Route one message, then persist the successful local AI exchange."""
    clean_message = message.strip()
    current_history = list(history or [])
    if not clean_message:
        _, progress = load_workspace(learner_name, mode, scenario)
        return "", current_history, progress

    try:
        user_id = database.get_or_create_user(normalize_learner_name(learner_name))
    except DatabaseError as exc:
        updated_history = [
            *current_history,
            {"role": "user", "content": clean_message},
            {"role": "assistant", "content": str(exc)},
        ]
        return "", updated_history, f"⚠️ {exc}"

    try:
        learner_context = learner_prompt_context(user_id)
        routed_message = clean_message
        if vision_context:
            routed_message = (
                f"{clean_message}\n{vision_context.strip()}\n\n"
                "Hãy dùng mô tả ảnh trên khi trả lời; nếu người dùng hỏi về ảnh, "
                "dựa vào mô tả đó và nói rõ những gì ảnh thể hiện."
            )
        web_context = ""
        if web_result is not None and web_result.sources:
            web_context = (
                "\n\n[KẾT QUẢ TÌM KIẾM WEB — chỉ dùng khi liên quan, "
                "trích nguồn dạng [W1], [W2] sau mỗi ý lấy từ web]\n"
                + web_result.context_block
            )
        if mode == MODE_GRAMMAR:
            answer = grammar.respond(
                llm,
                current_history,
                routed_message,
                learner_context + web_context,
            )
        elif mode == MODE_VOCABULARY:
            answer = vocabulary.respond(
                llm,
                current_history,
                routed_message,
                learner_context + web_context,
            )
        elif mode == MODE_ROLEPLAY:
            answer = roleplay.respond(
                llm,
                current_history,
                routed_message,
                scenario,
                learner_context + web_context,
            )
        else:
            answer = conversation.respond(
                llm,
                current_history,
                routed_message,
                learner_context + web_context,
            )
        if web_result is not None and web_result.sources:
            citations = "\n".join(
                f"- [{source['label']}] [{source['title']}](<{source['url']}>)"
                for source in web_result.sources
            )
            answer += f"\n\n**Nguồn web**\n{citations}"
    except LocalAIError as exc:
        answer = str(exc)
        updated_history = [
            *current_history,
            {"role": "user", "content": clean_message},
            {"role": "assistant", "content": answer},
        ]
        return "", updated_history, progress_markdown(user_id)
    except DatabaseError as exc:
        updated_history = [
            *current_history,
            {"role": "user", "content": clean_message},
            {"role": "assistant", "content": str(exc)},
        ]
        return "", updated_history, f"⚠️ {exc}"

    storage_warning = ""
    try:
        save_learning_records(
            user_id,
            mode,
            scenario,
            clean_message,
            answer,
        )
        progress = progress_markdown(user_id)
    except DatabaseError as exc:
        storage_warning = f"\n\n⚠️ {exc}"
        progress = f"⚠️ {exc}"

    updated_history = [
        *current_history,
        {"role": "user", "content": clean_message},
        {"role": "assistant", "content": answer + storage_warning},
    ]
    return "", updated_history, progress


def generate_exercise(
    learner_name: str,
    requested_skill: str,
    difficulty: str,
    question_count: int,
) -> tuple[Any, ...]:
    """Generate, validate, and persist one personalized exercise set."""
    try:
        user_id = database.get_or_create_user(normalize_learner_name(learner_name))
        preferences = database.get_user_preferences(user_id)
        insights = (
            database.get_skill_insights(user_id)
            if preferences.adaptive_intelligence
            else []
        )
        selected_skill = exercises.choose_skill(requested_skill, insights)
        learner_context = learner_prompt_context(user_id)
        questions = exercises.generate_questions(
            llm,
            selected_skill,
            difficulty,
            int(question_count),
            learner_context,
        )
        session_id, stored_questions = database.create_exercise_session(
            user_id,
            selected_skill,
            difficulty,
            questions,
        )
        state: dict[str, Any] = {
            "session_id": session_id,
            "skill": selected_skill,
            "difficulty": difficulty,
            "questions": stored_questions,
            "current_index": 0,
            "correct_count": 0,
            "draft_answers": {},
            "graded": {},
            "results": {},
            "feedbacks": {},
            "flags": [],
            "completed": False,
        }
        return state, *exercise_view(state), progress_markdown(user_id)
    except (LocalAIError, exercises.ExerciseError, DatabaseError) as exc:
        try:
            user_id = database.get_or_create_user(normalize_learner_name(learner_name))
            progress = progress_markdown(user_id)
        except DatabaseError:
            progress = f"⚠️ {exc}"
        return {}, *empty_exercise_view(f"⚠️ {exc}"), progress


def empty_exercise_view(
    message: str = "Chọn cấu hình rồi nhấn **Tạo bài tập** để bắt đầu.",
) -> tuple[Any, ...]:
    """Return a stable empty state for all v0.6 exercise components."""
    base_view = (
        message,
        gr.update(choices=[], value=None, visible=False, interactive=False),
        gr.update(value="", visible=False, interactive=False),
        "",
        "**Tiến độ:** Chưa có bài tập.",
        gr.update(interactive=False),
        gr.update(value="🚩 Cắm cờ", interactive=False),
        gr.update(interactive=False),
        gr.update(value="Nộp toàn bộ bài", interactive=False),
        gr.update(value="", visible=False),
    )
    question_buttons = tuple(
        gr.update(value=str(index + 1), visible=False, interactive=False)
        for index in range(MAX_QUESTION_BUTTONS)
    )
    return (*base_view, *question_buttons)


def _displayed_user_answer(question: dict[str, Any], answer: str) -> str:
    """Convert a stored A-D value to the visible option text for reports."""
    clean_answer = answer.strip()
    if question["question_type"] == "multiple_choice" and clean_answer.upper() in {
        "A",
        "B",
        "C",
        "D",
    }:
        option_index = ord(clean_answer.upper()) - ord("A")
        options = question.get("options", [])
        if option_index < len(options):
            return f"{clean_answer.upper()}. {options[option_index]}"
    return " ".join(clean_answer.split())


def _exercise_report(
    state: dict[str, Any],
    questions: list[dict[str, Any]],
) -> str:
    """Build one post-submission error report below the whole quiz."""
    if not state.get("completed"):
        return ""
    results = dict(state.get("results", {}))
    drafts = dict(state.get("draft_answers", {}))
    correct_count = sum(bool(value) for value in results.values())
    lines = [
        "## Báo cáo kết quả",
        f"Bạn làm đúng **{correct_count}/{len(questions)} câu**.",
    ]
    wrong_indexes = [
        index for index in range(len(questions)) if not results.get(str(index), False)
    ]
    if not wrong_indexes:
        lines.append("\n✅ **Xuất sắc — không có câu sai cần xem lại.**")
        return "\n\n".join(lines)

    lines.append("\n### Các câu cần xem lại")
    for index in wrong_indexes:
        question = questions[index]
        user_answer = _displayed_user_answer(
            question, str(drafts.get(str(index), ""))
        )
        lines.extend(
            [
                f"\n#### ❌ Câu {index + 1} — {question['skill']}",
                f"- **Bạn trả lời:** {user_answer}",
                f"- **Đáp án đúng:** {question['correct_answer']}",
                f"- **Giải thích:** {question['explanation_vi']}",
            ]
        )
    return "\n".join(lines)


def exercise_view(exercise_state: dict[str, Any] | None) -> tuple[Any, ...]:
    """Map portable exercise state to native Gradio quiz controls."""
    state = dict(exercise_state or {})
    questions = state.get("questions")
    if not isinstance(questions, list) or not questions:
        return empty_exercise_view()

    current_index = max(
        0, min(int(state.get("current_index", 0)), len(questions) - 1)
    )
    question = questions[current_index]
    key = str(current_index)
    drafts = dict(state.get("draft_answers", {}))
    completed = bool(state.get("completed", False))
    graded = completed
    results = dict(state.get("results", {}))
    flags = {int(index) for index in state.get("flags", [])}
    is_flagged = current_index in flags
    draft_answer = str(drafts.get(key, ""))
    is_multiple_choice = question["question_type"] == "multiple_choice"
    option_choices = [
        (f"{chr(65 + index)}. {option}", chr(65 + index))
        for index, option in enumerate(question.get("options", []))
    ]
    radio_value: str | None = None
    if is_multiple_choice:
        candidate = draft_answer.strip().upper()
        valid_letters = {chr(65 + index) for index in range(len(option_choices))}
        if candidate in valid_letters:
            radio_value = candidate
        else:
            for index, option in enumerate(question.get("options", [])):
                if draft_answer.casefold().strip() == str(option).casefold().strip():
                    radio_value = chr(65 + index)
                    break

    progress_tokens: list[str] = []
    for index in range(len(questions)):
        index_key = str(index)
        answered = bool(str(drafts.get(index_key, "")).strip())
        token = "●" if answered else "○"
        if index in flags:
            token += "🚩"
        if index == current_index:
            token = f"**[{index + 1}{token}]**"
        else:
            token = f"{index + 1}{token}"
        progress_tokens.append(token)

    feedbacks = dict(state.get("feedbacks", {}))
    feedback = str(state.get("notice", "")) or str(feedbacks.get(key, ""))
    answered_count = sum(
        bool(str(drafts.get(str(index), "")).strip())
        for index in range(len(questions))
    )
    if completed:
        status_detail = (
            f"Đã hoàn thành **{answered_count}/{len(questions)}** · "
            f"Đã nộp bài · Cắm cờ **{len(flags)}**"
        )
    else:
        status_detail = (
            f"Đã trả lời **{answered_count}/{len(questions)}** · "
            f"Cắm cờ **{len(flags)}** · Hoàn thành tất cả rồi nộp một lần"
        )
    status = f"**Tiến độ:** {' · '.join(progress_tokens)}  \n{status_detail}"
    base_view = (
        exercises.format_question_card(question, len(questions), is_flagged),
        gr.update(
            choices=option_choices,
            value=radio_value,
            visible=is_multiple_choice,
            interactive=not graded,
        ),
        gr.update(
            value=draft_answer if not is_multiple_choice else "",
            visible=not is_multiple_choice,
            interactive=not graded,
        ),
        feedback,
        status,
        gr.update(interactive=current_index > 0),
        gr.update(
            value="🚩 Bỏ cờ" if is_flagged else "🚩 Cắm cờ",
            interactive=True,
        ),
        gr.update(interactive=current_index < len(questions) - 1),
        gr.update(
            value=(
                "Đã nộp toàn bộ bài"
                if completed
                else f"Nộp toàn bộ bài ({len(questions)} câu)"
            ),
            interactive=not completed,
        ),
        gr.update(
            value=_exercise_report(state, questions),
            visible=completed,
        ),
    )
    question_button_updates: list[dict] = []
    for index in range(MAX_QUESTION_BUTTONS):
        if index >= len(questions):
            question_button_updates.append(
                gr.update(value=str(index + 1), visible=False, interactive=False)
            )
            continue
        index_key = str(index)
        answered = bool(str(drafts.get(index_key, "")).strip())
        if answered:
            icon = " 🚩" if index in flags else ""
            variant = "primary"
        elif index in flags:
            icon = " 🚩"
            variant = "secondary"
        else:
            icon = ""
            variant = "secondary"
        prefix = "▶ " if index == current_index else ""
        question_button_updates.append(
            gr.update(
                value=f"{prefix}{index + 1}{icon}",
                visible=True,
                interactive=True,
                variant=variant,
            )
        )
    return (*base_view, *question_button_updates)


def _save_current_draft(
    exercise_state: dict[str, Any] | None,
    selected_option: str | None,
    written_answer: str,
) -> dict[str, Any]:
    """Save a browser draft before navigation without grading it."""
    state = dict(exercise_state or {})
    questions = state.get("questions")
    if not isinstance(questions, list) or not questions:
        return state
    current_index = int(state.get("current_index", 0))
    key = str(current_index)
    if state.get("completed"):
        return state
    question = questions[current_index]
    if question["question_type"] == "multiple_choice":
        selected_letter = str(selected_option or "").strip().upper()
        answer = selected_letter if selected_letter in {"A", "B", "C", "D"} else ""
    else:
        answer = written_answer
    drafts = dict(state.get("draft_answers", {}))
    if answer is not None and str(answer).strip():
        drafts[key] = str(answer).strip()
    else:
        drafts.pop(key, None)
    state["draft_answers"] = drafts
    state.pop("notice", None)
    return state


def navigate_exercise(
    exercise_state: dict[str, Any] | None,
    selected_option: str | None,
    written_answer: str,
    step: int,
) -> tuple[Any, ...]:
    """Move between questions while preserving unsubmitted drafts."""
    state = _save_current_draft(
        exercise_state, selected_option, written_answer
    )
    questions = state.get("questions")
    if isinstance(questions, list) and questions:
        state["current_index"] = max(
            0,
            min(
                int(state.get("current_index", 0)) + step,
                len(questions) - 1,
            ),
        )
    return state, *exercise_view(state)


def previous_exercise_question(
    exercise_state: dict[str, Any] | None,
    selected_option: str | None,
    written_answer: str,
) -> tuple[Any, ...]:
    return navigate_exercise(exercise_state, selected_option, written_answer, -1)


def next_exercise_question(
    exercise_state: dict[str, Any] | None,
    selected_option: str | None,
    written_answer: str,
) -> tuple[Any, ...]:
    return navigate_exercise(exercise_state, selected_option, written_answer, 1)


def jump_to_exercise_question(
    exercise_state: dict[str, Any] | None,
    selected_option: str | None,
    written_answer: str,
    target_index: int,
) -> tuple[Any, ...]:
    """Jump directly from the numbered navigator to one question."""
    state = _save_current_draft(
        exercise_state, selected_option, written_answer
    )
    questions = state.get("questions")
    if isinstance(questions, list) and questions:
        state["current_index"] = max(0, min(int(target_index), len(questions) - 1))
    return state, *exercise_view(state)


def save_exercise_draft_status(
    exercise_state: dict[str, Any] | None,
    selected_option: str | None,
    written_answer: str,
) -> tuple[Any, ...]:
    """Refresh progress buttons immediately after a learner selects an answer."""
    state = _save_current_draft(
        exercise_state, selected_option, written_answer
    )
    view = exercise_view(state)
    return state, view[4], *view[10:]


def toggle_exercise_flag(
    exercise_state: dict[str, Any] | None,
    selected_option: str | None,
    written_answer: str,
    learner_name: str,
) -> tuple[Any, ...]:
    """Toggle and persist the review flag on the current question."""
    state = _save_current_draft(
        exercise_state, selected_option, written_answer
    )
    questions = state.get("questions")
    if not isinstance(questions, list) or not questions:
        return state, *exercise_view(state)
    current_index = int(state.get("current_index", 0))
    flags = {int(index) for index in state.get("flags", [])}
    is_flagged = current_index not in flags
    try:
        user_id = database.get_or_create_user(normalize_learner_name(learner_name))
        database.set_exercise_question_flag(
            user_id,
            int(state["session_id"]),
            int(questions[current_index]["question_id"]),
            is_flagged,
        )
        if is_flagged:
            flags.add(current_index)
        else:
            flags.discard(current_index)
        state["flags"] = sorted(flags)
    except DatabaseError as exc:
        state["notice"] = f"⚠️ {exc}"
    return state, *exercise_view(state)


def submit_exercise_answer(
    exercise_state: dict[str, Any] | None,
    selected_option: str | None,
    written_answer: str,
    learner_name: str,
) -> tuple[Any, ...]:
    """Grade and persist the entire set in one final submission."""
    state = _save_current_draft(
        exercise_state, selected_option, written_answer
    )
    questions = state.get("questions")
    if not isinstance(questions, list) or not questions:
        return state, *empty_exercise_view(), "Chưa có bài tập đang hoạt động."

    drafts = dict(state.get("draft_answers", {}))
    missing_indexes: list[int] = []
    for index, question in enumerate(questions):
        answer = str(drafts.get(str(index), "")).strip()
        if question["question_type"] == "multiple_choice":
            is_answered = answer.upper() in {"A", "B", "C", "D"}
        else:
            is_answered = bool(answer)
        if not is_answered:
            missing_indexes.append(index)
    if missing_indexes:
        state["current_index"] = missing_indexes[0]
        missing_labels = ", ".join(str(index + 1) for index in missing_indexes)
        state["notice"] = (
            f"⚠️ Bạn chưa trả lời câu: **{missing_labels}**. "
            "Hệ thống đã chuyển tới câu đầu tiên còn thiếu."
        )
        try:
            user_id = database.get_or_create_user(normalize_learner_name(learner_name))
            progress = progress_markdown(user_id)
        except DatabaseError as exc:
            progress = f"⚠️ {exc}"
        return state, *exercise_view(state), progress

    if state.get("completed"):
        try:
            user_id = database.get_or_create_user(normalize_learner_name(learner_name))
            progress = progress_markdown(user_id)
        except DatabaseError as exc:
            progress = f"⚠️ {exc}"
        return state, *exercise_view(state), progress

    try:
        user_id = database.get_or_create_user(normalize_learner_name(learner_name))
        results: dict[str, bool] = {}
        feedbacks: dict[str, str] = {}
        attempts: list[dict[str, Any]] = []
        for index, question in enumerate(questions):
            key = str(index)
            answer = str(drafts[key]).strip()
            is_correct = exercises.check_answer(question, answer)
            results[key] = is_correct
            feedback = "✅ **Chính xác!**" if is_correct else "❌ **Chưa đúng.**"
            feedbacks[key] = (
                f"{feedback}\n\n**Đáp án:** {question['correct_answer']}\n\n"
                f"**Giải thích:** {question['explanation_vi']}"
            )
            attempts.append(
                {
                    "question_id": int(question["question_id"]),
                    "user_answer": answer,
                    "is_correct": is_correct,
                    "skill": str(question["skill"]),
                }
            )

        database.submit_exercise_session(
            user_id,
            int(state["session_id"]),
            attempts,
        )

        state["graded"] = {str(index): True for index in range(len(questions))}
        state["results"] = results
        state["feedbacks"] = feedbacks
        state["correct_count"] = sum(bool(value) for value in results.values())
        state.pop("notice", None)
        score_percent = round(state["correct_count"] / len(questions) * 100)
        state["completion_summary"] = (
            f"Đã nộp toàn bộ: {state['correct_count']}/{len(questions)} "
            f"({score_percent}%)."
        )
        state["completed"] = True
        return state, *exercise_view(state), progress_markdown(user_id)
    except DatabaseError as exc:
        state["notice"] = f"⚠️ {exc}"
        return state, *exercise_view(state), f"⚠️ {exc}"


def handle_submit(
    message: str,
    history: list[ChatMessage] | None,
    mode: str,
    scenario: str,
    learner_name: str,
    exercise_state: dict[str, Any] | None,
) -> tuple[str, list[ChatMessage], str, dict[str, Any]]:
    """Route textbox input to chat services or the exercise engine."""
    if mode == MODE_EXERCISES:
        _, progress = load_workspace(learner_name, mode, scenario)
        return "", list(history or []), progress, dict(exercise_state or {})
    textbox, updated_history, progress = generate_reply(
        message, history, mode, scenario, learner_name
    )
    return textbox, updated_history, progress, dict(exercise_state or {})


def change_mode(
    learner_name: str,
    mode: str,
    scenario: str,
) -> tuple[dict, dict, dict, list[ChatMessage], str]:
    """Switch between the conversation and dedicated exercise workspaces."""
    history, progress = load_workspace(learner_name, mode, scenario)
    return (
        gr.update(visible=mode == MODE_ROLEPLAY),
        gr.update(visible=mode == MODE_EXERCISES),
        gr.update(visible=mode != MODE_EXERCISES),
        history,
        progress,
    )


def change_scenario(
    learner_name: str,
    mode: str,
    scenario: str,
) -> tuple[list[ChatMessage], str]:
    """Restore the selected saved role-play scene."""
    return load_workspace(learner_name, mode, scenario)


def clear_conversation(
    learner_name: str,
    mode: str,
    scenario: str,
) -> tuple[list[ChatMessage], str, str, dict[str, Any], dict]:
    """Delete only the current persisted conversation context."""
    try:
        user_id = database.get_or_create_user(normalize_learner_name(learner_name))
        if mode != MODE_EXERCISES:
            database.clear_history(user_id, mode, context_scenario(mode, scenario))
        return (
            initial_history(mode, scenario),
            "",
            progress_markdown(user_id),
            {},
            gr.update(value=None),
        )
    except DatabaseError as exc:
        return (
            initial_history(mode, scenario),
            "",
            f"⚠️ {exc}",
            {},
            gr.update(value=None),
        )


def _attachment_paths(value: Any) -> list[str]:
    values = value if isinstance(value, list) else [value]
    paths: list[str] = []
    for item in values:
        if not item:
            continue
        path = getattr(item, "name", None)
        if not path and isinstance(item, dict):
            path = item.get("path") or item.get("name")
        path = path or str(item)
        if path and path not in paths:
            paths.append(path)
    return paths


def attachment_preview(
    paths: list[str] | None, errors: list[str] | None = None
) -> str:
    items = [Path(path).name for path in (paths or [])]
    lines = [f"📎 `{name}`" for name in items]
    lines.extend(errors or [])
    return "  \n".join(lines)


def stage_attachments(
    current: list[str] | None, incoming: Any
) -> tuple[list[str], str]:
    candidates = [*(current or []), *_attachment_paths(incoming)]
    paths, errors = validate_attachment_batch(candidates)
    return paths, attachment_preview(paths, errors)


def stage_attachments_and_reset_search(
    current: list[str] | None, incoming: Any
) -> tuple[list[str], str, str]:
    """Stage attachments and clear results that belong to an older image."""
    paths, preview = stage_attachments(current, incoming)
    return paths, preview, ""


def _safe_markdown_text(value: str) -> str:
    return re.sub(r"[\[\]()`*_<>]", "", re.sub(r"\s+", " ", value)).strip()


GEN_MODE_VALUES = ("image", "gif", "video")


_MEDIA_MODE_LABELS = {
    "vi": {"image": "ảnh", "gif": "GIF", "video": "video ngắn"},
    "en": {"image": "image", "gif": "GIF", "video": "short video"},
}


def generate_media_ui(
    prompt: str,
    mode_value: str,
    interface_language: str,
):
    """Render locally generated media with live progress and a busy button."""
    language = "en" if interface_language == "en" else "vi"
    mode = mode_value if mode_value in GEN_MODE_VALUES else "image"
    mode_label = _MEDIA_MODE_LABELS[language][mode]
    hidden_image = gr.update(value=None, visible=False)
    hidden_video = gr.update(value=None, visible=False)
    idle_button = gr.update(interactive=True, value="✨ Tạo ngay")
    busy_button = gr.update(
        interactive=False,
        value="⏳ Đang tạo..." if language == "vi" else "⏳ Creating...",
    )
    if not str(prompt or "").strip():
        message = (
            "⚠️ Hãy nhập mô tả nội dung muốn tạo."
            if language == "vi"
            else "⚠️ Please describe what to create."
        )
        yield message, idle_button, hidden_image, hidden_video
        return

    hint = (
        "💡 Lần đầu sau khi mở app, hệ thống phải nạp model vào GPU nên mất khoảng "
        "40–60 giây; các lần sau chỉ còn vài giây."
        if language == "vi"
        else "💡 The first run after launch loads the model into the GPU (~40-60s); "
        "later runs take only a few seconds."
    )
    accepted = (
        f"📨 **Đã gửi mô tả tới bộ tạo {mode_label}!** Đang khởi động bộ sinh ảnh..."
        if language == "vi"
        else f"📨 **Prompt sent to the {mode_label} generator!** Warming up..."
    )
    yield f"{accepted}\n\n> {hint}", busy_button, hidden_image, hidden_video

    result: dict[str, Any] = {}

    def _run() -> None:
        try:
            result["path"] = imagegen_service.generate(prompt, mode=mode)
        except ImageGenError as exc:
            result["error"] = str(exc)

    worker = threading.Thread(target=_run, daemon=True)
    worker.start()
    started_at = time.perf_counter()
    while worker.is_alive():
        elapsed = int(time.perf_counter() - started_at)
        minutes, seconds = divmod(elapsed, 60)
        progress_line = (
            f"⏳ Đang tạo {mode_label}... đã chạy **{minutes} phút {seconds} giây**"
            if language == "vi"
            else f"⏳ Creating {mode_label}... **{minutes}m {seconds}s** elapsed"
        )
        yield f"{progress_line}\n\n> {hint}", busy_button, hidden_image, hidden_video
        time.sleep(2)

    elapsed = int(time.perf_counter() - started_at)
    minutes, seconds = divmod(elapsed, 60)
    duration = (
        f"{minutes} phút {seconds} giây" if language == "vi" else f"{minutes}m {seconds}s"
    )
    if result.get("error"):
        message = f"⚠️ {_safe_markdown_text(str(result['error']))}"
        yield message, idle_button, hidden_image, hidden_video
        return
    path = result["path"]
    if language == "vi":
        status = f"✅ Đã tạo xong sau {duration}: **{path.name}**\n\nLưu tại `{path}`"
    else:
        status = f"✅ Created in {duration}: **{path.name}**\n\nSaved at `{path}`"
    if mode == "video":
        yield status, idle_button, hidden_image, gr.update(value=str(path), visible=True)
    else:
        yield status, idle_button, gr.update(value=str(path), visible=True), hidden_video


def _keywords_from_text(text: str, limit: int = 12) -> str:
    """Derive compact search keywords from a vision description or OCR text."""
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    if not clean:
        return ""
    words = re.findall(r"[\wÀ-ỹ][\wÀ-ỹ'-]*", clean)
    return " ".join(words[:limit])


def search_staged_image_ui(
    staged_files: list[str] | None,
    allow_external: bool,
    interface_language: str,
) -> str:
    """Render privacy-aware visual-search results for the newest staged image."""
    language = "en" if interface_language == "en" else "vi"
    images = [
        path
        for path in (staged_files or [])
        if Path(path).suffix.casefold() in IMAGE_SUFFIXES
    ]
    if not images:
        return (
            "⚠️ Please attach a PNG, JPG, JPEG, or WEBP image first."
            if language == "en"
            else "⚠️ Hãy đính kèm một ảnh PNG, JPG, JPEG hoặc WEBP trước."
        )
    description = ""
    try:
        description = vision_service.describe(images[-1])
    except VisionError:
        description = ""
    query_override = _keywords_from_text(description)
    try:
        result = visual_search_service.search(
            images[-1], bool(allow_external), query_override=query_override
        )
    except VisualSearchError as exc:
        return f"⚠️ {_safe_markdown_text(str(exc))}"

    heading = "### Visual search" if language == "en" else "### Tìm kiếm hình ảnh"
    query_label = "Search keywords" if language == "en" else "Từ khóa tìm kiếm"
    lines = [heading, f"**{query_label}:** `{_safe_markdown_text(result.query)}`"]
    if description:
        seen_label = (
            "### What the local vision model sees"
            if language == "en"
            else "### Model thị giác local nhìn thấy"
        )
        lines.append(f"{seen_label}\n\n{_safe_markdown_text(description)}")
    if result.notice:
        lines.append(f"> {_safe_markdown_text(result.notice)}")
    if result.labels:
        label = "Detected labels" if language == "en" else "Nhãn nhận diện"
        lines.append(f"**{label}:** " + ", ".join(_safe_markdown_text(x) for x in result.labels))
    links_label = "Search tools" if language == "en" else "Công cụ tìm kiếm"
    lines.append(
        f"**{links_label}:** [Google Images](<{result.google_images_url}>) · "
        f"[Google Lens](<{result.lens_url}>)"
    )
    web_hits_label = "Web results" if language == "en" else "Kết quả trên web"
    try:
        web_hits = web_search_service.search(result.query, max_results=5)
        lines.append(f"**{web_hits_label}:**")
        lines.extend(
            f"- [{_safe_markdown_text(hit['title'])}](<{hit['url']}>)"
            for hit in web_hits
        )
    except WebSearchError:
        pass
    if result.pages:
        title = "Pages containing this image" if language == "en" else "Trang có chứa ảnh này"
        lines.append(f"**{title}:**")
        lines.extend(
            f"- [{_safe_markdown_text(page['title'])}](<{page['url']}>)"
            for page in result.pages
        )
    if result.matching_images:
        title = "Matching images" if language == "en" else "Ảnh trùng hoặc gần trùng"
        lines.append(f"**{title}:** " + " · ".join(
            f"[#{index}](<{url}>)" for index, url in enumerate(result.matching_images, 1)
        ))
    if result.similar_images:
        title = "Similar images" if language == "en" else "Ảnh tương tự"
        lines.append(f"**{title}:** " + " · ".join(
            f"[#{index}](<{url}>)" for index, url in enumerate(result.similar_images, 1)
        ))
    return "\n\n".join(lines)


def format_processing_time(elapsed_seconds: float) -> str:
    """Format one response duration in the compact UI wording."""
    seconds = max(0, int(round(elapsed_seconds)))
    minutes, remaining = divmod(seconds, 60)
    return f"Đã xử lý trong {minutes} phút {remaining} giây"


def handle_composer_submit(
    composer: dict[str, Any] | str | None,
    staged_files: list[str] | None,
    history: list[ChatMessage] | None,
    mode: str,
    scenario: str,
    learner_name: str,
    exercise_state: dict[str, Any] | None,
    web_search_enabled: bool = False,
) -> tuple[None, list[ChatMessage], str, dict[str, Any], list[str], str, dict]:
    """Handle text plus dropped/selected files from the unified composer."""
    started_at = time.perf_counter()
    if isinstance(composer, dict):
        text = str(composer.get("text") or "").strip()
        dropped = _attachment_paths(composer.get("files") or [])
    else:
        text = str(composer or "").strip()
        dropped = []
    candidates: list[str] = list(dict.fromkeys([*(staged_files or []), *dropped]))
    files, validation_errors = validate_attachment_batch(candidates)
    if not text and not files:
        try:
            user_id = database.get_or_create_user(normalize_learner_name(learner_name))
            progress = progress_markdown(user_id)
        except DatabaseError as exc:
            progress = f"⚠️ {exc}"
        updated = list(history or [])
        if validation_errors:
            updated.append(
                {
                    "role": "assistant",
                    "content": "**Không thể nhận tệp**\n\n"
                    + "\n".join(f"- {item}" for item in validation_errors),
                }
            )
        return (
            None,
            updated,
            progress,
            dict(exercise_state or {}),
            [],
            "",
            gr.update(value=None),
        )
    if mode == MODE_EXERCISES:
        _, progress = load_workspace(learner_name, mode, scenario)
        return (
            None,
            list(history or []),
            progress,
            dict(exercise_state or {}),
            [],
            "",
            gr.update(value=None),
        )

    user_id = database.get_or_create_user(normalize_learner_name(learner_name))
    document_ids: list[int] = []
    image_paths: list[str] = []
    notes: list[str] = list(validation_errors)
    document_suffixes = DocumentParser.SUPPORTED_SUFFIXES
    for file_path in files:
        path = Path(file_path)
        try:
            if path.suffix.casefold() in IMAGE_SUFFIXES:
                image_paths.append(str(path))
                notes.append(f"✅ {path.name}: ảnh đã nhận")
            elif path.suffix.casefold() in document_suffixes:
                result = study_hub.ingest(user_id, path)
                document_ids.append(int(result["document_id"]))
                notes.append(
                    f"✅ {path.name}: {result['engine']} · {result['chunks']} đoạn"
                )
            elif path.suffix.casefold() in VIDEO_SUFFIXES:
                study_hub.store_media_attachment(user_id, path)
                notes.append(
                    f"✅ {path.name}: đã lưu local; chưa bật phiên âm/phân tích video"
                )
            else:
                notes.append(f"⚠️ {path.name}: định dạng chưa được hỗ trợ")
        except (StudyHubError, DatabaseError, LocalAIError, OSError) as exc:
            notes.append(f"⚠️ {path.name}: {exc}")

    vision_context = ""
    for image_path in image_paths:
        try:
            description = vision_service.describe(image_path, question=text)
        except VisionError as exc:
            notes.append(f"👁️ {Path(image_path).name}: {exc}")
            continue
        vision_context += (
            f"\n\n[MÔ TẢ ẢNH {Path(image_path).name} — do model thị giác local nhìn]\n"
            f"{description}"
        )

    shown_text = text or (
        "Hãy mô tả ảnh tôi vừa gửi." if image_paths else "Hãy tóm tắt nội dung tệp tôi vừa gửi."
    )
    file_labels = " ".join(f"📎 {Path(path).name}" for path in files)
    user_content = f"{shown_text}\n\n{file_labels}".strip()
    updated = list(history or []) + [{"role": "user", "content": user_content}]
    web_result = None
    web_notice = ""
    if web_search_enabled and text:
        try:
            web_result = web_search_service.gather(text)
        except WebSearchError as exc:
            web_notice = f"⚠️ Tìm kiếm web: {exc}"
    if document_ids:
        try:
            rag = study_hub.ask(user_id, shown_text, document_ids)
            sources = "\n".join(
                f"- [{item['label']}] {item['title']}"
                for item in rag.get("sources", [])
            )
            answer = rag["answer"]
            if sources:
                answer += f"\n\n**Nguồn đã dùng**\n{sources}"
        except (StudyHubError, DatabaseError, LocalAIError) as exc:
            answer = f"Mình đã nhận tệp nhưng chưa thể trả lời bằng RAG: {exc}"
    elif text or vision_context:
        _, generated, _ = generate_reply(
            shown_text, history, mode, scenario, learner_name,
            vision_context=vision_context,
            web_result=web_result,
        )
        answer = str(generated[-1]["content"]) if generated else ""
    else:
        answer = "Mình đã nhận tệp. " + (
            "Video cần pipeline phiên âm để hiểu nội dung."
        )
    if web_notice:
        answer += f"\n\n{web_notice}"
    if notes:
        answer += "\n\n**Tệp đính kèm**\n" + "\n".join(f"- {note}" for note in notes)
    audio_update = gr.update(value=None)
    try:
        preferences = database.get_user_preferences(user_id)
        if preferences.voice_output:
            audio_path = voice_line_service.synthesize_with_intro(
                answer, preferences.language, mode=mode
            )
            audio_update = gr.update(value=audio_path, visible=True)
    except (DatabaseError, LocalTTSError) as exc:
        answer += f"\n\n⚠️ Giọng đọc local: {exc}"
    duration = format_processing_time(time.perf_counter() - started_at)
    answer += f"\n\n<small>{duration}</small>"
    updated.append({"role": "assistant", "content": answer})
    if document_ids:
        database.save_exchange(
            user_id, mode, context_scenario(mode, scenario), shown_text, answer
        )
    return (
        None,
        updated,
        progress_markdown(user_id),
        dict(exercise_state or {}),
        [],
        "",
        audio_update,
    )


def build_app() -> gr.Blocks:
    """Create the complete Tris AI interface."""
    with gr.Blocks(
        title="Tris AI",
        analytics_enabled=False,
    ) as demo:
        exercise_state = gr.State({})
        auth_state = gr.State({})
        attachment_state = gr.State([])

        with gr.Row(elem_id="app-header"):
            icon_data = base64.b64encode(APP_ICON_PATH.read_bytes()).decode("ascii")
            gr.HTML(
                f'<img src="data:image/x-icon;base64,{icon_data}" alt="Tris AI">',
                elem_id="brand-icon",
                min_width=44,
            )
            brand_block = gr.Markdown(
                f"### Tris AI ▾\n`{MODEL_NAME}` · chạy local",
                elem_id="brand-block",
                scale=5,
            )
            with gr.Row(elem_id="header-actions", scale=2):
                header_login_button = gr.Button(
                    "Đăng nhập",
                    link=f"{OAUTH_PUBLIC_BASE_URL}/auth/login",
                    variant="secondary",
                    size="sm",
                )
                header_register_button = gr.Button(
                    "Đăng ký",
                    link=f"{OAUTH_PUBLIC_BASE_URL}/auth/register",
                    variant="primary",
                    size="sm",
                )
                header_account_badge = gr.Markdown(
                    "",
                    elem_id="header-account",
                    visible=False,
                )
                header_logout_button = gr.Button(
                    "Đăng xuất",
                    variant="secondary",
                    size="sm",
                    visible=False,
                    elem_id="header-logout",
                )

        with gr.Sidebar(
            label="Cài đặt",
            open=False,
            position="right",
            width=420,
            elem_id="settings-panel",
        ):
            settings_heading = gr.Markdown("## Cài đặt chung")
            account_status = gr.Markdown(
                "Bạn đang dùng chế độ local chưa đăng nhập. "
                "Tài khoản và mật khẩu được lưu riêng trong PostgreSQL."
            )
            learner_name = gr.Textbox(
                value=DEFAULT_LEARNER_NAME,
                label="Hồ sơ người học",
                info="Dữ liệu học của mỗi hồ sơ được tách riêng trên máy.",
            )
            with gr.Accordion("Giao diện", open=True) as appearance_accordion:
                theme_setting = gr.Dropdown(
                    choices=[
                        ("Hệ thống", "system"),
                        ("Sáng", "light"),
                        ("Tối", "dark"),
                    ],
                    value="system",
                    label="Chủ đề",
                    interactive=True,
                )
                interface_language_setting = gr.Dropdown(
                    choices=[("Tiếng Việt (VI)", "vi"), ("English (EN)", "en")],
                    value="vi",
                    label="Ngôn ngữ hệ thống",
                    interactive=True,
                )
                language_setting = gr.Dropdown(
                    choices=[("Tiếng Việt", "vi"), ("English", "en")],
                    value="vi",
                    label="Ngôn ngữ phản hồi của AI",
                    interactive=True,
                )
                adaptive_setting = gr.Checkbox(
                    value=True,
                    label="Cá nhân hóa theo kỹ năng và lỗi đã học",
                    interactive=True,
                )
                voice_setting = gr.Checkbox(
                    value=False,
                    label="Bật nhập bằng giọng nói",
                    interactive=True,
                )
                mascot_voice_setting = gr.Checkbox(
                    value=False,
                    label="Bật giọng linh vật Tris đọc phản hồi",
                    info="Giọng local nguyên bản; không dùng API và không clone nhân vật khác.",
                    interactive=True,
                )
            save_settings_button = gr.Button(
                "Lưu cài đặt", variant="primary"
            )
            settings_status = gr.Markdown("")
            with gr.Accordion("Tài khoản & bảo mật", open=False) as account_accordion:
                gr.Markdown(social_login_status_markdown())
                settings_login_button = gr.Button(
                    "Mở trang đăng nhập",
                    link=f"{OAUTH_PUBLIC_BASE_URL}/auth/login",
                    size="sm",
                )
                settings_register_button = gr.Button(
                    "Mở trang đăng ký",
                    link=f"{OAUTH_PUBLIC_BASE_URL}/auth/register",
                    size="sm",
                )
                with gr.Group():
                    current_password = gr.Textbox(
                        label="Mật khẩu hiện tại",
                        type="password",
                    )
                    new_password = gr.Textbox(
                        label="Mật khẩu mới",
                        type="password",
                    )
                    new_password_confirm = gr.Textbox(
                        label="Nhập lại mật khẩu mới",
                        type="password",
                    )
                    change_password_button = gr.Button("Đổi mật khẩu")
                logout_button = gr.Button("Đăng xuất", variant="secondary")
            with gr.Accordion("Dữ liệu & backup", open=False) as data_accordion:
                gr.Markdown(
                    "Backup SQLite và hồ sơ JSON được tạo trong thư mục local của dự án."
                )
                with gr.Row():
                    backup_button = gr.Button("Tạo backup SQLite")
                    export_button = gr.Button("Xuất dữ liệu JSON")
                maintenance_status = gr.Markdown("")
                maintenance_download = gr.File(
                    label="Tệp vừa tạo", interactive=False
                )
            with gr.Accordion("Tài liệu đã tải", open=False) as documents_accordion:
                document_library = gr.Markdown("Đang tải thư viện...")
                selected_documents = gr.CheckboxGroup(
                    choices=[],
                    label="Tài liệu dùng để tạo bài tập",
                )
                document_exercise_skill = gr.Dropdown(
                    choices=exercises.EXERCISE_SKILLS,
                    value=exercises.AUTO_SKILL,
                    label="Kỹ năng",
                )
                document_exercise_difficulty = gr.Dropdown(
                    choices=exercises.DIFFICULTIES,
                    value="Adaptive",
                    label="Độ khó",
                )
                document_exercise_count = gr.Dropdown(
                    choices=exercises.QUESTION_COUNTS,
                    value=5,
                    label="Số câu",
                )
                create_document_exercise = gr.Button(
                    "Tạo bài từ tài liệu", variant="secondary"
                )

        with gr.Row():
            mode = gr.Radio(
                choices=MODES,
                value=MODE_CONVERSATION,
                label="Chế độ học",
                scale=4,
            )
            scenario = gr.Dropdown(
                choices=roleplay.SCENARIOS,
                value=roleplay.SCENARIOS[0],
                label="Scenario",
                visible=True,
                scale=2,
            )

        with gr.Group(visible=False) as exercise_controls:
            with gr.Row():
                exercise_skill = gr.Dropdown(
                    choices=exercises.EXERCISE_SKILLS,
                    value=exercises.AUTO_SKILL,
                    label="Exercise skill",
                    info="Auto ưu tiên kỹ năng yếu nhất đã quan sát.",
                    scale=2,
                )
                exercise_difficulty = gr.Dropdown(
                    choices=exercises.DIFFICULTIES,
                    value="Adaptive",
                    label="Difficulty",
                    scale=1,
                )
                exercise_count = gr.Dropdown(
                    choices=exercises.QUESTION_COUNTS,
                    value=5,
                    label="Questions",
                    scale=1,
                )
                create_exercise = gr.Button(
                    "Tạo bài tập", variant="primary", scale=1
                )

            with gr.Group(elem_id="exercise-card"):
                with gr.Row(elem_id="exercise-layout"):
                    with gr.Column(scale=4, min_width=560, elem_id="question-main"):
                        exercise_question = gr.Markdown(
                            "Chọn cấu hình rồi nhấn **Tạo bài tập** để bắt đầu."
                        )
                        exercise_options = gr.Radio(
                            choices=[],
                            label="Chọn đáp án",
                            visible=False,
                            interactive=False,
                            elem_id="exercise-options",
                        )
                        exercise_written_answer = gr.Textbox(
                            label="Câu trả lời của bạn",
                            placeholder="Nhập câu trả lời...",
                            visible=False,
                            interactive=False,
                            lines=2,
                        )
                        with gr.Row():
                            previous_exercise = gr.Button(
                                "← Câu trước", interactive=False
                            )
                            flag_exercise = gr.Button(
                                "🚩 Cắm cờ", interactive=False
                            )
                            next_exercise = gr.Button(
                                "Câu sau →", interactive=False
                            )
                    with gr.Column(
                        scale=1,
                        min_width=260,
                        elem_id="question-sidebar",
                    ):
                        question_board_heading = gr.Markdown("### Bảng câu hỏi")
                        question_buttons: list[gr.Button] = []
                        for row_start in range(0, MAX_QUESTION_BUTTONS, 5):
                            with gr.Row():
                                for index in range(row_start, row_start + 5):
                                    question_buttons.append(
                                        gr.Button(
                                            str(index + 1),
                                            visible=False,
                                            interactive=False,
                                            elem_classes="question-nav-button",
                                            size="sm",
                                            min_width=42,
                                            scale=1,
                                        )
                                    )
                        exercise_status = gr.Markdown(
                            "**Tiến độ:** Chưa có bài tập."
                        )
                        submit_exercise = gr.Button(
                            "Nộp toàn bộ bài",
                            variant="primary",
                            interactive=False,
                        )
                exercise_feedback = gr.Markdown("", elem_id="exercise-feedback")
                exercise_report = gr.Markdown(
                    "", visible=False, elem_id="exercise-report"
                )

        with gr.Accordion("Tiến độ & ôn tập", open=False) as progress_accordion:
            progress = gr.Markdown("Đang tải bộ nhớ local...")
            review_summary = gr.Markdown("Đang tải lịch sử ôn tập...")
            with gr.Row():
                daily_goal = gr.Number(
                    value=10,
                    minimum=1,
                    maximum=200,
                    precision=0,
                    label="Mục tiêu câu/ngày",
                )
                save_goal = gr.Button("Lưu mục tiêu", variant="secondary")
                refresh_review = gr.Button("Làm mới thống kê")
            goal_status = gr.Markdown("")
            with gr.Row():
                review_kind = gr.Dropdown(
                    choices=[
                        ("Câu đã làm sai", "wrong"),
                        ("Câu đã cắm cờ", "flagged"),
                        ("Điểm yếu gần đây", "weak"),
                    ],
                    value="wrong",
                    label="Nguồn ôn tập",
                )
                review_count = gr.Dropdown(
                    choices=[3, 5, 10], value=5, label="Số câu tối đa"
                )
                start_review = gr.Button("Bắt đầu ôn", variant="primary")
            review_status = gr.Markdown("")

        with gr.Group() as conversation_workspace:
            chatbot = gr.Chatbot(
                label="Tris AI",
                height=500,
                layout="bubble",
                placeholder="Mình có thể giúp gì cho việc học tiếng Anh của bạn?",
            )
            mascot_audio = gr.Audio(
                label="Giọng linh vật Tris",
                type="filepath",
                format="wav",
                autoplay=False,
                interactive=False,
                visible=False,
                show_label=False,
                container=False,
                buttons=[],
                elem_id="mascot-audio",
            )
            with gr.Column(elem_id="composer-shell"):
                with gr.Accordion(
                    "＋ Đính kèm",
                    open=False,
                    elem_id="attachment-menu",
                ) as attachment_accordion:
                    attachment_help = gr.Markdown(
                        "Chọn đúng loại hoặc kéo thả trực tiếp vào khung nhập bên dưới."
                        f"\n\n**Giới hạn:** {_upload_limits_text()}"
                    )
                    with gr.Row():
                        upload_document = gr.UploadButton(
                            "📄 Gửi tệp",
                            file_types=[".pdf", ".txt", ".md", ".docx"],
                            file_count="multiple",
                            type="filepath",
                        )
                        upload_image = gr.UploadButton(
                            "🖼️ Gửi ảnh",
                            file_types=["image"],
                            file_count="multiple",
                            type="filepath",
                        )
                        upload_video = gr.UploadButton(
                            "🎬 Gửi video",
                            file_types=["video"],
                            file_count="multiple",
                            type="filepath",
                        )
                    visual_consent = gr.Checkbox(
                        label="Cho phép gửi ảnh đã chọn tới Google để tìm ảnh tương tự",
                        value=False,
                    )
                    visual_search_button = gr.Button(
                        "🔎 Tìm ảnh tương tự trên web",
                        variant="secondary",
                    )
                    visual_search_results = gr.Markdown("")
                attachment_preview_box = gr.Markdown("")
                web_search_toggle = gr.Checkbox(
                    label="🌐 Tìm kiếm web để trả lời (kèm nguồn [W1], [W2])",
                    value=False,
                )
                with gr.Accordion(
                    "🎨 Tạo ảnh / GIF / video ngắn",
                    open=False,
                ) as media_accordion:
                    gen_prompt = gr.Textbox(
                        label="Mô tả nội dung muốn tạo (tiếng Việt hoặc English)",
                        placeholder="Ví dụ: một chú shiba dễ thương đang đọc sách trên cỏ...",
                        lines=2,
                        max_lines=4,
                    )
                    gen_mode = gr.Radio(
                        choices=[
                            ("🖼️ Ảnh", "image"),
                            ("🎞️ GIF", "gif"),
                            ("🎬 Video ngắn", "video"),
                        ],
                        value="image",
                        label="Kiểu nội dung",
                    )
                    gen_button = gr.Button("✨ Tạo ngay", variant="primary")
                    gen_status = gr.Markdown("")
                    gen_image = gr.Image(
                        show_label=False, visible=False, interactive=False
                    )
                    gen_video = gr.Video(show_label=False, visible=False)
                message = gr.MultimodalTextbox(
                    label=None,
                    show_label=False,
                    placeholder="Nhắn cho Tris AI...",
                    sources=["upload"],
                    file_types=[
                        ".pdf", ".txt", ".md", ".docx",
                        ".png", ".jpg", ".jpeg", ".webp",
                        ".mp4", ".mov", ".webm", ".mkv", ".avi",
                    ],
                    file_count="multiple",
                    lines=2,
                    max_lines=8,
                    autofocus=True,
                    submit_btn="↑",
                )
                composer_footer = gr.Markdown(
                    _upload_limits_text(),
                )
            clear = gr.Button("Xóa cuộc trò chuyện hiện tại", size="sm")

        interface_components = [
            brand_block,
            header_login_button,
            header_register_button,
            settings_heading,
            account_status,
            learner_name,
            appearance_accordion,
            theme_setting,
            interface_language_setting,
            language_setting,
            adaptive_setting,
            voice_setting,
            mascot_voice_setting,
            save_settings_button,
            account_accordion,
            settings_login_button,
            settings_register_button,
            current_password,
            new_password,
            new_password_confirm,
            change_password_button,
            logout_button,
            data_accordion,
            backup_button,
            export_button,
            maintenance_download,
            documents_accordion,
            selected_documents,
            document_exercise_skill,
            document_exercise_difficulty,
            document_exercise_count,
            create_document_exercise,
            mode,
            scenario,
            exercise_skill,
            exercise_difficulty,
            exercise_count,
            create_exercise,
            exercise_options,
            exercise_written_answer,
            previous_exercise,
            flag_exercise,
            next_exercise,
            question_board_heading,
            submit_exercise,
            progress_accordion,
            daily_goal,
            save_goal,
            refresh_review,
            review_kind,
            review_count,
            start_review,
            chatbot,
            attachment_accordion,
            attachment_help,
            upload_document,
            upload_image,
            upload_video,
            visual_consent,
            visual_search_button,
            web_search_toggle,
            message,
            composer_footer,
            clear,
            media_accordion,
            gen_prompt,
            gen_mode,
            gen_button,
        ]

        submit_inputs = [
            message,
            attachment_state,
            chatbot,
            mode,
            scenario,
            learner_name,
            exercise_state,
            web_search_toggle,
        ]
        submit_outputs = [
            message,
            chatbot,
            progress,
            exercise_state,
            attachment_state,
            attachment_preview_box,
            mascot_audio,
        ]
        message.submit(
            handle_composer_submit,
            inputs=submit_inputs,
            outputs=submit_outputs,
        ).then(lambda: "", outputs=[visual_search_results])
        for upload in (upload_document, upload_image, upload_video):
            upload.upload(
                stage_attachments_and_reset_search,
                inputs=[attachment_state, upload],
                outputs=[attachment_state, attachment_preview_box, visual_search_results],
            )
        visual_search_button.click(
            search_staged_image_ui,
            inputs=[attachment_state, visual_consent, interface_language_setting],
            outputs=[visual_search_results],
        )
        gen_button.click(
            generate_media_ui,
            inputs=[gen_prompt, gen_mode, interface_language_setting],
            outputs=[gen_status, gen_button, gen_image, gen_video],
        )
        save_settings_button.click(
            save_general_settings,
            inputs=[
                learner_name,
                theme_setting,
                interface_language_setting,
                language_setting,
                adaptive_setting,
                voice_setting,
                mascot_voice_setting,
            ],
            outputs=[settings_status, message],
        ).then(
            interface_language_updates,
            inputs=[interface_language_setting, auth_state],
            outputs=interface_components,
        ).then(
            fn=None,
            inputs=[theme_setting],
            outputs=[],
            js=APPLY_THEME_JS,
        )
        interface_language_setting.change(
            interface_language_updates,
            inputs=[interface_language_setting, auth_state],
            outputs=interface_components,
        )
        theme_setting.change(
            fn=None,
            inputs=[theme_setting],
            outputs=[],
            js=APPLY_THEME_JS,
        )

        exercise_view_outputs = [
            exercise_question,
            exercise_options,
            exercise_written_answer,
            exercise_feedback,
            exercise_status,
            previous_exercise,
            flag_exercise,
            next_exercise,
            submit_exercise,
            exercise_report,
            *question_buttons,
        ]

        create_exercise.click(
            generate_exercise,
            inputs=[
                learner_name,
                exercise_skill,
                exercise_difficulty,
                exercise_count,
            ],
            outputs=[exercise_state, *exercise_view_outputs, progress],
        )

        exercise_navigation_inputs = [
            exercise_state,
            exercise_options,
            exercise_written_answer,
        ]
        exercise_navigation_outputs = [exercise_state, *exercise_view_outputs]
        previous_exercise.click(
            previous_exercise_question,
            inputs=exercise_navigation_inputs,
            outputs=exercise_navigation_outputs,
        )
        next_exercise.click(
            next_exercise_question,
            inputs=exercise_navigation_inputs,
            outputs=exercise_navigation_outputs,
        )
        exercise_options.input(
            save_exercise_draft_status,
            inputs=exercise_navigation_inputs,
            outputs=[exercise_state, exercise_status, *question_buttons],
        )
        exercise_written_answer.blur(
            save_exercise_draft_status,
            inputs=exercise_navigation_inputs,
            outputs=[exercise_state, exercise_status, *question_buttons],
        )
        for index, question_button in enumerate(question_buttons):
            target_index = gr.State(index)
            question_button.click(
                jump_to_exercise_question,
                inputs=[*exercise_navigation_inputs, target_index],
                outputs=exercise_navigation_outputs,
            )
        flag_exercise.click(
            toggle_exercise_flag,
            inputs=[*exercise_navigation_inputs, learner_name],
            outputs=exercise_navigation_outputs,
        )
        submit_exercise.click(
            submit_exercise_answer,
            inputs=[*exercise_navigation_inputs, learner_name],
            outputs=[exercise_state, *exercise_view_outputs, progress],
        )

        mode.change(
            change_mode,
            inputs=[learner_name, mode, scenario],
            outputs=[
                scenario,
                exercise_controls,
                conversation_workspace,
                chatbot,
                progress,
            ],
        )
        scenario.change(
            change_scenario,
            inputs=[learner_name, mode, scenario],
            outputs=[chatbot, progress],
        )
        learner_name.submit(
            load_workspace_with_state,
            inputs=[learner_name, mode, scenario],
            outputs=[
                chatbot,
                progress,
                exercise_state,
                *exercise_view_outputs,
            ],
        ).then(
            load_general_settings,
            inputs=[learner_name],
            outputs=[
                theme_setting,
                interface_language_setting,
                language_setting,
                adaptive_setting,
                voice_setting,
                mascot_voice_setting,
                settings_status,
                message,
            ],
        ).then(
            interface_language_updates,
            inputs=[interface_language_setting, auth_state],
            outputs=interface_components,
        ).then(
            fn=None,
            inputs=[theme_setting],
            outputs=[],
            js=APPLY_THEME_JS,
        )
        learner_name.blur(
            load_workspace_with_state,
            inputs=[learner_name, mode, scenario],
            outputs=[
                chatbot,
                progress,
                exercise_state,
                *exercise_view_outputs,
            ],
        ).then(
            load_general_settings,
            inputs=[learner_name],
            outputs=[
                theme_setting,
                interface_language_setting,
                language_setting,
                adaptive_setting,
                voice_setting,
                mascot_voice_setting,
                settings_status,
                message,
            ],
        ).then(
            interface_language_updates,
            inputs=[interface_language_setting, auth_state],
            outputs=interface_components,
        ).then(
            fn=None,
            inputs=[theme_setting],
            outputs=[],
            js=APPLY_THEME_JS,
        )
        clear.click(
            clear_conversation,
            inputs=[learner_name, mode, scenario],
            outputs=[chatbot, message, progress, exercise_state, mascot_audio],
        ).then(lambda: "", outputs=[visual_search_results])
        logout_button.click(
            logout_account_ui,
            inputs=[auth_state],
            outputs=[auth_state, account_status, learner_name],
        ).then(
            header_auth_ui,
            inputs=[auth_state, interface_language_setting],
            outputs=[
                header_login_button,
                header_register_button,
                header_account_badge,
                header_logout_button,
            ],
        )
        header_logout_button.click(
            logout_account_ui,
            inputs=[auth_state],
            outputs=[auth_state, account_status, learner_name],
        ).then(
            header_auth_ui,
            inputs=[auth_state, interface_language_setting],
            outputs=[
                header_login_button,
                header_register_button,
                header_account_badge,
                header_logout_button,
            ],
        )
        change_password_button.click(
            change_password_ui,
            inputs=[
                auth_state,
                current_password,
                new_password,
                new_password_confirm,
            ],
            outputs=[
                account_status,
                current_password,
                new_password,
                new_password_confirm,
            ],
        )
        save_goal.click(
            save_daily_goal,
            inputs=[learner_name, daily_goal],
            outputs=[goal_status, review_summary],
        )
        refresh_review.click(
            review_dashboard,
            inputs=[learner_name],
            outputs=[review_summary],
        )
        start_review.click(
            start_review_exercise,
            inputs=[learner_name, review_kind, review_count],
            outputs=[
                mode,
                scenario,
                exercise_controls,
                conversation_workspace,
                exercise_state,
                *exercise_view_outputs,
                progress,
                review_status,
            ],
        )
        create_document_exercise.click(
            generate_document_exercise_ui,
            inputs=[
                learner_name,
                selected_documents,
                document_exercise_skill,
                document_exercise_difficulty,
                document_exercise_count,
            ],
            outputs=[
                mode,
                scenario,
                exercise_controls,
                conversation_workspace,
                exercise_state,
                *exercise_view_outputs,
                progress,
                review_status,
            ],
        )
        backup_action = gr.State("backup")
        export_action = gr.State("export")
        backup_button.click(
            maintenance_files,
            inputs=[learner_name, backup_action],
            outputs=[maintenance_status, maintenance_download],
        )
        export_button.click(
            maintenance_files,
            inputs=[learner_name, export_action],
            outputs=[maintenance_status, maintenance_download],
        )
        demo.load(
            social_login_callback_ui,
            inputs=None,
            outputs=[auth_state, account_status, learner_name],
        ).then(
            header_auth_ui,
            inputs=[auth_state, interface_language_setting],
            outputs=[
                header_login_button,
                header_register_button,
                header_account_badge,
                header_logout_button,
            ],
        ).then(
            load_workspace_with_state,
            inputs=[learner_name, mode, scenario],
            outputs=[
                chatbot,
                progress,
                exercise_state,
                *exercise_view_outputs,
            ],
        ).then(
            load_general_settings,
            inputs=[learner_name],
            outputs=[
                theme_setting,
                interface_language_setting,
                language_setting,
                adaptive_setting,
                voice_setting,
                mascot_voice_setting,
                settings_status,
                message,
            ],
        ).then(
            interface_language_updates,
            inputs=[interface_language_setting, auth_state],
            outputs=interface_components,
        ).then(
            fn=None,
            inputs=[theme_setting],
            outputs=[],
            js=APPLY_THEME_JS,
        )
        demo.load(
            review_dashboard,
            inputs=[learner_name],
            outputs=[review_summary],
        )
        demo.load(
            document_library_view,
            inputs=[learner_name],
            outputs=[document_library, selected_documents],
        )
        demo.load(lambda: session_watchdog.connect(), inputs=None, outputs=None)
        demo.unload(lambda: session_watchdog.disconnect())

    return demo


def _find_free_port(host: str, preferred: int) -> int:
    """Return the preferred port, or the next free one if it is busy."""
    for port in range(preferred, preferred + 10):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind((host, port))
            except OSError:
                continue
            return port
    return preferred


def main() -> None:
    """Open the replacement UI; the original Gradio view remains opt-in."""
    if os.getenv("TRIS_LEGACY_UI", "0") != "1":
        from workspace_host import main as launch_workspace
        launch_workspace()
        return
    demo = build_app()
    port = _find_free_port(APP_HOST, APP_PORT)
    if port != APP_PORT:
        print(f"Port {APP_PORT} is busy, using {port} instead.")
    demo.queue(default_concurrency_limit=2).launch(
        server_name=APP_HOST,
        server_port=port,
        share=False,
        show_error=False,
        inbrowser=APP_OPEN_BROWSER,
        css=APP_CSS,
        max_file_size=MAX_VIDEO_BYTES,
        favicon_path=APP_ICON_PATH,
    )


if __name__ == "__main__":
    main()
