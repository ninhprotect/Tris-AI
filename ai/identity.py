"""Product facts are application metadata, not facts for a small LLM to guess."""
import re
import unicodedata

CREATOR_VI = 'Tris AI được tạo ra và phát triển bởi Nguyễn Hải Hà Ninh, sinh viên ngành Công nghệ thông tin tại Đại học Thủ Dầu Một.'
CREATOR_EN = 'Tris AI was created and developed by Nguyễn Hải Hà Ninh, an Information Technology student at Thu Dau Mot University (Đại học Thủ Dầu Một).'
PURPOSE_VI = ('Mục đích của Tris là giúp bạn học tiếng Anh chủ động: luyện hội thoại, '
              'ngữ pháp, từ vựng, làm bài tập và ôn lại lỗi sai. Tris còn hỗ trợ hỏi đáp '
              'tài liệu, đọc nội dung ảnh và tạo ảnh trong chat khi các công cụ local sẵn sàng.')
PURPOSE_EN = ('Tris was built to help you learn English independently through conversation, '
              'grammar, vocabulary, exercises and reviewing mistakes. Tris also supports '
              'document questions, image reading and image creation when its local tools are ready.')


def normalized(value):
    return ''.join(c for c in unicodedata.normalize('NFD',value.lower().replace('đ','d')) if unicodedata.category(c)!='Mn')


def is_translation_request(message: str) -> bool:
    text = ' '.join(normalized(message).split())
    return bool(re.match(r'^(?:(?:please|can you|could you|help me|ban|hay|giup toi|giup minh)\s+)*(?:translate|dich)\b', text))


def identity_answer(message, language='vi'):
    text = ' '.join(normalized(message).split())
    # "mục đích" means purpose, not the translation command "dịch".
    command_text = re.sub(r'\bmuc dich\b', 'purpose', text)
    if re.search(r'\b(translate|translation|dich|sua ngu phap|correct this sentence)\b', command_text):
        return None
    creator = bool(re.search(r'(ai|nguoi nao).{0,25}(tao ra|phat trien|lap trinh).{0,20}(ban|tris|model(?: ai)? nay|mo hinh(?: ai)? nay)|who.{0,20}(created|built|developed|made).{0,15}(you|tris)|your (creator|developer)|nguoi (tao ra|phat trien).{0,15}(ban|tris)',text))
    creator |= bool('ninh' in text and re.search(r'tao ra|phat trien|created|creator|developed|built',text))
    intro = bool(re.search(
        r'^(?:xin chao[,! ]*|hi[,! ]*|hello[,! ]*)?(?:ban la ai|tris la ai|'
        r'(?:(?:hay|ban|cau|tris) )?gioi thieu (?:ve )?(?:ban than|ban|tris)|'
        r'who are you|what is tris(?: ai)?|(?:please )?introduce yourself|tell me about yourself)'
        r'(?:\b|[?.!])', text.strip()))
    base = bool(re.search(r'(model|mo hinh).{0,20}(nen|goc|base|underlying)|underlying model|base model|are you (qwen|alibaba)',text))
    purpose = bool(re.search(
        r'\bmuc dich(?: hoat dong| ton tai)? (?:cua )?(ban|tris|ai nay|model nay)\b|'
        r'\b(ban|tris) (?:co )?(muc dich|giup duoc gi)\b|'
        r'\b(ban|tris) (?:duoc |da duoc )?(tao ra|phat trien|xay dung).{0,20}(de lam gi|muc dich)|'
        r'\btao ra (ban|tris).{0,20}(muc dich|de lam gi)|'
        r'\b(vi sao|tai sao).{0,25}(tao ra ban|ban duoc tao)|'
        r'(your purpose|what can you do|why were you (created|built)|what were you (created|built) for)', text))
    # A mixed request needs the LLM to cover its non-identity question too.
    if re.search(r'(?:[?;]|\bva\b|\band\b)\s*(?:(?:giup minh|giup toi|ban|hay|please|help me)\s+)*(?:giai thich|tinh|calculate|explain|write code|viet ham|sua cau|chinh sua|correct)\b', text):
        return None
    if not creator and not base and not intro and not purpose:
        return None
    answer = CREATOR_EN if language=='en' else CREATOR_VI
    if intro:
        answer = ("Hi! I'm Tris, your AI English tutor. " if language == 'en'
                  else 'Xin chào! Mình là Tris, trợ lý AI giúp bạn học tiếng Anh. ') + answer
    if purpose:
        answer += '\n\n' + (PURPOSE_EN if language == 'en' else PURPOSE_VI)
    if base:
        answer += (' The underlying pretrained model is Qwen, run locally through Ollama. Building Tris AI is distinct from pretraining its base model.' if language=='en' else ' Model nền được huấn luyện sẵn là Qwen, chạy local qua Ollama. Việc xây dựng Tris AI khác với việc huấn luyện model nền từ đầu.')
    return answer
