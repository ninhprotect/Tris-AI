"""Isolated API contract tests. No real accounts, models, or document library touched."""
import json
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, Mock, patch
from services.image_gen import ImageGenError
from services.local_stt import LocalSTTError, TranscriptionResult

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import workspace_api


class FakeStream:
    status_code = 200
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    def raise_for_status(self): pass
    async def aiter_lines(self):
        for event in [{"message": {"content": "Hello "}}, {"message": {"content": "learner!"}}, {"done": True}]:
            yield json.dumps(event)


class FakeOllama:
    payload = None
    def __init__(self, **kwargs): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    def stream(self, method, url, json):
        type(self).payload = json
        return FakeStream()


class FakeCompareOllama:
    """Sequential fake: answer A, answer B, then the judge pass on model A."""
    calls = 0
    def __init__(self, **kwargs): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    def stream(self, method, url, json):
        type(self).calls += 1
        index = type(self).calls
        return FakeCompareStream(json, index)


class FakeCompareStream:
    status_code = 200
    def __init__(self, payload, index): self.payload = payload
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    def raise_for_status(self): pass
    async def aiter_lines(self):
        model = self.payload['model']
        if 'trọng tài đối chiếu' in self.payload['messages'][0]['content']:
            chunks = ['Hai bên cùng nói mèo. ', 'Không thấy mâu thuẫn.']
        elif model.endswith(':4b') or '4b' in model:
            chunks = ['Mèo ', 'là động vật.']
        else:
            chunks = ['Con mèo ', 'thuộc họ mèo.']
        for chunk in chunks:
            yield json.dumps({'message': {'content': chunk}})
        yield json.dumps({'done': True})


class FakeReviewOllama:
    """Draft pass, then the self-review pass; the review reply is set per test."""
    payloads = []
    review_reply = "OK"
    def __init__(self, **kwargs): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    def stream(self, method, url, json):
        type(self).payloads.append(json)
        reviewing = "quality checker for Tris" in json["messages"][0]["content"]
        return FakeChunks([type(self).review_reply] if reviewing else ["The past tense of go ", "is goed."])


class FakeChunks:
    status_code = 200
    def __init__(self, chunks): self.chunks = chunks
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    def raise_for_status(self): pass
    async def aiter_lines(self):
        for chunk in self.chunks:
            yield json.dumps({"message": {"content": chunk}})
        yield json.dumps({"done": True})


class WorkspaceAPITests(unittest.TestCase):
    def setUp(self):
        self.account = SimpleNamespace(account_id="private-id", learner_name="Test Learner", username="test")
        def require_access(token, authorization):
            if authorization != "Bearer test-session": raise HTTPException(401, "Login required")
        self.backend = SimpleNamespace(
            app=FastAPI(), require_access=require_access,
            bearer_account=lambda authorization: self.account if authorization == "Bearer test-session" else None,
            social_login_codes=SimpleNamespace(consume=Mock(return_value=None)),
            user_id_for=Mock(return_value=42),
            learner_context_for=Mock(return_value=([], "Explain in Vietnamese.")),
            database=SimpleNamespace(save_exchange=Mock()),
            study_hub=SimpleNamespace(ingest=Mock(return_value={"document_id": 5}), store_media_attachment=Mock(),
                                     index=SimpleNamespace(search=Mock(return_value=[]))),
            web_search_service=SimpleNamespace(gather=Mock()),
            imagegen_service=SimpleNamespace(generate=Mock(return_value=Path('tris_image_fixture.png'))),
            speech_to_text=SimpleNamespace(
                status=Mock(return_value={"ready": True, "model_loaded": True}),
                transcribe=Mock(
                    return_value=TranscriptionResult(
                        text="Xin chào Tris",
                        language="vi",
                        audio_seconds=1.25,
                        processing_seconds=0.2,
                        model="base",
                        device="cpu",
                    )
                ),
            ),
        )
        workspace_api.install_workspace_routes(self.backend)
        self.client = TestClient(self.backend.app)
        self.auth = {"Authorization": "Bearer test-session"}
        self.models = patch.object(workspace_api, "installed_models", AsyncMock(return_value=[{"name": "test:4b", "size": 123}]))
        self.models_mock = self.models.start()
        self.addCleanup(self.models.stop)
        self.addCleanup(self.client.close)
        # Most tests check the single-pass chat contract; self-review has its own tests below.
        self.review_flag = patch.object(workspace_api, "CHAT_SELF_REVIEW", False)
        self.review_flag.start()
        self.addCleanup(self.review_flag.stop)

    def test_models_contract(self):
        result = self.client.get("/v1/workspace/models").json()
        self.assertEqual(result["default"], "test:4b")
        self.assertEqual(len(result["models"]), 1)

    def run_reviewed_chat(self, review_reply):
        FakeReviewOllama.payloads, FakeReviewOllama.review_reply = [], review_reply
        with patch.object(workspace_api, "CHAT_SELF_REVIEW", True), \
             patch.object(workspace_api.httpx, "AsyncClient", FakeReviewOllama):
            response = self.client.post("/v1/workspace/chat", headers=self.auth,
                                        json={"message": "Past tense of go?", "model": ""})
        events = [json.loads(row) for row in response.text.splitlines()]
        return "".join(e.get("delta", "") for e in events), events

    def test_self_review_replaces_a_wrong_draft_before_anything_is_shown(self):
        answer, events = self.run_reviewed_chat("The past tense of go is went.")
        self.assertEqual(answer, "The past tense of go is went.")
        self.assertNotIn("goed", answer)  # the wrong draft never reaches the learner
        self.assertEqual(len(FakeReviewOllama.payloads), 2)
        review_user = FakeReviewOllama.payloads[1]["messages"][1]["content"]
        self.assertIn("Past tense of go?", review_user)
        self.assertIn("is goed.", review_user)
        self.assertTrue(events[-1].get("done"))
        saved = self.backend.database.save_exchange.call_args.args
        self.assertEqual(saved[-1], "The past tense of go is went.")

    def test_self_review_ok_keeps_the_draft(self):
        answer, events = self.run_reviewed_chat("OK")
        self.assertEqual(answer, "The past tense of go is goed.")
        self.assertTrue(any("rà lại" in e.get("status", "") for e in events))

    def test_picker_offers_only_the_tris_tutor_model(self):
        installed = [{"name": n, "size": 1} for n in
                     ("english-tutor-local:4b", "qwen3:4b-instruct", "qwen3:4b", "english-tutor-local:8b", "qwen3:8b")]
        with patch.object(workspace_api, "VISIBLE_CHAT_MODELS", ("english-tutor-local:4b",)):
            self.assertEqual([m["name"] for m in workspace_api.visible_chat_models(installed)], ["english-tutor-local:4b"])
            # If the tutor model is missing, keep every chat model so Tris still answers.
            self.assertEqual(workspace_api.visible_chat_models(installed[1:]), installed[1:])

    def test_media_uses_existing_generator_and_persists_chat(self):
        result=self.client.post('/v1/workspace/chat',headers=self.auth,json={'message':'Tạo ảnh con mèo'})
        events=[json.loads(row) for row in result.text.splitlines()]
        self.backend.imagegen_service.generate.assert_called_once_with(
            'Tạo ảnh con mèo','image',6, on_event=ANY)
        self.assertIn('/v1/media/tris_image_fixture.png',events[-2]['delta'])
        self.assertTrue(events[-1]['done'])
        self.backend.database.save_exchange.assert_called_once()

    def test_media_confirms_context_and_streams_real_progress_only(self):
        seen = {}
        def generate(message, mode, frames, on_event=None):
            seen['on_event'] = on_event
            for event in [{'stage':'prepared','prompt':'An orange cat','translated':True},
                          {'stage':'engine_load'},
                          {'stage':'step','step':1,'total':4},
                          {'stage':'frame','frame':2,'total':6},
                          {'garbage': True}]:
                on_event(event)
            return Path('tris_image_fixture.png')
        self.backend.imagegen_service.generate.side_effect = generate
        result=self.client.post('/v1/workspace/chat',headers=self.auth,
                                json={'message':'Tạo ảnh mèo cam','action':'image'})
        events=[json.loads(row) for row in result.text.splitlines()]
        statuses=[event['status'] for event in events if 'status' in event]
        self.assertTrue(any('sd-turbo' in text and 'tạo ảnh' in text for text in statuses[:1]),
                        statuses)
        self.assertTrue(any('An orange cat' in text for text in statuses))
        self.assertTrue(any('GPU' in text for text in statuses))
        self.assertTrue(any('bước 1/4' in text for text in statuses))
        self.assertTrue(any('khung 2/6' in text for text in statuses))
        # Only truthful counts are forwarded; unknown stages are dropped.
        self.assertFalse(any('garbage' in text for text in statuses))
        self.assertIn('/v1/media/tris_image_fixture.png',events[-2]['delta'])

    def test_compare_runs_two_models_then_judge_and_persists(self):
        FakeCompareOllama.calls = 0
        self.models_mock.return_value = [{"name": "test:4b", "size": 123}, {"name": "test:8b", "size": 456}]
        with patch.object(workspace_api.httpx, 'AsyncClient', FakeCompareOllama):
            result = self.client.post('/v1/workspace/compare', headers=self.auth, json={
                'message': 'Con mèo là gì?', 'model_a': 'test:4b', 'model_b': 'test:8b', 'language': 'vi'})
        self.assertEqual(result.status_code, 200)
        events = [json.loads(line) for line in result.text.splitlines()]
        a_deltas = ''.join(e['delta'] for e in events if e.get('which') == 'a' and e.get('delta'))
        b_deltas = ''.join(e['delta'] for e in events if e.get('which') == 'b' and e.get('delta'))
        judge = ''.join(e['judge'] for e in events if 'judge' in e)
        self.assertEqual(a_deltas, 'Mèo là động vật.')
        self.assertEqual(b_deltas, 'Con mèo thuộc họ mèo.')
        self.assertIn('cùng nói mèo', judge)
        self.assertTrue(any(e.get('which') == 'a' and e.get('done') for e in events))
        self.assertTrue(any(e.get('which') == 'b' and e.get('done') for e in events))
        self.assertTrue(events[-1]['done'])
        self.assertEqual(events[-1]['model_a'], 'test:4b')
        self.assertEqual(events[-1]['model_b'], 'test:8b')
        saved = self.backend.database.save_exchange.call_args[0][4]
        self.assertIn('### test:4b', saved)
        self.assertIn('### test:8b', saved)
        self.assertIn('Kết luận đối chiếu', saved)

    def test_compare_rejects_same_model_and_whitespace(self):
        response = self.client.post('/v1/workspace/compare', headers=self.auth,
                                    json={'message': 'Hi', 'model_a': 'test:4b', 'model_b': 'test:4b'})
        self.assertEqual(response.status_code, 422)
        response = self.client.post('/v1/workspace/compare', headers=self.auth,
                                    json={'message': '   ', 'model_a': 'test:4b', 'model_b': 'test:8b'})
        self.assertEqual(response.status_code, 422)

    def test_compare_unauthorized_rejected(self):
        response = self.client.post('/v1/workspace/compare',
                                    json={'message': 'Hi', 'model_a': 'a', 'model_b': 'b'})
        self.assertEqual(response.status_code, 401)

    def test_follow_up_queues_while_another_request_holds_the_gpu(self):
        import threading
        lock = self.backend.app.state.inference_lock
        with patch.object(workspace_api.httpx, "AsyncClient", FakeOllama):
            with self.client as client:
                # Occupy the GPU slot exactly like a running task would.
                client.portal.call(lock.acquire)
                result = {}
                sender = threading.Thread(target=lambda: result.update(
                    response=client.post('/v1/workspace/chat', headers=self.auth,
                                         json={'message':'Tin nhắn bổ sung','model':'test:4b','follow_up':True})))
                sender.start()
                try:
                    queued = False
                    deadline = time.time() + 10
                    while time.time() < deadline:
                        waiters = client.portal.call(
                            lambda: len(getattr(lock, '_waiters', ()) or ()))
                        if waiters:
                            queued = True
                            break
                        time.sleep(0.02)
                    self.assertTrue(queued, 'follow-up request never reached the lock queue')
                    probe = client.post('/v1/workspace/chat', headers=self.auth,
                                        json={'message':'probe','model':'test:4b'})
                    self.assertEqual(probe.status_code, 429)
                finally:
                    client.portal.call(lock.release)
                    sender.join(30)
        response = result.get('response')
        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, 200)
        events=[json.loads(row) for row in response.text.splitlines()]
        self.assertTrue(events[0].get('status','').startswith('Đã xếp hàng'))
        self.assertEqual(''.join(event.get('delta','') for event in events), 'Hello learner!')

    def test_creator_reply_corrects_bad_history_without_model_guessing(self):
        result=self.client.post('/v1/workspace/chat',headers=self.auth,json={'message':'Who created you?','language':'en','history':[{'role':'assistant','content':'Ninh did not create me.'}]})
        events=[json.loads(row) for row in result.text.splitlines()]
        self.assertIn('Nguyễn Hải Hà Ninh',events[0]['delta'])
        self.assertNotIn('did not',events[0]['delta'])

    def test_image_error_is_actionable(self):
        self.backend.imagegen_service.generate.side_effect=ImageGenError('Model local unavailable')
        result=self.client.post('/v1/workspace/chat',headers=self.auth,json={'message':'a cat','action':'image'})
        self.assertIn('Model local unavailable',result.text)
        self.backend.database.save_exchange.assert_not_called()

    def test_introduction_ignores_old_false_attribution(self):
        with patch.object(workspace_api.httpx, 'AsyncClient') as llm:
            result=self.client.post('/v1/workspace/chat',headers=self.auth,json={
                'message':'Giới thiệu về bản thân nhé', 'language':'vi',
                'history':[{'role':'assistant','content':'I was made by another company, not Ninh.'}]})
        events=[json.loads(row) for row in result.text.splitlines()]
        self.assertIn('Nguyễn Hải Hà Ninh',events[0]['delta'])
        self.assertNotIn('Alibaba',events[0]['delta'])
        self.assertNotIn('Qwen',events[0]['delta'])
        llm.assert_not_called()

    def test_screenshot_identity_and_purpose_works_without_model_service(self):
        with patch.object(workspace_api.httpx,'AsyncClient') as llm:
            result=self.client.post('/v1/workspace/chat',headers=self.auth,json={
                'message':'xin chào bạn là ai\n\nngười tạo ra bạn cho mục đích gì',
                'language':'vi','web_search':True})
        events=[json.loads(row) for row in result.text.splitlines()]
        self.assertIn('Nguyễn Hải Hà Ninh',events[0]['delta'])
        self.assertIn('Mục đích',events[0]['delta'])
        self.assertTrue(events[-1]['done'])
        llm.assert_not_called()
        self.backend.web_search_service.gather.assert_not_called()

    def test_runtime_error_is_specific_and_not_saved_as_success(self):
        from services.chat_runtime import ChatRuntimeError
        async def failed(*args, **kwargs):
            yield {'delta':'Incomplete'}
            raise ChatRuntimeError('AI_MEMORY','Thiếu VRAM. Hãy dùng 4b.')
        with patch.object(workspace_api,'stream_local_chat',failed):
            result=self.client.post('/v1/workspace/chat',headers=self.auth,json={'message':'Tell me about rain','model':'test:4b'})
        events=[json.loads(row) for row in result.text.splitlines()]
        self.assertEqual(events[-1]['code'],'AI_MEMORY')
        self.assertFalse(any(e.get('done') for e in events))
        self.backend.database.save_exchange.assert_not_called()

    def test_translation_uses_translation_task_not_biography_prompt(self):
        with patch.object(workspace_api.httpx,'AsyncClient',FakeOllama):
            result=self.client.post('/v1/workspace/chat',headers=self.auth,json={
                'message':'Translate into English: Ai tạo ra bạn?', 'language':'vi','model':'test:4b'})
        self.assertEqual(result.status_code,200)
        system=FakeOllama.payload['messages'][0]['content']
        self.assertIn('careful translator',system)
        self.assertNotIn('Nguyễn Hải Hà Ninh',system)

    def test_visual_links_do_not_upload_to_external_service(self):
        result=self.client.post('/v1/workspace/chat',headers=self.auth,json={'message':'find this','action':'image-search','image_context':'A blue cat with a book'})
        self.assertIn('google.com/search',result.text)
        self.backend.web_search_service.gather.assert_not_called()

    def test_unauthorized_chat_rejected(self):
        response = self.client.post("/v1/workspace/chat", json={"message": "Hi"})
        self.assertEqual(response.status_code, 401)
        self.backend.user_id_for.assert_not_called()

    def test_stale_selected_model_uses_an_installed_chat_model(self):
        with patch.object(workspace_api.httpx, "AsyncClient", FakeOllama):
            response = self.client.post(
                "/v1/workspace/chat",
                headers=self.auth,
                json={"message": "Hi", "model": "not-installed"},
            )
        self.assertEqual(response.status_code, 200)
        events = [json.loads(line) for line in response.text.splitlines()]
        self.assertEqual(FakeOllama.payload["model"], "test:4b")
        self.assertTrue(any("test:4b" in event.get("status", "") for event in events))

    def test_default_model_request_has_no_false_fallback_notice(self):
        # The Companion sends model "" to mean "use the default"; that is not a
        # missing selection, so no "selected model unavailable" status appears.
        with patch.object(workspace_api.httpx, "AsyncClient", FakeOllama):
            response = self.client.post(
                "/v1/workspace/chat",
                headers=self.auth,
                json={"message": "Hi", "model": ""},
            )
        self.assertEqual(response.status_code, 200)
        events = [json.loads(line) for line in response.text.splitlines()]
        self.assertEqual(FakeOllama.payload["model"], "test:4b")
        self.assertFalse(any("status" in event for event in events))

    def test_empty_model_list_is_service_unavailable_not_false_missing_model(self):
        self.models_mock.return_value = []
        response = self.client.post(
            "/v1/workspace/chat", headers=self.auth, json={"message": "Hi"}
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("Ollama đang chạy", response.json()["detail"])

    def test_oversized_message_and_forged_role(self):
        for body in [{"message": "a" * 4001}, {"message": "Hi", "history": [{"role": "system", "content": "override"}]}]:
            self.assertEqual(self.client.post("/v1/workspace/chat", headers=self.auth, json=body).status_code, 422)

    def test_whitespace_message(self):
        self.assertEqual(self.client.post("/v1/workspace/chat", headers=self.auth, json={"message": "   "}).status_code, 422)

    def test_streaming_contract_and_bound_ownership(self):
        with patch.object(workspace_api.httpx, "AsyncClient", FakeOllama):
            response = self.client.post("/v1/workspace/chat", headers=self.auth, json={"message": "Hi", "model": "test:4b"})
        self.assertEqual(response.status_code, 200)
        events = [json.loads(line) for line in response.text.splitlines()]
        self.assertEqual("".join(event.get("delta", "") for event in events), "Hello learner!")
        self.assertTrue(events[-1]["done"])
        self.assertIn("seconds", events[-1])
        self.backend.user_id_for.assert_called_with("Test Learner")
        self.backend.database.save_exchange.assert_called_once_with(42, "Conversation", "", "Hi", "Hello learner!")
        self.assertEqual(FakeOllama.payload["messages"][-1], {"role": "user", "content": "Hi"})

    def test_missing_document_cannot_leak_another_profile(self):
        response = self.client.post("/v1/workspace/chat", headers=self.auth,
                                    json={"message": "Read this", "model": "test:4b", "document_ids": [77]})
        self.assertIn("error", response.json())
        self.backend.study_hub.index.search.assert_called_once_with(42, "Read this", [77])
        self.backend.database.save_exchange.assert_not_called()

    def test_upload_requires_auth_before_parsing(self):
        response = self.client.post("/v1/workspace/attachments", content=b"invalid multipart")
        self.assertEqual(response.status_code, 401)
        self.backend.study_hub.ingest.assert_not_called()

    def test_upload_request_size_guard(self):
        response = self.client.post("/v1/workspace/attachments", headers={**self.auth, "Content-Length": str(152 * 1024 * 1024)}, content=b"")
        self.assertEqual(response.status_code, 413)

    def test_microphone_transcription_is_authenticated_bounded_and_temporary(self):
        seen = []
        def transcribe(path, language):
            seen.append(Path(path))
            self.assertTrue(Path(path).is_file())
            self.assertEqual(Path(path).read_bytes(), b"local webm fixture")
            self.assertEqual(language, "vi")
            return TranscriptionResult("Xin chào Tris", "vi", 1.25, 0.2, "base", "cpu")
        self.backend.speech_to_text.transcribe.side_effect = transcribe
        response = self.client.post(
            "/v1/workspace/transcribe",
            headers=self.auth,
            data={"language": "vi"},
            files={"file": ("recording.webm", b"local webm fixture", "audio/webm")},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["text"], "Xin chào Tris")
        self.assertFalse(seen[0].exists())

    def test_microphone_transcription_rejects_unauthorized_and_oversized_requests(self):
        unauthorized = self.client.post(
            "/v1/workspace/transcribe",
            files={"file": ("recording.webm", b"audio", "audio/webm")},
        )
        self.assertEqual(unauthorized.status_code, 401)
        oversized = self.client.post(
            "/v1/workspace/transcribe",
            headers={**self.auth, "Content-Length": str(13 * 1024 * 1024)},
            content=b"",
        )
        self.assertEqual(oversized.status_code, 413)
        self.backend.speech_to_text.transcribe.assert_not_called()

    def test_microphone_transcription_reports_local_model_setup_error(self):
        self.backend.speech_to_text.transcribe.side_effect = LocalSTTError("STT chưa sẵn sàng", 503)
        response = self.client.post(
            "/v1/workspace/transcribe",
            headers=self.auth,
            files={"file": ("recording.webm", b"audio", "audio/webm")},
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "STT chưa sẵn sàng")

    def test_unsupported_upload_rejected(self):
        response = self.client.post("/v1/workspace/attachments", headers=self.auth, files={"file": ("unsafe.exe", b"hello")})
        self.assertEqual(response.status_code, 400)

    def test_document_ingestion_temp_copy_only(self):
        paths = []
        def ingest(user, path, title):
            paths.append(path)
            self.assertEqual(user, 42)
            self.assertEqual(Path(path).read_text(), "A sample document with safe text.")
            self.assertEqual(title, "lesson.txt")
            return {"document_id": 5}
        self.backend.study_hub.ingest.side_effect = ingest
        response = self.client.post("/v1/workspace/attachments", headers=self.auth,
                                    files={"file": ("lesson.txt", b"A sample document with safe text.")})
        self.assertEqual(response.json()["document_id"], 5)
        self.assertFalse(paths[0].exists(), "Only the generated temporary copy is removed")

    def test_oauth_bridge_one_time_contract(self):
        self.backend.social_login_codes.consume.side_effect = [("session", self.account), None]
        response = self.client.post("/v1/workspace/oauth/exchange", json={"code": "one-time-code"})
        self.assertEqual(response.json()["account"]["account_id"], "private-id")
        self.assertEqual(self.client.post("/v1/workspace/oauth/exchange", json={"code": "one-time-code"}).status_code, 401)


if __name__ == "__main__":
    unittest.main()
