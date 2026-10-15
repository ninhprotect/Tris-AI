"""No GPU/network required: image prompt translation and fidelity boundaries."""
import json
import unittest
from unittest.mock import Mock

import httpx

from services.image_prompt import ImagePromptError, prepare_image_prompt


def client_reply(prompt):
    response = Mock()
    response.json.return_value = {"message": {"content": json.dumps({"prompt": prompt})}}
    client = Mock()
    client.post.return_value = response
    return client


class ImagePromptTests(unittest.TestCase):
    def test_user_regression_orange_cat(self):
        client = client_reply("An orange cat")
        result = prepare_image_prompt("tạo ảnh mèo cam", client)
        self.assertEqual(result.prompt, "An orange cat")
        self.assertTrue(result.translated)
        payload = client.post.call_args.kwargs["json"]
        self.assertEqual(payload["messages"][-1]["content"], "mèo cam")
        self.assertEqual(payload["options"]["temperature"], 0)

    def test_english_preserves_entities_negation_and_style_without_network(self):
        client = Mock()
        result = prepare_image_prompt("Please draw an image of two black cats on a red chair, no people, watercolor", client)
        self.assertEqual(result.prompt, "two black cats on a red chair, no people, watercolor")
        self.assertFalse(result.translated)
        client.post.assert_not_called()

    def test_vietnamese_constraints_not_dropped(self):
        expected = "Two black cats on a red chair, no people, watercolor painting"
        result = prepare_image_prompt("Vẽ ảnh hai con mèo đen trên ghế đỏ, không có người, tranh màu nước", client_reply(expected))
        self.assertEqual(result.prompt, expected)

    def test_unaccented_vietnamese_command_uses_local_translation(self):
        result = prepare_image_prompt("tao anh meo cam", client_reply("An orange cat"))
        self.assertTrue(result.translated)
        self.assertEqual(result.prompt, "An orange cat")

    def test_hallucinated_street_is_not_silently_sent_to_diffusion(self):
        with self.assertRaises(ImagePromptError):
            prepare_image_prompt("tạo ảnh mèo cam", client_reply("A street in a city"))

    def test_wrong_color_is_rejected(self):
        with self.assertRaises(ImagePromptError):
            prepare_image_prompt("tạo ảnh mèo cam", client_reply("A black cat"))

    def test_negation_is_not_silently_removed(self):
        with self.assertRaises(ImagePromptError):
            prepare_image_prompt("tạo ảnh mèo cam, không có người", client_reply("An orange cat"))

    def test_connection_failure_does_not_fall_back_to_raw_vietnamese(self):
        client = Mock()
        client.post.side_effect = httpx.ConnectError("refused")
        with self.assertRaisesRegex(ImagePromptError, "chưa tạo ảnh"):
            prepare_image_prompt("tạo ảnh mèo cam", client)

    def test_invalid_json_and_empty_translation_fail_explicitly(self):
        for output in ["", None, 123]:
            with self.subTest(output=output), self.assertRaises(ImagePromptError):
                prepare_image_prompt("tạo ảnh mèo cam", client_reply(output))
        client = client_reply("x")
        client.post.return_value.json.return_value = {"message": {"content": "not json"}}
        with self.assertRaises(ImagePromptError):
            prepare_image_prompt("tạo ảnh mèo cam", client)

    def test_bare_command_needs_a_subject(self):
        with self.assertRaises(ImagePromptError):
            prepare_image_prompt("tạo ảnh", Mock())

    def test_preserves_requested_vietnamese_text(self):
        expected = 'An orange cat beside a sign reading "Xin chào"'
        result = prepare_image_prompt('Tạo ảnh mèo cam cạnh biển ghi "Xin chào"', client_reply(expected))
        self.assertEqual(result.prompt, expected)

    def test_quoted_lettering_is_not_an_added_subject(self):
        expected = 'A wooden sign reading "mèo cam"'
        result = prepare_image_prompt('Tạo ảnh biển gỗ ghi "mèo cam"', client_reply(expected))
        self.assertEqual(result.prompt, expected)

    def test_changed_lettering_is_rejected(self):
        with self.assertRaises(ImagePromptError):
            prepare_image_prompt('Tạo ảnh biển gỗ ghi "Xin chào"', client_reply('A wooden sign reading "Hello"'))

    def test_untranslated_vietnamese_is_rejected(self):
        with self.assertRaises(ImagePromptError):
            prepare_image_prompt("tạo ảnh một con ngựa màu hồng", client_reply("Một con ngựa màu hồng"))


if __name__ == "__main__":
    unittest.main()
