import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from services.chat_runtime import (
    CONTEXT_TRIMMED_NOTE, ChatRuntimeError, accept_review, bounded_history, fit_context, review_messages,
    stream_local_chat,
)

RealClient = httpx.AsyncClient


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def collect(self, responses, disconnected=False):
        self.calls=[]
        def handle(request):
            self.calls.append(json.loads(request.content))
            reply=responses[len(self.calls)-1]
            if isinstance(reply, Exception): raise reply
            return reply
        def factory(**kwargs):
            return RealClient(transport=httpx.MockTransport(handle))
        payload={'model':'explicit-user-choice:4b','messages':[{'role':'user','content':'private prompt'}]}
        request=SimpleNamespace(is_disconnected=AsyncMock(return_value=disconnected))
        with patch('services.chat_runtime.httpx.AsyncClient',side_effect=factory), patch('services.chat_runtime.asyncio.sleep',new_callable=AsyncMock):
            return [e async for e in stream_local_chat(payload,request)]

    @staticmethod
    def answer():
        return httpx.Response(200,text='{"message":{"content":"Hello"}}\n{"done":true}\n')

    async def test_transient_retry_preserves_model_and_no_duplicate_answer(self):
        events=await self.collect([httpx.Response(503,json={'error':'temporarily unavailable'}),self.answer()])
        self.assertEqual(''.join(e.get('delta','') for e in events),'Hello')
        self.assertTrue(events[-1]['complete'])
        self.assertEqual(len(self.calls),2)
        self.assertEqual(self.calls[0],self.calls[1])
        self.assertEqual(self.calls[0]['model'],'explicit-user-choice:4b')

    async def test_failure_has_actionable_status_without_private_body(self):
        with self.assertLogs('services.chat_runtime',level='WARNING') as logs:
            with self.assertRaises(ChatRuntimeError) as caught:
                await self.collect([httpx.Response(400,json={'error':'private raw upstream data'})])
        self.assertEqual(caught.exception.code,'AI_REQUEST_REJECTED')
        self.assertIn('400',str(caught.exception))
        self.assertNotIn('private',str(caught.exception))
        self.assertNotIn('private',' '.join(logs.output))
        self.assertEqual(len(self.calls),1)

    async def test_oom_does_not_retry_expensive_same_model(self):
        with self.assertRaises(ChatRuntimeError) as caught:
            await self.collect([httpx.Response(500,json={'error':'CUDA out of memory'})])
        self.assertEqual(caught.exception.code,'AI_MEMORY')
        self.assertEqual(len(self.calls),1)

    async def test_maximum_one_retry(self):
        with self.assertRaises(ChatRuntimeError):
            await self.collect([httpx.Response(503),httpx.Response(503)])
        self.assertEqual(len(self.calls),2)

    async def test_partial_answer_is_never_replayed(self):
        reply=httpx.Response(200,text='{"message":{"content":"Partial"}}\n{"error":"runner unavailable"}\n')
        with self.assertRaises(ChatRuntimeError):
            await self.collect([reply])
        self.assertEqual(len(self.calls),1)

    async def test_no_false_done_for_empty_or_truncated_stream(self):
        for reply, code in [('{"done":true}\n','AI_EMPTY'), ('{"message":{"content":"Partial"}}\n','AI_INCOMPLETE'), ('[]\n','AI_BAD_RESPONSE')]:
            with self.subTest(code=code), self.assertRaises(ChatRuntimeError) as caught:
                await self.collect([httpx.Response(200,text=reply)])
            self.assertEqual(caught.exception.code,code)

    async def test_timeout_and_offline_are_distinct(self):
        for exc, code in [(httpx.ReadTimeout('test'),'AI_TIMEOUT'), (httpx.ConnectError('test'),'AI_OFFLINE')]:
            with self.subTest(code=code),self.assertRaises(ChatRuntimeError) as caught:
                await self.collect([exc, exc])
            self.assertEqual(caught.exception.code,code)
            self.assertEqual(len(self.calls), 2)

    async def test_connection_reset_before_first_token_retries_then_succeeds(self):
        events = await self.collect([httpx.ConnectError('runner restarted'), self.answer()])
        self.assertEqual(''.join(event.get('delta', '') for event in events), 'Hello')
        self.assertTrue(events[-1]['complete'])
        self.assertEqual(len(self.calls), 2)

    async def test_cancel_during_retry_does_not_send_second_request(self):
        events=await self.collect([httpx.Response(503)],disconnected=True)
        self.assertEqual(len(self.calls),1)
        self.assertFalse(any(e.get('complete') for e in events))


class ContextTests(unittest.TestCase):
    def test_short_history_preserved_for_followup(self):
        history=[{'role':'user','content':'My bicycle is red.'},{'role':'assistant','content':'Your bicycle is red.'}]
        self.assertEqual(bounded_history(history,'Tutor','What color?',2048,384),history)

    def test_long_history_keeps_whole_recent_turns_without_orphans(self):
        history=[{'role':'user','content':'long'*4000},{'role':'assistant','content':'old'},
                 {'role':'user','content':'My bicycle is red.'},{'role':'assistant','content':'Red bicycle.'}]
        self.assertEqual(bounded_history(history,'Tutor','What color?',2048,384),history[-2:])
        self.assertEqual(len(history[0]['content']),16000)

    def test_long_current_request_is_never_sliced_to_fit_history(self):
        self.assertEqual(bounded_history([{'role':'user','content':'Old'}],'x'*9000,'Current question',2048,384),[])

    def test_short_sources_are_kept_verbatim(self):
        context='\n[S1] Grammar notes\nPresent perfect: have/has + past participle.\n'
        self.assertEqual(fit_context('Tutor rules',context,'Explain it',4096,384),context)

    def test_oversized_sources_are_trimmed_to_fit_the_window(self):
        # The real failure: 6264-token prompts against a 2048 window. After trimming,
        # system + sources + question + reply must fit the same byte budget.
        system='Tutor rules '*200
        context=''.join(f'\n[S{i}] Chương {i}\n'+('Thì hiện tại hoàn thành dùng để diễn tả. '*60) for i in range(1,8))
        trimmed=fit_context(system,context,'Giải thích giúp mình',4096,384)
        self.assertTrue(trimmed.endswith(CONTEXT_TRIMMED_NOTE))
        used=len(system.encode())+len(trimmed.encode())+len('Giải thích giúp mình'.encode())+600
        self.assertLessEqual(used,(4096-384-128)*3)
        trimmed.encode('utf-8')  # never cut inside a multi-byte Vietnamese character
        self.assertTrue(trimmed.startswith('\n[S1] Chương 1'))

    def test_no_room_for_sources_drops_them_instead_of_overflowing(self):
        self.assertEqual(fit_context('x'*20000,'\n[S1] doc\ntext','q',4096,384),'')


class SelfReviewTests(unittest.TestCase):
    draft='Thì hiện tại hoàn thành dùng have/has + V3. Ví dụ: I have finished my homework. [S1] '*4

    def test_ok_variants_keep_the_draft(self):
        for review in ('OK','ok.','OK!\nNothing to change.','<<<\nOK\n>>>',''):
            self.assertEqual(accept_review(self.draft,review),self.draft)

    def test_full_correction_is_used(self):
        fixed=self.draft.replace('V3','V3 (quá khứ phân từ)')
        self.assertEqual(accept_review(self.draft,fixed),fixed.strip())

    def test_untrustworthy_reviews_fall_back_to_the_draft(self):
        self.assertEqual(accept_review(self.draft,'The draft is mostly correct but could be shorter.'),self.draft)
        self.assertEqual(accept_review(self.draft,'Đúng rồi.'),self.draft)  # far too short: truncated
        no_sources=self.draft.replace('[S1]','')
        self.assertEqual(accept_review(self.draft,no_sources),self.draft)  # dropped citations

    def test_review_prompt_carries_question_draft_and_language_rules(self):
        messages=review_messages('Thì hiện tại hoàn thành là gì?',self.draft,'vi','Grammar')
        self.assertIn('explanations must be in Vietnamese',messages[0]['content'])
        self.assertIn('Thì hiện tại hoàn thành là gì?',messages[1]['content'])
        self.assertIn('have/has',messages[1]['content'])
        roleplay=review_messages('A latte, please.','Sure! Anything else?','vi','Role Play')
        self.assertIn('stays in character',roleplay[0]['content'])


if __name__=='__main__': unittest.main()
