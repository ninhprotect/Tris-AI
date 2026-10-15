"""Learning records shared with the existing Gradio tutor behavior."""
import re
from services import skill_analysis


def save_learning_records(database, user_id, mode, scenario, message, answer):
    database.save_exchange(user_id, mode, scenario if mode == "Role Play" else "", message, answer)
    correction = any(marker in answer.casefold() for marker in
                     ("correction:", "❌", "→", "small correction", "một chỉnh sửa", "sai vì"))
    if mode == "Vocabulary":
        word = message.strip()
        if len(word) <= 60 and 1 <= len(word.split()) <= 3 and re.fullmatch(r"[A-Za-zÀ-ỹ' -]+", word):
            database.save_vocabulary(user_id, word, answer)
        else:
            database.record_skill_attempt(user_id, "Vocabulary Usage", is_error=correction)
    if mode == "Grammar":
        database.record_skill_attempt(user_id, skill_analysis.classify_grammar_skill(message, answer), is_error=correction)
    if mode in {"Conversation", "Grammar", "Role Play"} and correction:
        database.save_grammar_mistake(user_id, mode, message, answer)
        if mode != "Grammar":
            database.record_skill_attempt(user_id, skill_analysis.classify_grammar_skill(message, answer), is_error=True)
