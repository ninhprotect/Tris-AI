import unittest
from ai.identity import identity_answer, is_translation_request
from services.chat_tools import media_intent


class ChatToolsTests(unittest.TestCase):
    def test_creator_queries_are_reliable(self):
        for text in ['Ai tạo ra bạn?', 'Who created you?', 'Nguyễn Hải Hà Ninh is the one who created me', 'Người phát triển Tris là ai?']:
            self.assertIn('Nguyễn Hải Hà Ninh',identity_answer(text))
            self.assertIn('Đại học Thủ Dầu Một',identity_answer(text))

    def test_does_not_claim_to_pretrain_base_model(self):
        result=identity_answer('Model nền của bạn là gì?')
        self.assertIn('Qwen',result)
        self.assertIn('khác với',result)

    def test_does_not_hijack_translation_or_ordinary_chat(self):
        self.assertIsNone(identity_answer('Dịch câu: Who created you?'))
        self.assertIsNone(identity_answer('How can I practice English?'))

    def test_introduction_has_creator_without_unsolicited_base_attribution(self):
        for text in ['Bạn là ai?', 'Giới thiệu về bản thân nhé', 'Who are you?', 'Please introduce yourself.']:
            answer = identity_answer(text)
            self.assertIn('Nguyễn Hải Hà Ninh', answer)
            self.assertNotIn('Alibaba', answer)
            self.assertNotIn('Qwen', answer)
        self.assertIn('created and developed', identity_answer('Introduce yourself', 'en'))
        self.assertIsNone(identity_answer('Hãy giới thiệu về mô hình dữ liệu quan hệ'))

    def test_conservative_media_intent(self):
        for text in ['Tạo ảnh một con mèo','Vẽ hình một ngôi nhà','Create an image of a cat','Please generate a picture of a fox']:
            self.assertEqual(media_intent(text),'image')
        self.assertEqual(media_intent('a cat','gif'),'gif')
        self.assertIsNone(media_intent('Cách tạo ảnh bằng AI?'))
        self.assertIsNone(media_intent('Do not create an image'))
        self.assertIsNone(media_intent('Translate: create an image'))
        self.assertIsNone(media_intent('Tạo ảnh một con mèo','chat'))

    def test_purpose_is_not_translation(self):
        for message in ['xin chào bạn là ai\n\nngười tạo ra bạn cho mục đích gì',
                        'Mục đích của Tris là gì?', 'Bạn được tạo ra để làm gì?']:
            answer=identity_answer(message)
            self.assertIn('Nguyễn Hải Hà Ninh',answer)
            self.assertIn('Mục đích',answer)
            self.assertIn('học tiếng Anh',answer)
        self.assertIn('built to help',identity_answer('Who are you and why were you created?', 'en'))
        self.assertIsNone(identity_answer('Dịch câu: Mục đích của bạn là gì?'))
        self.assertIsNone(identity_answer('Ai tạo ra bạn? Và giải thích phép chia phân số.'))

    def test_translation_task_detection_is_not_triggered_by_purpose(self):
        for message in ['Translate into English: Ai tạo ra bạn?', 'Bạn hãy dịch: mục đích', 'Please translate this.']:
            self.assertTrue(is_translation_request(message))
        for message in ['Mục đích của bạn là gì?', 'What is machine translation?', 'Ai tạo ra bạn?']:
            self.assertFalse(is_translation_request(message))

    def test_polite_purpose_questions_and_mixed_tasks_are_not_hijacked(self):
        for message in ['Bạn giải thích mục đích của SQL được không?',
                        'Bạn có biết mục đích của việc học từ vựng là gì không?',
                        'Xin chào bạn là ai? Giúp mình sửa câu She go to school.']:
            self.assertIsNone(identity_answer(message),message)


if __name__=='__main__': unittest.main()
