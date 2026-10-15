"""Transparent rule-based skill analysis for Tris AI v0.3."""

from database import SkillInsight

GRAMMAR_SKILL_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Past Simple",
        (
            "past simple",
            "simple past",
            "quá khứ đơn",
            "yesterday",
            "last week",
            "last night",
            "ago",
        ),
    ),
    (
        "Present Perfect",
        ("present perfect", "hiện tại hoàn thành", "have been", "has been"),
    ),
    (
        "Articles",
        ("article", "articles", "mạo từ", "a/an", "dùng 'a'", "dùng 'an'"),
    ),
    (
        "Subject–Verb Agreement",
        (
            "subject-verb",
            "subject–verb",
            "chủ ngữ",
            "chia động từ",
            "third-person singular",
            "ngôi thứ ba số ít",
        ),
    ),
    (
        "Plurals & Countable Nouns",
        (
            "plural",
            "số nhiều",
            "countable",
            "uncountable",
            "danh từ đếm được",
            "danh từ không đếm được",
        ),
    ),
    (
        "Prepositions",
        ("preposition", "prepositions", "giới từ"),
    ),
    (
        "Word Order",
        ("word order", "trật tự từ", "thứ tự từ"),
    ),
    (
        "Present Simple",
        ("present simple", "hiện tại đơn", "every day", "usually", "always"),
    ),
    (
        "Verb Forms",
        ("verb form", "gerund", "infinitive", "v-ing", "động từ nguyên mẫu"),
    ),
)


def classify_grammar_skill(user_message: str, tutor_feedback: str) -> str:
    """Classify one correction using readable keywords in text and feedback."""
    evidence = f"{user_message} {tutor_feedback}".casefold()
    for skill_name, keywords in GRAMMAR_SKILL_RULES:
        if any(keyword in evidence for keyword in keywords):
            return skill_name
    return "General Grammar"


def build_learner_context(insights: list[SkillInsight]) -> str:
    """Turn SQLite evidence into a short, non-authoritative model memory."""
    meaningful = [
        insight
        for insight in insights
        if insight.attempt_count >= 3 or insight.error_count > 0
    ]
    if not meaningful:
        return ""

    lines = [
        "Local learner memory (use subtly; do not mention statistics unless asked):"
    ]
    for insight in meaningful[:6]:
        lines.append(
            f"- {insight.skill_name}: {insight.level}; "
            f"{insight.correct_count} successful and {insight.error_count} corrected attempts."
        )
    lines.append(
        "Give a little more practice to weak skills while keeping the current conversation natural."
    )
    return "\n".join(lines)
