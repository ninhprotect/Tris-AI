"""Opt-in local chat regressions, using a temporary database and fixture account.

Example (run with the project's .venv Python):
    python scripts/evaluate_chat_quality.py --list
    python scripts/evaluate_chat_quality.py --run --model english-tutor-local:4b

This calls installed Ollama models through the real workspace route. It does
not train weights, download models, start a production server, access real
accounts, or save exchanges to the user's database. Model loading uses local
GPU/RAM and can compete with a running Tris session; run when Tris is idle.
The report contains only these synthetic prompts/answers and timing metadata.
Passing this small keyword-based check does not measure general intelligence.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import tempfile
import time
from types import SimpleNamespace
import unicodedata
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
CASES_PATH = PROJECT_ROOT / "tests" / "quality_cases.json"
NOTICE = (
    "Synthetic local regression checks only; keyword matches can miss errors or "
    "reject valid paraphrases. Review the answers manually. This is not a "
    "general intelligence benchmark, fine-tuning, or evidence of trained weights."
)


def normalized(value: str) -> str:
    # Compare wording, not Markdown emphasis. Retain the raw answer in reports.
    plain = re.sub(r'[*_`]', '', unicodedata.normalize("NFC", value).casefold())
    return " ".join(plain.split())


def redacted(value: str) -> str:
    """Defense in depth: never include token/secret-shaped strings in reports."""
    value = re.sub(r"(?i)\bBearer\s+[^\s\"']+", "Bearer [redacted]", value)
    value = re.sub(r"\bGOCSPX-[A-Za-z0-9_-]+", "[redacted]", value)
    value = re.sub(
        r"(?i)([?&](?:code|state|access_token|refresh_token|client_secret)=)[^\s&#]+",
        r"\1[redacted]", value,
    )
    return value


def check_answer(case: dict, answer: str) -> list[dict]:
    text = normalized(answer)
    checks = [{"check": "nonempty_answer", "passed": bool(text)}]
    for phrase in case.get("contains_all", []):
        checks.append({"check": f"contains: {phrase}", "passed": normalized(phrase) in text})
    choices = case.get("contains_any", [])
    if choices:
        checks.append({"check": "contains any: " + " | ".join(choices),
                       "passed": any(normalized(phrase) in text for phrase in choices)})
    for pattern in case.get("matches_all", []):
        checks.append({"check": f"pattern: {pattern}",
                       "passed": bool(re.search(pattern, text, re.IGNORECASE))})
    alternatives = case.get("matches_any", [])
    if alternatives:
        checks.append({"check": "matches any pattern: " + " | ".join(alternatives),
                       "passed": any(re.search(pattern, text, re.IGNORECASE) for pattern in alternatives)})
    for phrase in case.get("excludes", []):
        checks.append({"check": f"does not contain: {phrase}",
                       "passed": normalized(phrase) not in text})
    return checks


def load_cases(case_ids: list[str] | None = None) -> list[dict]:
    payload = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("Unsupported quality-case schema.")
    cases = payload["cases"]
    ids = [case["id"] for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("Quality-case IDs must be unique.")
    if case_ids:
        unknown = set(case_ids) - set(ids)
        if unknown:
            raise ValueError("Unknown case IDs: " + ", ".join(sorted(unknown)))
        cases = [case for case in cases if case["id"] in case_ids]
    for case in cases:
        if not isinstance(case.get("message"), str) or not case["message"].strip():
            raise ValueError("Each case must have a nonempty message.")
        for pattern in case.get("matches_all", []) + case.get("matches_any", []):
            re.compile(pattern)
    return cases


def evaluate_case(client, case: dict, model: str) -> dict:
    # No production token is read or needed; this header belongs to the fixture.
    body = {"message": case["message"], "model": model,
            "language": case.get("language", "vi"), "mode": case.get("mode", "Conversation"),
            "history": case.get("history", []), "action": "chat", "web_search": False,
            "document_ids": [], "image_context": ""}
    started = time.perf_counter()
    answer, errors, events = "", [], []
    status = None
    try:
        response = client.post("/v1/workspace/chat", headers={"Authorization": "Bearer quality-fixture"}, json=body)
        status = response.status_code
        if not response.is_success:
            # Status alone is sufficient; never copy arbitrary server error bodies.
            errors.append(f"HTTP {status}")
        else:
            events = [json.loads(line) for line in response.text.splitlines() if line.strip()]
            answer = "".join(str(event.get("delta", "")) for event in events)
            errors.extend(redacted(str(event["error"]))[:800] for event in events if event.get("error"))
            if not events or not events[-1].get("done"):
                errors.append("Stream did not finish with a done event.")
    except Exception as exc:
        # Exception messages can contain URLs/environment details; record only type.
        errors.append(type(exc).__name__)
    checks = check_answer(case, answer)
    checks.insert(0, {"check": "completed_without_service_error", "passed": not errors})
    return {
        "id": case["id"], "description": case["description"],
        "expected_path": case.get("expected_path", "model"),
        "prompt": redacted(case["message"]), "language": body["language"], "mode": body["mode"],
        "history": case.get("history", []), "http_status": status,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "reported_processing_seconds": next((event["seconds"] for event in reversed(events) if event.get("done") and "seconds" in event), None),
        "answer": redacted(answer), "errors": errors, "checks": checks,
        "passed": all(check["passed"] for check in checks),
    }


def run_evaluation(cases: list[dict], model: str) -> list[dict]:
    # Delay app imports until explicit --run. --list never contacts any service.
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient
    from config.settings import OLLAMA_HOST
    from database import TutorDatabase
    from workspace_api import install_workspace_routes

    if urlparse(OLLAMA_HOST).hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("This local-only evaluation requires a loopback OLLAMA_HOST.")

    def require_access(token, authorization):
        if authorization != "Bearer quality-fixture":
            raise HTTPException(status_code=401, detail="Fixture account required.")

    def unused_service(*args, **kwargs):
        raise RuntimeError("External/media services are disabled in this evaluation.")

    with tempfile.TemporaryDirectory(prefix="tris-quality-fixture-") as folder:
        database = TutorDatabase(Path(folder) / "quality.db")
        database.initialize()
        account = SimpleNamespace(learner_name="Synthetic Quality Fixture")
        backend = SimpleNamespace(
            app=FastAPI(), require_access=require_access,
            bearer_account=lambda authorization: account if authorization == "Bearer quality-fixture" else None,
            user_id_for=database.get_or_create_user, database=database,
            learner_context_for=lambda user_id: ([], "Keep the response brief and answer the learner's actual question."),
            web_search_service=SimpleNamespace(gather=unused_service),
            imagegen_service=SimpleNamespace(generate=unused_service),
        )
        install_workspace_routes(backend)
        results = []
        with TestClient(backend.app) as client:
            for case in cases:
                result = evaluate_case(client, case, model)
                results.append(result)
                state = "PASS" if result["passed"] else "REVIEW"
                print(f"{state} {case['id']} ({result['elapsed_seconds']:.2f}s)", flush=True)
                for check in result["checks"]:
                    if not check["passed"]:
                        print("  Unmet: " + check["check"], flush=True)
        return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run", action="store_true", help="Explicitly allow inference with the installed local model.")
    parser.add_argument("--list", action="store_true", help="List and validate cases without loading models or contacting services.")
    parser.add_argument("--model", default="english-tutor-local:4b", help="Exact installed Ollama model name; nothing will be downloaded.")
    parser.add_argument("--case", action="append", dest="case_ids", help="Run/list only this case ID (repeatable).")
    parser.add_argument("--output", type=Path, help="New JSON report path; defaults to data/quality-report-<UTC timestamp>.json.")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        cases = load_cases(args.case_ids)
    except (ValueError, KeyError, OSError) as exc:
        parser.error(str(exc))
    if args.list:
        for case in cases:
            print(case["id"] + ": " + case["description"])
        return 0
    if not args.run:
        parser.error("Use --list to inspect cases or --run to explicitly start local inference.")
    started = datetime.now(timezone.utc)
    stamp = started.strftime("%Y%m%d-%H%M%S-%fZ")
    output = (args.output or PROJECT_ROOT / "data" / f"quality-report-{stamp}.json").resolve()
    if output.exists():
        parser.error("Report already exists; choose a new --output path. Existing files are never overwritten.")
    print(NOTICE, flush=True)
    print("Using a temporary database/account. Local inference may use GPU/RAM; no model downloads.", flush=True)
    results = run_evaluation(cases, args.model)
    finished = datetime.now(timezone.utc)
    report = {"schema_version": 1, "notice": NOTICE, "model": redacted(args.model),
              "started_at_utc": started.isoformat(), "finished_at_utc": finished.isoformat(),
              "elapsed_seconds": round((finished - started).total_seconds(), 3),
              "isolated_database": True, "synthetic_cases_only": True, "training_performed": False,
              "case_count": len(results), "checks_passed_cases": sum(result["passed"] for result in results),
              "results": results}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print("Report: " + str(output), flush=True)
    print("Review answers manually; this regression report is not an intelligence score.", flush=True)
    return 0 if all(result["passed"] for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
