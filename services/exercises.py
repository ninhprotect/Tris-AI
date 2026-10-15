"""UI-independent personalized exercise engine for v0.4 and future mobile apps."""

import re
from typing import Any

from ai.llm import OllamaLLM
from database import SkillInsight

AUTO_SKILL = "Auto — Điểm yếu nhất"
EXERCISE_SKILLS = [
    AUTO_SKILL,
    "Past Simple",
    "Present Simple",
    "Present Perfect",
    "Articles",
    "Subject–Verb Agreement",
    "Plurals & Countable Nouns",
    "Prepositions",
    "Word Order",
    "Verb Forms",
    "General Grammar",
    "Vocabulary Usage",
]
DIFFICULTIES = ["Easy", "Medium", "Hard", "Adaptive"]
QUESTION_COUNTS = [3, 5, 10]
QUESTION_TYPES = {
    "multiple_choice",
    "fill_blank",
    "sentence_correction",
    "translation",
    "guided_sentence",
}

EXERCISE_SYSTEM_PROMPT = """
You create concise English exercises for a Vietnamese learner.
Return only data matching the requested JSON schema.

Rules:
- Target exactly the requested English skill and difficulty.
- Use a useful mix of multiple_choice, fill_blank, sentence_correction,
  translation, and guided_sentence when appropriate.
- Prompts are mainly in English; translation prompts may include Vietnamese.
- explanation_vi must clearly explain the answer in Vietnamese.
- For multiple_choice, provide exactly four options and set correct_answer to
  the complete correct option text, not just A/B/C/D.
- The prompt must contain only the question stem. Never repeat A/B/C/D choices
  inside the prompt.
- Each option must contain only its answer text. Do not prefix options with
  A, B, C, D, "A)", "A.", or similar labels; the UI adds those labels.
- For other types, options must be an empty list.
- accepted_answers must contain correct_answer and any genuinely equivalent
  short answers.
- Never reveal the correct answer inside the question prompt.
- Questions must be independent and suitable for a language learner.
""".strip()


class ExerciseError(RuntimeError):
    """Safe exercise generation/validation error for any UI."""


def exercise_schema(question_count: int) -> dict[str, Any]:
    """Create the exact JSON schema sent to Ollama structured output."""
    return {
        "type": "object",
        "properties": {
            "questions": {
                "type": "array",
                "minItems": question_count,
                "maxItems": question_count,
                "items": {
                    "type": "object",
                    "properties": {
                        "question_type": {
                            "type": "string",
                            "enum": sorted(QUESTION_TYPES),
                        },
                        "prompt": {"type": "string"},
                        "options": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "correct_answer": {"type": "string"},
                        "accepted_answers": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "explanation_vi": {"type": "string"},
                    },
                    "required": [
                        "question_type",
                        "prompt",
                        "options",
                        "correct_answer",
                        "accepted_answers",
                        "explanation_vi",
                    ],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["questions"],
        "additionalProperties": False,
    }


def choose_skill(requested_skill: str, insights: list[SkillInsight]) -> str:
    """Resolve Auto to the weakest observed skill without coupling to Gradio."""
    if requested_skill != AUTO_SKILL:
        return requested_skill
    for insight in insights:
        if insight.level in {"Yếu", "Đang cải thiện"}:
            return insight.skill_name
    if insights:
        return insights[0].skill_name
    return "General Grammar"


def generate_questions(
    llm: OllamaLLM,
    skill: str,
    difficulty: str,
    question_count: int,
    learner_context: str = "",
) -> list[dict[str, Any]]:
    """Generate and validate JSON-ready questions using local Qwen."""
    if difficulty not in DIFFICULTIES:
        raise ExerciseError("Độ khó bài tập không hợp lệ.")
    if question_count not in QUESTION_COUNTS:
        raise ExerciseError("Số lượng câu hỏi không hợp lệ.")

    prompt = (
        f"Create exactly {question_count} questions.\n"
        f"Target skill: {skill}\n"
        f"Difficulty: {difficulty}\n"
        "Make the set varied, practical, and concise."
    )
    payload = llm.chat_structured(
        EXERCISE_SYSTEM_PROMPT,
        prompt,
        exercise_schema(question_count),
        learner_context,
    )
    raw_questions = payload.get("questions")
    if not isinstance(raw_questions, list) or len(raw_questions) != question_count:
        raise ExerciseError(
            "Local AI chưa tạo đủ số câu hỏi. Hãy nhấn tạo bài lại."
        )

    questions: list[dict[str, Any]] = []
    for position, raw_question in enumerate(raw_questions, start=1):
        try:
            questions.append(_validate_question(raw_question, position, skill, difficulty))
        except ExerciseError:
            # Small models occasionally emit a malformed choice set; keep the
            # valid remainder instead of failing the whole exercise.
            continue
    if not questions:
        raise ExerciseError(
            "Local AI chưa tạo được câu hỏi hợp lệ nào. Hãy nhấn tạo bài lại."
        )
    questions = [
        {**question, "position": index}
        for index, question in enumerate(questions, start=1)
    ]
    return questions


def _validate_question(
    raw_question: Any,
    position: int,
    skill: str,
    difficulty: str,
) -> dict[str, Any]:
    if not isinstance(raw_question, dict):
        raise ExerciseError("Local AI tạo một câu hỏi không hợp lệ.")

    question_type = str(raw_question.get("question_type", ""))
    prompt = str(raw_question.get("prompt", "")).strip()
    correct_answer = str(raw_question.get("correct_answer", "")).strip()
    explanation = str(raw_question.get("explanation_vi", "")).strip()
    options_value = raw_question.get("options", [])
    accepted_value = raw_question.get("accepted_answers", [])

    if question_type not in QUESTION_TYPES or not prompt or not correct_answer:
        raise ExerciseError("Local AI tạo nội dung câu hỏi chưa đầy đủ.")
    options = [str(option).strip() for option in options_value if str(option).strip()]
    accepted_answers = [str(answer).strip() for answer in accepted_value if str(answer).strip()]
    if question_type == "multiple_choice" and len(options) != 4:
        raise ExerciseError("Câu trắc nghiệm chưa có đúng bốn lựa chọn.")
    if question_type == "multiple_choice":
        prompt = _strip_inline_choices(prompt)
        options = [_strip_choice_prefix(option) for option in options]
        correct_answer = _resolve_choice_answer(correct_answer, options)
        accepted_answers = [
            _resolve_choice_answer(answer, options) for answer in accepted_answers
        ]
    else:
        options = []
    if correct_answer not in accepted_answers:
        accepted_answers.append(correct_answer)

    return {
        "position": position,
        "skill": skill,
        "difficulty": difficulty,
        "question_type": question_type,
        "prompt": prompt,
        "options": options,
        "correct_answer": correct_answer,
        "accepted_answers": accepted_answers,
        "explanation_vi": explanation or "Hãy xem lại đáp án đúng và thử lần nữa.",
    }


def _strip_choice_prefix(value: str) -> str:
    """Remove labels Qwen sometimes adds even when the schema says not to."""
    return re.sub(
        r"^\s*[A-D]\s*[\)\.\:\-]\s*",
        "",
        value,
        count=1,
        flags=re.IGNORECASE,
    ).strip()


def _resolve_choice_answer(value: str, options: list[str]) -> str:
    """Convert either a letter or a prefixed option into clean answer text."""
    clean_value = value.strip()
    if re.fullmatch(r"[A-D]", clean_value, flags=re.IGNORECASE):
        return options[ord(clean_value.upper()) - ord("A")]
    return _strip_choice_prefix(clean_value)


def _strip_inline_choices(prompt: str) -> str:
    """Remove a full A/B/C/D block accidentally embedded in the question stem."""
    markers: list[re.Match[str]] = []
    for letter in "ABCD":
        marker = re.search(
            rf"(?<![A-Za-z0-9]){letter}\s*[\)\.\:\-]\s+",
            prompt,
            flags=re.IGNORECASE,
        )
        if marker is None:
            return prompt.strip()
        markers.append(marker)
    positions = [marker.start() for marker in markers]
    if positions != sorted(positions) or len(set(positions)) != 4:
        return prompt.strip()
    cleaned_prompt = prompt[: positions[0]].rstrip(" \n\t:-")
    return cleaned_prompt or prompt.strip()


def format_question(question: dict[str, Any], total_questions: int) -> str:
    """Render one portable question as Markdown for the current Gradio UI."""
    type_labels = {
        "multiple_choice": "Multiple choice",
        "fill_blank": "Fill in the blank",
        "sentence_correction": "Correct the sentence",
        "translation": "Translate",
        "guided_sentence": "Write a sentence",
    }
    position = int(question["position"])
    lines = [
        f"### Câu {position}/{total_questions} — {question['skill']}",
        f"*{type_labels.get(question['question_type'], question['question_type'])}*",
        "",
        str(question["prompt"]),
    ]
    options = question.get("options", [])
    for index, option in enumerate(options):
        lines.append(f"{chr(65 + index)}. {option}")
    lines.append("\nNhập đáp án của bạn bên dưới.")
    return "\n".join(lines)


def format_question_card(
    question: dict[str, Any],
    total_questions: int,
    is_flagged: bool = False,
) -> str:
    """Render only the prompt; v0.6 answer controls are native UI elements."""
    type_labels = {
        "multiple_choice": "Chọn một đáp án",
        "fill_blank": "Điền vào chỗ trống",
        "sentence_correction": "Sửa câu",
        "translation": "Dịch câu",
        "guided_sentence": "Viết câu theo yêu cầu",
    }
    flag = " 🚩" if is_flagged else ""
    return (
        f"## Câu {int(question['position'])} / {total_questions}{flag}\n\n"
        f"**{question['skill']} · {question['difficulty']} · "
        f"{type_labels.get(question['question_type'], question['question_type'])}**"
        f"\n\n### {question['prompt']}"
    )


def check_answer(question: dict[str, Any], user_answer: str) -> bool:
    """Grade locally using normalized accepted answers; no extra model call."""
    normalized_user = _normalize_answer(user_answer)
    candidates = {
        _normalize_answer(answer) for answer in question.get("accepted_answers", [])
    }
    candidates.add(_normalize_answer(str(question.get("correct_answer", ""))))

    options = question.get("options", [])
    answer_letter = user_answer.strip().upper()
    if len(answer_letter) == 1 and "A" <= answer_letter <= "D" and options:
        option_index = ord(answer_letter) - ord("A")
        if option_index < len(options):
            normalized_user = _normalize_answer(str(options[option_index]))
    return bool(normalized_user) and normalized_user in candidates


def _normalize_answer(answer: str) -> str:
    lowered = answer.casefold().strip()
    without_punctuation = re.sub(r"[^\w\s']", "", lowered, flags=re.UNICODE)
    return " ".join(without_punctuation.split())
