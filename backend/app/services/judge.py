"""집결지 판정. 후보 표와 규칙을 대형 모델에 주고 순위를 받는다. (SDD 5절 6단계, 8절)

대형 모델이 만드는 것은 rank·reason·rejected_reason·switched_from 뿐이다. 숫자와 access_ok 는
코드가 이미 넣었고 여기서는 바꾸지 않는다.

스키마를 어기면 한 번 더 시도하고, 그래도 어기면 예외를 올린다. 부르는 쪽(pipeline)이 규칙 점수 순서로
대신 채운다 (SDD 5절 6단계 "실패면 rules.apply 순으로 rank, reason 은 규칙 문구 그대로").
"""
from __future__ import annotations

import json
from typing import Any

from backend.app.domain import rules as domain_rules
from backend.app.observability import langfuse
from backend.app.schemas.slots import Slots
from backend.app.services import costs as cost_guards
from backend.app.services import llm
from backend.app.services.llm import _parse_json_block, model_large

# 프리셋이 둘로 갈려 프롬프트도 둘이었는데, 범용으로 바꾸면서 하나로 합쳤다 (2026-09-21).
JUDGE_PROMPT = "converge/judge"

# 프롬프트에 붙이는 규칙 파일. 값이 아니라 문서를 그대로 넣는다 (RAG 없이 통째로, CLAUDE.md)
RULE_FILES = ("access", "transport")


def _rules_text() -> str:
    lines: list[str] = []
    for name in RULE_FILES:
        values = domain_rules.load_rule(name)
        lines.append(f"[{name}.md]")
        lines.extend(f"- {key}: {value}" for key, value in values.items())
    return "\n".join(lines)


def _situation_text(slots: Slots) -> str:
    access = slots.access
    return "\n".join(
        [
            f"- 목적지: {slots.destination}",
            f"- 목적: {slots.purpose}",
            f"- 약속: {slots.datetime}",
            f"- 출입 절차: 필요={access.required if access else None}, 신청={access.applied if access else None}",
            f"- 제약: {', '.join(slots.constraints) if slots.constraints else '없음'}",
            f"- 집결지 언급: {slots.rendezvous.name if slots.rendezvous else '없음'}",
            "- 참석자: "
            + ", ".join(
                f"{p.name}({p.role}, {p.transport or '미정'}"
                + (f", {p.pickup} 차로 {p.pickup_at} 탑승" if p.pickup else "")
                + (", 지리 모름" if p.unfamiliar else "")
                + ")"
                for p in slots.participants
            ),
        ]
    )


def _candidates_text(candidates: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"{i}. {c['name']} (kind={c['kind']}, access_ok={c.get('access_ok', True)}, 주소={c['address'] or '미상'})"
        for i, c in enumerate(candidates)
    )


def _participants_text(rows: list[dict[str, Any]], candidates: list[dict[str, Any]] | None = None) -> str:
    """참석자별 경로. 후보 이름을 같이 적는다. 번호만 주면 모델이 이유에 "후보 2" 라고 쓰고,
    화면의 순위 번호와 달라 읽는 사람이 헷갈린다 (09-22 화면 E2E)."""
    if not rows:
        return "(경로 조회 결과 없음)"
    names = {i: c["name"] for i, c in enumerate(candidates or [])}
    return "\n".join(
        f"- {names.get(r['candidate_idx'], '후보')}(candidate_idx={r['candidate_idx']}) {r['name']}: "
        f"{r['transport']}, 경로 {r['raw_duration_min']}분"
        + (f", 환승 {r['transfer_count']}회" if r.get("transfer_count") else "")
        for r in rows
    )


async def rank(
    slots: Slots, candidates: list[dict[str, Any]], participant_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """후보 순위를 대형 모델에 맡긴다. 돌려주는 항목은 rankings 배열 그대로.

    candidates 항목에는 name·kind·address·access_ok 가, participant_rows 에는 candidate_idx·name·
    transport·raw_duration_min·transfer_count 가 있어야 한다.
    """
    prompt_name = JUDGE_PROMPT
    prompt, version = langfuse.get_prompt(prompt_name)
    filled = (
        prompt.replace("{{rules}}", _rules_text())
        .replace("{{situation}}", _situation_text(slots))
        .replace("{{candidates}}", _candidates_text(candidates))
        .replace("{{participants}}", _participants_text(participant_rows, candidates))
    )

    model = model_large()
    last_error: Exception | None = None
    # request_logs 에 남길 판정 호출 값. 재시도까지 합쳐 센다 (pipeline._judge_meta 가 읽는다)
    tokens_in = tokens_out = 0
    llm._last_meta.update({"judge_model": model, "judge_tokens_in": 0, "judge_tokens_out": 0, "judge_cost_usd": 0.0, "judge_attempts": 0})

    for attempt in (1, 2):
        messages = [{"role": "user", "content": filled}]
        if attempt == 2 and last_error is not None:
            messages.append(
                {
                    "role": "user",
                    "content": f"방금 출력이 형식을 어겼습니다: {last_error}. rankings 배열만 다시 JSON 으로 출력하세요.",
                }
            )
        # 크레딧이 떨어지면 FALLBACK 으로 바뀐다 (llm._create). 실제로 답한 모델을 기록에 남긴다
        res, used = await llm._create(
            model,
            messages=messages,
            temperature=0,
            response_format={"type": "json_object"},
        )
        if used != model:
            model = used
            llm._last_meta["judge_model"] = used
        usage = getattr(res, "usage", None)
        tokens_in += int(getattr(usage, "prompt_tokens", 0) or 0)
        tokens_out += int(getattr(usage, "completion_tokens", 0) or 0)
        llm._last_meta.update(
            {
                "judge_tokens_in": tokens_in,
                "judge_tokens_out": tokens_out,
                "judge_cost_usd": cost_guards.estimate_cost_usd(model, tokens_in, tokens_out),
                "judge_attempts": attempt,
            }
        )
        try:
            data = _parse_json_block(res.choices[0].message.content or "")
            rankings = _validate(data, len(candidates))
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
            last_error = e
            continue
        return [{**row, "model": model, "prompt_version": f"{prompt_name}@{version}"} for row in rankings]

    raise last_error if last_error else RuntimeError("판정에 실패했습니다")


def _validate(data: dict[str, Any], count: int) -> list[dict[str, Any]]:
    """모델 출력이 쓸 수 있는 모양인지 본다. 어기면 ValueError.

    후보 수와 답 수가 같아야 하고, 순위는 1부터 겹치지 않아야 한다. 하나라도 어긋나면 재시도한다.
    화면과 저장 스키마(SDD 4절)가 이 전제를 그대로 믿기 때문이다.
    """
    rankings = data.get("rankings")
    if not isinstance(rankings, list) or len(rankings) != count:
        raise ValueError(f"rankings 가 후보 수({count})와 다릅니다: {rankings!r}")

    seen_idx: set[int] = set()
    seen_rank: set[int] = set()
    out: list[dict[str, Any]] = []
    for row in rankings:
        idx, rank_value = row.get("candidate_idx"), row.get("rank")
        if not isinstance(idx, int) or not 0 <= idx < count or idx in seen_idx:
            raise ValueError(f"candidate_idx 가 잘못됐습니다: {idx!r}")
        if not isinstance(rank_value, int) or not 1 <= rank_value <= count or rank_value in seen_rank:
            raise ValueError(f"rank 가 잘못됐습니다: {rank_value!r}")
        seen_idx.add(idx)
        seen_rank.add(rank_value)
        out.append(
            {
                "candidate_idx": idx,
                "rank": rank_value,
                "reason": str(row.get("reason") or "").strip() or "판정 이유가 비어 있습니다",
                "rejected_reason": row.get("rejected_reason") or None,
                "switched_from": row.get("switched_from") or None,
            }
        )
    return out
