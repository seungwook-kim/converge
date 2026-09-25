"""평가셋을 돌려 점수를 낸다. (evals/EVAL_GUIDE.md)

무엇을 재나:
  문항마다 파이프라인을 한 번 태우고 다섯 축으로 나눠 본다. 하나로 뭉치면 점수가 떨어져도
  어디가 무너졌는지 못 짚는다.

    슬롯 정확도      기대한 슬롯 칸과 실제가 같은가 (문항에 expected 가 있을 때만)
    계약 준수율      응답이 스키마를 지켰는가. stage 별 필수 항목이 채워졌는가
    단계 도달        어느 stage 로 끝났는가. 기대한 stage 와 같은가
    지연             요청 하나에 걸린 시간
    비용             그 요청이 쓴 모델 비용

  "현장 적합성"은 사람이 본다. 여기서는 재지 않는다 (EVAL_GUIDE 평가 축).

정답은 사람이 쓴다:
  이 스크립트는 채점만 한다. 문항과 정답을 만들지 않는다. LLM 이 만든 정답으로 LLM 을 평가하면
  아무것도 증명되지 않는다 (EVAL_GUIDE).

문항 형식 (evals/dataset.jsonl, 한 줄에 하나):
    {"id": 1,
     "input": "토요일 오후 2시 강남역 근처에서 봅시다. 저는 수원시청에서 차로 갑니다.",
     "expected": {"stage": "done", "slots": {"preset": "meeting"}},
     "note": "정상", "why": "절차 이야기가 없고 카페 자리라 meeting 이다"}

  expected 는 세 가지 모양을 받는다.
    - 비어 있음        점수를 매기지 않고 돌려만 본다 (계약·지연·비용은 잰다)
    - 문자열           stage 이름으로 본다. "done", "need_info" 처럼
    - 객체             {"stage": ..., "slots": {칸: 값}} 형태. slots 는 적힌 칸만 본다

실행:
    python evals/run_eval.py                          # 기본 데이터셋
    python evals/run_eval.py --dataset evals/dataset.jsonl --limit 5
    python evals/run_eval.py --dry-run                # 모델을 부르지 않고 문항만 검사

결과는 evals/results/<시각>.json 에 남고, 요약을 화면에 찍는다.
Langfuse 가 켜져 있으면 파이프라인이 알아서 트레이스를 남긴다 (run_eval 이 따로 올리지 않는다).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEFAULT_DATASET = ROOT / "evals" / "dataset.jsonl"
RESULTS_DIR = ROOT / "evals" / "results"
EVAL_USER_ID = "00000000-0000-0000-0000-000000000002"  # 평가 실행은 사람 계정과 섞이지 않게 따로 둔다

# 문항 뼈대에 들어 있는 자리 표시. 이게 그대로면 아직 사람이 안 쓴 문항이다
PLACEHOLDERS = ("여기에 입력", "경계에 있는 입력", "실패를 유도하는 입력")


def load_env() -> None:
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ[key.strip()] = value.split(" #")[0].strip().strip('"')


def load_dataset(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """문항과 "아직 안 쓴 문항" 목록을 돌려준다."""
    rows: list[dict[str, Any]] = []
    todo: list[str] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        text = str(row.get("input") or "")
        if not text or text in PLACEHOLDERS:
            todo.append(f"{line_no}행 (id={row.get('id')})")
            continue
        rows.append(row)
    return rows, todo


# ─────────────────────────────────────────────────────────────── 채점


def expected_stage(expected: Any) -> str | None:
    if isinstance(expected, str) and expected.strip():
        return expected.strip()
    if isinstance(expected, dict):
        stage = expected.get("stage")
        return str(stage) if stage else None
    return None


def expected_slots(expected: Any) -> dict[str, Any]:
    if isinstance(expected, dict) and isinstance(expected.get("slots"), dict):
        return expected["slots"]
    return {}


def slot_value(slots: Any, key: str) -> Any:
    """"access.required" 처럼 점으로 쓴 경로를 따라간다.

    끝에서 만나는 값이 Pydantic 모델이면 dict 로 바꿔 돌려준다. 결과를 파일로 남기기 때문에
    JSON 으로 써지는 값이어야 한다 (09-21: Access 객체가 그대로 나와 저장이 터졌다).
    """
    current: Any = slots
    for part in key.split("."):
        if current is None:
            return None
        current = getattr(current, part, None) if not isinstance(current, dict) else current.get(part)
    dump = getattr(current, "model_dump", None)
    return dump() if callable(dump) else current


def check_contract(response: Any) -> list[str]:
    """스키마가 막지 못하는 약속을 본다. 화면이 stage 하나만 보고 갈라지기 때문에 여기서 느슨해지면 빈 화면이 나간다."""
    problems: list[str] = []
    stage = response.stage
    if stage == "done" and response.result is None:
        problems.append("done 인데 result 가 없다")
    if stage == "need_info" and not response.questions:
        problems.append("need_info 인데 questions 가 비었다")
    if stage == "need_confirm" and not response.geocoded:
        problems.append("need_confirm 인데 지도에 찍을 좌표가 없다")
    if stage == "done" and response.result is not None:
        if not response.result.per_participant:
            problems.append("done 인데 참석자별 결과가 비었다")
        ranks = [c.rank for c in response.result.candidates if c.rank]
        if len(ranks) != len(set(ranks)):
            problems.append("후보 순위가 겹친다")
        for cand in response.result.candidates:
            if cand.rank and cand.rank > 1 and not cand.rejected_reason:
                problems.append(f"{cand.name}: 1순위가 아닌데 탈락 이유가 없다")
    if not response.message:
        problems.append("화면에 보여줄 message 가 비었다")
    return problems


def score_row(row: dict[str, Any], response: Any) -> dict[str, Any]:
    expected = row.get("expected")
    want_stage = expected_stage(expected)
    want_slots = expected_slots(expected)

    slot_hits: list[dict[str, Any]] = []
    for key, want in want_slots.items():
        got = slot_value(response.slots, key)
        slot_hits.append({"key": key, "expected": want, "got": got, "ok": got == want})

    contract = check_contract(response)
    return {
        "stage": response.stage,
        "stage_expected": want_stage,
        "stage_ok": None if want_stage is None else response.stage == want_stage,
        "slots": slot_hits,
        "slot_ok": None if not slot_hits else all(h["ok"] for h in slot_hits),
        "contract_problems": contract,
        "contract_ok": not contract,
    }


# ─────────────────────────────────────────────────────────────── 실행


async def run_one(row: dict[str, Any]) -> dict[str, Any]:
    from backend.app.schemas.request import AgentRequest
    from backend.app.services import llm, pipeline

    started = time.time()
    try:
        response = await pipeline.run(AgentRequest(text=row["input"]), EVAL_USER_ID)
    except Exception as e:  # noqa: BLE001  한 문항이 터져도 나머지를 돌린다
        return {"id": row.get("id"), "input": row["input"], "error": f"{type(e).__name__}: {e}",
                "seconds": round(time.time() - started, 2)}

    meta = llm.last_meta()
    out = {
        "id": row.get("id"),
        "input": row["input"],
        "note": row.get("note"),
        "seconds": round(time.time() - started, 2),
        "model": meta.get("model"),
        "cost_usd": meta.get("cost_usd") or 0.0,
        "trace_id": response.trace_id,
        **score_row(row, response),
    }
    return out


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    ok = [r for r in results if "error" not in r]
    graded_stage = [r for r in ok if r.get("stage_ok") is not None]
    graded_slots = [r for r in ok if r.get("slot_ok") is not None]
    seconds = sorted(r["seconds"] for r in ok)

    def rate(rows: list[dict[str, Any]], key: str) -> float | None:
        return round(sum(1 for r in rows if r[key]) / len(rows), 3) if rows else None

    return {
        "문항": len(results),
        "실행 실패": len(results) - len(ok),
        "단계 정확도": rate(graded_stage, "stage_ok"),
        "단계 채점 문항": len(graded_stage),
        "슬롯 정확도": rate(graded_slots, "slot_ok"),
        "슬롯 채점 문항": len(graded_slots),
        "계약 준수율": rate(ok, "contract_ok"),
        "지연 p50": seconds[len(seconds) // 2] if seconds else None,
        "지연 p95": seconds[int(len(seconds) * 0.95) - 1] if len(seconds) >= 2 else None,
        "비용 합계": round(sum(r.get("cost_usd") or 0.0 for r in ok), 6),
    }


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--limit", type=int, help="앞에서 몇 문항만")
    parser.add_argument("--dry-run", action="store_true", help="모델을 부르지 않고 문항만 검사한다")
    parser.add_argument("--model", help="이 실행에서만 MODEL_SMALL·MODEL_LARGE 를 바꾼다. 예: openai/gpt-4o-mini (.env 는 그대로)")
    parser.add_argument("--prompt-label", help="Langfuse 프롬프트 라벨. 운영에 올리기 전 staging 을 잴 때 (기본 production)")
    args = parser.parse_args()

    load_env()
    if args.model:
        # load_env 가 .env 로 덮어쓴 뒤에 바꾼다. 모델 비교(2개 이상)와 한도 소진 때 대체 실행용 (09-23)
        os.environ["MODEL_SMALL"] = os.environ["MODEL_LARGE"] = args.model
    if args.prompt_label:
        from backend.app.observability import langfuse as lf

        original = lf.get_prompt
        lf.get_prompt = lambda name, label="production": original(name, label=args.prompt_label)
    rows, todo = load_dataset(Path(args.dataset))
    if todo:
        print(f"아직 안 쓴 문항 {len(todo)}건은 건너뛴다: {', '.join(todo[:5])}")
    if not rows:
        print("돌릴 문항이 없다. evals/dataset.jsonl 에 사람이 문항을 써야 한다 (EVAL_GUIDE).")
        return 1
    if args.limit:
        rows = rows[: args.limit]

    print(f"문항 {len(rows)}건")
    if args.dry_run:
        for row in rows:
            want = expected_stage(row.get("expected"))
            keys = list(expected_slots(row.get("expected")))
            print(f"  [{row.get('id')}] stage={want or '채점 안 함'} slots={keys or '채점 안 함'}")
            print(f"        {row['input'][:70]}")
        return 0

    results = []
    for row in rows:
        result = await run_one(row)
        results.append(result)
        if "error" in result:
            mark = "실행 실패"
        else:
            marks = [m for m in (
                None if result["stage_ok"] is None else ("단계 O" if result["stage_ok"] else "단계 X"),
                None if result["slot_ok"] is None else ("슬롯 O" if result["slot_ok"] else "슬롯 X"),
                "계약 O" if result["contract_ok"] else "계약 X",
            ) if m]
            mark = " · ".join(marks)
        print(f"  [{result.get('id')}] {result['seconds']:5.1f}s  {mark}")
        if result.get("contract_problems"):
            for problem in result["contract_problems"]:
                print(f"        계약: {problem}")

    summary = summarize(results)
    print()
    for key, value in summary.items():
        print(f"  {key:12} {value}")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out_path = RESULTS_DIR / f"{stamp}.json"
    out_path.write_text(
        json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"\n  결과 저장   {out_path.relative_to(ROOT)}")
    print("  현장 적합성은 사람이 본다. 위 숫자로는 재지 않는다 (EVAL_GUIDE).")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
