"""Regression coverage for replacing Gradio without changing the learner profile."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from workspace_features import install_feature_routes


class FeatureTests(unittest.TestCase):
    def setUp(self):
        def access(token, authorization):
            if authorization != "Bearer valid": raise HTTPException(401, "Sign in")
        self.db = SimpleNamespace(
            workspace_history=Mock(return_value=[{"id": 3, "mode": "Grammar", "scenario": "", "role": "user", "content": "My saved sentence", "created_at": "2026-09-01"}]),
            get_user_preferences=Mock(return_value=SimpleNamespace(language="vi")),
            get_exercise_session=Mock(return_value={"questions": [{"question_id": 9}]}),
            set_exercise_question_flag=Mock(),
        )
        self.backend = SimpleNamespace(app=FastAPI(), require_access=access,
            bearer_account=lambda token: SimpleNamespace(learner_name="Existing Learner") if token == "Bearer valid" else None,
            database=self.db, user_id_for=Mock(return_value=8), safe_call=lambda fn,*args: fn(*args),
            ExerciseRequest=lambda **kw: SimpleNamespace(**kw), SubmitRequest=lambda **kw: SimpleNamespace(**kw),
            create_exercise=Mock(return_value={"session_id":1,"questions":[]}),
            submit_exercise=Mock(return_value={"total":5,"correct_count":3}),
        )
        install_feature_routes(self.backend)
        self.client=TestClient(self.backend.app)
        self.auth={"Authorization":"Bearer valid"}

    def test_history_uses_existing_profile_not_new_namespace(self):
        response=self.client.get('/v1/workspace/session',headers=self.auth)
        self.assertEqual(response.status_code,200)
        self.backend.user_id_for.assert_called_with('Existing Learner')
        self.assertEqual(response.json()['chats'][0]['messages'][0]['content'],'My saved sentence')
        self.assertFalse(response.json()['chats'][0]['demo'])

    def test_history_requires_login(self):
        self.assertEqual(self.client.get('/v1/workspace/session').status_code,401)
        self.db.workspace_history.assert_not_called()

    def test_exercise_creation_routes_to_existing_engine(self):
        response=self.client.post('/v1/workspace/exercises',headers=self.auth,json={'question_count':5})
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.backend.create_exercise.call_args.args[0].learner_name,'Existing Learner')

    def test_bulk_submit_uses_one_call_and_authenticated_profile(self):
        response=self.client.post('/v1/workspace/exercises/1/submit',headers=self.auth,json={'answers':[{'question_id':i,'answer':'B'} for i in range(5)]})
        self.assertEqual(response.status_code,200)
        self.backend.submit_exercise.assert_called_once()
        self.assertEqual(len(self.backend.submit_exercise.call_args.args[1].answers),5)

    def test_flag_preserves_session_and_user_ownership(self):
        response=self.client.put('/v1/workspace/exercises/1/questions/9/flag',headers=self.auth,json={'flagged':True})
        self.assertEqual(response.status_code,200)
        self.db.set_exercise_question_flag.assert_called_once_with(8,1,9,True)

    def test_foreign_question_cannot_be_flagged(self):
        response=self.client.put('/v1/workspace/exercises/1/questions/99/flag',headers=self.auth,json={'flagged':True})
        self.assertEqual(response.status_code,404)
        self.db.set_exercise_question_flag.assert_not_called()

    def test_presence_rejects_other_web_origin(self):
        response=self.client.post('/v1/workspace/presence',headers={'Origin':'https://elsewhere.example'},json={'tab':'test-tab-12345'})
        self.assertEqual(response.status_code,403)

if __name__=='__main__': unittest.main()
