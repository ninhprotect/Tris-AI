"""Explicit real-Ollama smoke test; temporary SQLite, no production account bypass."""
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from database import TutorDatabase
from config.settings import MODEL_NAME
from workspace_api import install_workspace_routes


def main():
    with tempfile.TemporaryDirectory(prefix="tris-real-model-test-") as folder:
        database = TutorDatabase(Path(folder) / "test.db")
        database.initialize()
        def require_access(token, authorization):
            if authorization != "Bearer isolated-test": raise HTTPException(401)
        backend = SimpleNamespace(app=FastAPI(), require_access=require_access,
            bearer_account=lambda authorization: SimpleNamespace(learner_name="Isolated Test"),
            user_id_for=database.get_or_create_user, database=database,
            learner_context_for=lambda user: ([],"Keep the response brief."))
        install_workspace_routes(backend)
        with TestClient(backend.app) as client:
            response = client.post("/v1/workspace/chat", headers={"Authorization":"Bearer isolated-test"},
                                   json={"message":"Say hello in one short sentence.","model":MODEL_NAME,"language":"en"})
            response.raise_for_status()
            events = [json.loads(line) for line in response.text.splitlines()]
            if any(event.get("error") for event in events) or not events[-1].get("done"):
                raise RuntimeError("Real local inference did not complete")
            answer = "".join(event.get("delta", "") for event in events)
            if not answer.strip(): raise RuntimeError("Empty model response")
            saved = database.workspace_history(database.get_or_create_user("Isolated Test"))
            assert len(saved) == 2
            print(json.dumps({"model":MODEL_NAME,"real_inference":True,"saved_messages":len(saved),
                              "seconds":events[-1]["seconds"],"answer_preview":answer[:220]},ensure_ascii=False))

if __name__ == "__main__": main()
