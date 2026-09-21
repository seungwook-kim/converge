"""소형 모델(GGUF)로 슬롯을 뽑는다. (SDD 5절 1단계, 8절 "소형 (GGUF) 또는 대형 폴백")

파인튜닝한 모델은 학습 때와 같은 프롬프트로 불러야 한다. 형식이 다르면 스키마를 지키지 않고
제멋대로 키를 지어낸다 (09-20 실측). 그래서 학습 저장소에서 가져온 두 파일을 그대로 쓴다.

  backend/app/models/kanana_2.1b.prompt.json   system·instruction·separator·stop (학습 설정에서 추출)
  backend/app/models/grammar.gbnf              출력 JSON 문법. 형식을 벗어난 토큰을 아예 막는다

모델과 두 파일이 없으면 이 파일은 "쓸 수 없음"만 알려 주고, llm.py 가 대형 모델로 간다.
"""
from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Any

DEFAULT_MODEL_PATH = "backend/app/models/kanana_2.1b-Q4_K_M.gguf"
GRAMMAR_NAME = "grammar.gbnf"
N_THREADS = int(os.environ.get("MODEL_SMALL_THREADS", "8"))

_lock = threading.Lock()  # llama.cpp 인스턴스는 동시 호출에 안전하지 않다
_llm: Any | None = None
_grammar: Any | None = None
_spec: dict[str, Any] | None = None


def model_path() -> Path:
    return Path(os.environ.get("MODEL_SMALL_PATH", DEFAULT_MODEL_PATH))


def prompt_spec_path() -> Path:
    """GGUF 와 짝인 프롬프트 설정. 파일 이름은 모델 이름에서 만든다."""
    path = model_path()
    stem = path.name.split("-")[0]  # kanana_2.1b-Q4_K_M.gguf -> kanana_2.1b
    return path.with_name(f"{stem}.prompt.json")


def available() -> bool:
    """세 파일이 다 있고 llama_cpp 를 import 할 수 있는가."""
    if not (model_path().exists() and prompt_spec_path().exists()):
        return False
    if not (model_path().parent / GRAMMAR_NAME).exists():
        return False
    try:
        import llama_cpp  # noqa: F401
    except ImportError:
        return False
    return True


def _load() -> tuple[Any, Any, dict[str, Any]]:
    """모델을 한 번만 올린다. 1.3GiB 라 요청마다 올리면 답이 안 나온다."""
    global _llm, _grammar, _spec
    if _llm is None:
        from llama_cpp import Llama, LlamaGrammar

        spec = json.loads(prompt_spec_path().read_text(encoding="utf-8"))
        _llm = Llama(
            model_path=str(model_path()),
            n_ctx=int(spec.get("n_ctx", 2048)),
            n_threads=N_THREADS,
            verbose=False,
        )
        _grammar = LlamaGrammar.from_file(str(model_path().parent / GRAMMAR_NAME), verbose=False)
        _spec = spec
    return _llm, _grammar, _spec  # type: ignore[return-value]


BOS = "<|begin_of_text|>"


def build_prompt(spec: dict[str, Any], text: str) -> str:
    """학습 때와 같은 문자열 (finetune/common/prompting.py 의 prompt_format).

    Llama-3 계열 템플릿이다. system 에 스키마 설명이 통째로 들어간다. 이걸 빼면 모델이 학습한
    출력 형식을 잊고 제 나름의 키를 만든다.

    파일 형식이 두 가지다. 학습 저장소가 09-21 에 prefix·suffix 로 바꿨는데, 예전 파일로도
    돌아가야 하므로 둘 다 받는다.
      새 형식  {"prefix": "...user 헤더까지", "suffix": "...assistant 헤더"}  -> prefix + 문장 + suffix
      옛 형식  {"system", "instruction", "separator"}                        -> 여기서 조립

    어느 쪽이든 BOS 는 떼고 넘긴다. llama.cpp 가 BOS 를 자동으로 넣어 두 번 들어가고,
    그러면 학습 때와 토큰 열이 달라진다 (학습 설정도 add_bos: false).
    """
    if spec.get("prefix"):
        prompt = f"{spec['prefix']}{text}{spec.get('suffix', '')}"
    else:
        user = f"{spec['instruction']}{spec['separator']}{text}"
        prompt = (
            "<|start_header_id|>system<|end_header_id|>\n\n"
            f"{spec['system']}<|eot_id|>"
            "<|start_header_id|>user<|end_header_id|>\n\n"
            f"{user}<|eot_id|>"
            "<|start_header_id|>assistant<|end_header_id|>\n\n"
        )
    return prompt[len(BOS):] if prompt.startswith(BOS) else prompt


def extract_json(text: str) -> str:
    """모델 출력에서 JSON 문자열만. 파싱과 검증은 부르는 쪽(llm.py)이 한다."""
    llm, grammar, spec = _load()
    with _lock:
        out = llm(
            build_prompt(spec, text),
            max_tokens=int(spec.get("max_new_tokens", 400)),
            temperature=float(spec.get("temperature", 0.0)),
            stop=spec.get("stop") or [],
            grammar=grammar,
        )
    return str(out["choices"][0]["text"]).strip()


def model_name() -> str:
    """결과에 남길 이름. 어느 모델로 뽑았는지 화면과 로그에서 보인다."""
    return f"local/{model_path().stem}"


# ─────────────────────────────────────────────────────────────────────────────
# 소형 모델 출력 점검 (09-20 측정 결과)
# ─────────────────────────────────────────────────────────────────────────────
# 소형은 시각 정규화("목요일 아침 8시" -> "목요일 08:00")와 목적지 파악은 대형보다 낫다.
# 대신 호칭을 줄인다. "박업체 과장님" -> "업체", "한동료" -> "동료" 처럼 앞뒤를 잘라 버린다.
# 이름이 잘리면 화면에 그대로 나오고, 핀과 참석자를 이름으로 잇는 자리에서 어긋난다.
# 그래서 잘린 흔적이 보이면 그 요청만 대형으로 넘긴다 (llm.py 승격 경로).

# 이름을 원문에서 찾을 때 무시할 글자 (띄어쓰기 차이)
_NAME_NOISE = frozenset(" \t\n·,")


class NameTruncated(ValueError):
    """소형이 참석자 이름을 잘랐다. 대형으로 승격해야 한다."""


def _pattern(name: str) -> str:
    """이름을 원문에서 찾을 정규식. 글자 사이 띄어쓰기는 있든 없든 맞춘다."""
    letters = [ch for ch in name if ch not in _NAME_NOISE]
    return r"\s*".join(re.escape(ch) for ch in letters)


def check_names(text: str, names: list[str]) -> None:
    """뽑은 이름이 원문에 그대로 있는지 본다. 잘렸으면 NameTruncated.

    보는 것 두 가지다.
      1) 이름이 원문에 아예 없으면 지어낸 것이다
      2) 원문에서 이름 "앞" 에 한글이 더 붙어 있으면 잘린 것이다
         ("업체"를 뽑았는데 원문이 "박업체 과장님"이면 앞에 "박"이 있다)

    뒤는 보지 않는다. 한국어는 이름 뒤에 조사가 바로 붙는다("박업체 과장님이", "최동료는").
    뒤까지 막으면 멀쩡한 이름도 잘렸다고 하게 된다.

    원문에서 찾을 때는 띄어쓰기만 무시하고 위치는 원문 기준으로 본다. 공백을 지운 문자열로
    앞글자를 보면 "김해시청 앞에서 이업체" 처럼 앞 어절의 끝글자가 붙어 보여 잘못 걸린다.

    "나" 처럼 1인칭은 건너뛴다. 문장에서 "저는", "제가" 로 쓰이고 코드가 "나" 로 바꾼 값이라
    원문에 그대로 없을 수 있다 (llm.normalize_names).
    """
    for name in names:
        if name in ("나", ""):
            continue
        match = re.search(_pattern(name), text)
        if match is None:
            raise NameTruncated(f"원문에 없는 이름: {name!r}")
        before = text[match.start() - 1] if match.start() > 0 else ""
        if _is_hangul(before):
            raise NameTruncated(f"이름이 잘렸다: {name!r} (원문에는 더 긴 호칭이 있다)")


def _is_hangul(ch: str) -> bool:
    return bool(ch) and "가" <= ch <= "힣"
