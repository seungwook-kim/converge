"""배포본 한 사이클(POST /api/agent 하나)의 단계별 시간을 Langfuse 트레이스에서 모은다. (docs/measurements.md)

왜 있나: 회귀셋(evals/run_eval.py)은 이 PC 에서 파이프라인을 돌려 정확도를 잰다. 배포된 서버가 실제로
얼마나 걸리는지, 어느 단계가 느린지는 배포본 트레이스를 봐야 안다 (10-20).

입력은 요청 기록 JSON 이다. 브라우저나 다른 도구로 배포본에 요청을 보내고, 요청마다
{"round": 1, "id": 문항, "ms": 화면이 잰 시간, "status": 200, "stage": "done", "trace_id": "..."} 를 한 줄씩 남긴 목록.

    python scripts/measure_cycle.py evals/results/cycle-20261020.json

출력: 단계별 p50·p95·최대, 전체(서버)와 화면 기준 시간, 회차별 요약. 같은 파일 옆에 -summary.json 을 남긴다.
키는 루트 .env 의 LANGFUSE_* 를 쓴다. 실행하지 않은 숫자를 문서에 적지 않는다 (CLAUDE.md).
"""
from __future__ import annotations

import base64
import json
import os
import statistics
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_env() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.split(" #")[0].strip().strip('"'))


def _get(path: str) -> dict:
    host = os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com").rstrip("/")
    token = base64.b64encode(f'{os.environ["LANGFUSE_PUBLIC_KEY"]}:{os.environ["LANGFUSE_SECRET_KEY"]}'.encode()).decode()
    req = urllib.request.Request(host + path, headers={"Authorization": "Basic " + token})
    return json.load(urllib.request.urlopen(req, timeout=30))


def _trace(trace_id: str) -> dict | None:
    """트레이스가 Langfuse 에 들어오기까지 몇 초 걸린다. 잠깐씩 다시 묻는다.

    /api/public/traces/{id} 는 2026-11-16 에 없어져서 v2 observations 로 읽는다 (10-31).
    돌려주는 모양은 예전과 같게 {"observations": [...]} 로 맞춘다. 429 가 오면 더 길게 쉰다.
    """
    for i in range(6):
        try:
            data = _get(f"/api/public/v2/observations?traceId={trace_id}&limit=100").get("data", [])
            if data:
                return {"observations": data}
        except Exception:  # noqa: BLE001
            pass
        time.sleep(5 + 5 * i)
    return None


def _seconds(obs: dict) -> float | None:
    if not obs.get("startTime") or not obs.get("endTime"):
        return None
    start = datetime.fromisoformat(obs["startTime"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(obs["endTime"].replace("Z", "+00:00"))
    return (end - start).total_seconds()


def _stats(values: list[float]) -> dict:
    values = sorted(values)
    if not values:
        return {}
    p95 = values[min(len(values) - 1, round(0.95 * (len(values) - 1)))]
    return {"n": len(values), "p50": round(statistics.median(values), 2), "p95": round(p95, 2), "max": round(values[-1], 2)}


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    _load_env()
    src = Path(sys.argv[1])
    rows = json.loads(src.read_text(encoding="utf-8"))

    per_step: dict[str, list[float]] = {}
    server: list[float] = []
    client = [r["ms"] / 1000 for r in rows if r.get("status") == 200]
    missing = 0
    for r in rows:
        if not r.get("trace_id"):
            continue
        t = _trace(r["trace_id"])
        if t is None:
            missing += 1
            continue
        for o in t.get("observations", []):
            sec = _seconds(o)
            if sec is None:
                continue
            if o["name"] == "agent":
                server.append(sec)
            else:
                per_step.setdefault(o["name"], []).append(sec)

    by_round: dict[int, list[float]] = {}
    by_stage: dict[str, list[float]] = {}
    for r in rows:
        if r.get("status") == 200:
            by_round.setdefault(r["round"], []).append(r["ms"] / 1000)
            by_stage.setdefault(r.get("stage") or "?", []).append(r["ms"] / 1000)

    summary = {
        "requests": len(rows),
        "ok": sum(1 for r in rows if r.get("status") == 200),
        "stages": {s: sum(1 for r in rows if r.get("stage") == s) for s in sorted({r.get("stage") for r in rows if r.get("stage")})},
        "traces_missing": missing,
        "client_total": _stats(client),
        "server_total": _stats(server),
        "by_round_client": {k: _stats(v) for k, v in sorted(by_round.items())},
        # 끝까지 계산(done)과 되묻기(need_info)는 하는 일이 달라 시간도 다르다. 섞으면 평균이 뜻을 잃는다
        "by_stage_client": {k: _stats(v) for k, v in sorted(by_stage.items())},
        "steps": {k: _stats(v) for k, v in sorted(per_step.items(), key=lambda kv: -statistics.median(kv[1]))},
    }
    out = src.with_name(src.stem + "-summary.json")
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"요청 {summary['requests']}  성공 {summary['ok']}  stage {summary['stages']}  트레이스 못 찾음 {missing}")
    print(f"화면 기준 전체  {summary['client_total']}")
    print(f"서버 기준 전체  {summary['server_total']}")
    for k, v in summary["by_round_client"].items():
        print(f"  {k}회차(화면)  {v}")
    for k, v in summary["by_stage_client"].items():
        print(f"  {k}(화면)  {v}")
    print("단계별 (느린 순)")
    for k, v in summary["steps"].items():
        print(f"  {k:12s} {v}")
    print(f"저장 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
