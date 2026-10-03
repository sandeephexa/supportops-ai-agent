"""Reproducible application smoke evaluations; no judge calls unless --ragas is explicit."""

import argparse
import asyncio
import json
import os
import statistics
import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient
from supportops.api import create_app
from supportops.config import ROOT, Settings
from supportops.guardrails import verify_answer


async def ragas_score(rows, settings):
    os.environ["RAGAS_DO_NOT_TRACK"] = "true"
    from openai import AsyncOpenAI
    from ragas.llms import llm_factory
    from ragas.metrics.collections import FactualCorrectness, Faithfulness

    client = AsyncOpenAI(api_key=settings.api_key, base_url=settings.base_url)
    llm = llm_factory(settings.reasoning_model, client=client)
    faithfulness, correctness = Faithfulness(llm=llm), FactualCorrectness(llm=llm)
    try:
        for row in rows:
            if "response" not in row:
                continue
            faithful = await faithfulness.ascore(
                user_input=row["question"], response=row["response"], retrieved_contexts=row["contexts"]
            )
            correct = await correctness.ascore(response=row["response"], reference=row["reference"])
            row["ragas_faithfulness"] = float(faithful.value)
            row["ragas_factual_correctness"] = float(correct.value)
            row["judge_model"] = settings.reasoning_model
    finally:
        await client.close()


def evaluate(dataset, output, live=False, ragas=False):
    configured = Settings()
    if (live or ragas) and not configured.api_key:
        raise SystemExit("Live or Ragas evaluation requires SUPPORTOPS_API_KEY; demo evaluation needs none.")
    rows = []
    with tempfile.TemporaryDirectory(prefix="supportops-eval-") as temporary:
        settings = configured.model_copy(
            update={
                "environment": "development",
                "seed_demo_data": True,
                "auto_create_schema": True,
                "allowed_hosts": ["testserver"],
                "mode": "live" if live else "demo",
                "auth_mode": "demo",
                "database_url": f"sqlite:///{temporary}/app.db",
                "checkpoint_url": f"sqlite:///{temporary}/graph.db",
                "worker_enabled": False,
            }
        )
        with TestClient(create_app(settings)) as client:
            for raw in dataset.read_text().splitlines():
                case = json.loads(raw)
                started = time.monotonic()
                response = client.post(
                    "/api/cases", json={"account_id": case["account"], "question": case["question"]}
                )
                row = {"id": case["id"], "family": case["family"], "question": case["question"]}
                if "http_status" in case:
                    row.update(
                        passed=response.status_code == case["http_status"],
                        expected_http=case["http_status"],
                        actual_http=response.status_code,
                    )
                elif response.status_code != 202:
                    row.update(passed=False, error=f"HTTP {response.status_code}")
                else:
                    case_id = response.json()["id"]
                    client.app.state.worker.tick()
                    result = client.get(f"/api/cases/{case_id}").json()
                    answer = result.get("result") or {}
                    content = json.dumps(answer)
                    assertions = [word.lower() in content.lower() for word in case["expected"]]
                    safe = all(word not in json.dumps(result) for word in case.get("forbidden", []))
                    try:
                        verify_answer(answer, result["evidence"])
                        provenance = True
                    except Exception:
                        provenance = False
                    retrieved = [e["id"] for e in result["evidence"]]
                    recall = int(case["gold_doc"] in retrieved) if case["gold_doc"] else None
                    row.update(
                        passed=all(assertions) and safe and provenance and result["status"] == case["status"],
                        status=result["status"],
                        reference_assertion_accuracy=sum(assertions) / len(assertions),
                        citation_provenance_valid=provenance,
                        expected_evidence_retrieved=recall,
                        redaction_passed=safe,
                        response=content,
                        reference=case["reference"],
                        contexts=[e["content"] for e in result["evidence"]],
                    )
                row["latency_ms"] = round((time.monotonic() - started) * 1000, 2)
                rows.append(row)
        if ragas:
            asyncio.run(ragas_score(rows, configured))
    latencies = sorted(row["latency_ms"] for row in rows)
    report = {
        "suite": "curated-smoke-v1",
        "dataset_type": "development fixtures; not held-out production evidence",
        "mode": "live" if live else "demo",
        "connectors": "synthetic",
        "cases": len(rows),
        "passed": sum(row["passed"] for row in rows),
        "pass_rate": sum(row["passed"] for row in rows) / len(rows),
        "median_latency_ms": statistics.median(latencies),
        "p95_latency_ms": latencies[min(len(rows) - 1, int(len(rows) * 0.95))],
        "faithfulness": "Ragas judge scores per case"
        if ragas
        else "Not measured: provenance checks are not semantic faithfulness",
        "results": rows,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "results"}, indent=2))
    return report["passed"] == report["cases"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=ROOT / "evals" / "cases.jsonl")
    parser.add_argument("--output", type=Path, default=ROOT / "var" / "eval-report.json")
    parser.add_argument("--live", action="store_true", help="Use configured live inference; incurs API costs")
    parser.add_argument("--ragas", action="store_true", help="Run paid semantic judges against responses")
    args = parser.parse_args()
    raise SystemExit(0 if evaluate(args.dataset, args.output, args.live, args.ragas) else 1)
