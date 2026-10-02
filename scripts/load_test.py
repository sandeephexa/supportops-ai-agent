"""Bounded local load probe. Runs only when explicitly invoked against a demo server."""

import argparse
import asyncio
import json
import time

import httpx


async def run(url, concurrency):
    async with httpx.AsyncClient(base_url=url, timeout=100) as client:
        health = (await client.get("/api/health")).json()
        if health["mode"] != "demo" or health["auth_mode"] != "demo":
            raise SystemExit("This fixture load probe is restricted to demo servers.")

        async def case():
            start = time.monotonic()
            result = await client.post(
                "/api/cases",
                json={"account_id": "acme", "question": "Investigate 403 errors after credential rotation."},
            )
            result.raise_for_status()
            case_id = result.json()["id"]
            deadline = time.monotonic() + 100
            while time.monotonic() < deadline:
                data = (await client.get(f"/api/cases/{case_id}")).json()
                if data["status"] not in ["queued", "running"]:
                    return {"status": data["status"], "seconds": round(time.monotonic() - start, 3)}
                await asyncio.sleep(0.2)
            return {"status": "timeout", "seconds": 100}

        results = await asyncio.gather(*(case() for _ in range(concurrency)))
        print(json.dumps({"concurrency": concurrency, "mode": "demo", "results": results}, indent=2))
        if any(r["status"] != "needs_approval" for r in results):
            raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--concurrency", type=int, choices=range(1, 11), default=5)
    args = parser.parse_args()
    asyncio.run(run(args.url, args.concurrency))
