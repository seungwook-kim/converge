"""배포 진입점. 루트 Dockerfile 로 만든 이미지를 Modal 에서 ASGI 앱으로 띄운다. (SDD 10절, docs/deploy.md)

    python -m modal deploy modal_app.py

- 요청이 없으면 5분 뒤 0대로 내려간다. 다음 첫 요청은 콜드 스타트로 느리다.
- 키는 Modal 비밀값 `converge` 에 넣는다 (SDD 9절). Claude API 키와 MODEL_SMALL 은 `converge-claude`. 이 파일과 이미지에는 키가 없다.
- Dockerfile 의 CMD(uvicorn)는 쓰지 않는다. Modal 이 아래 함수가 돌려주는 앱을 직접 띄운다.
"""
import modal

app = modal.App("converge")

# 빌드 컨텍스트가 루트여야 skills/, mcp_server/ 가 같이 들어간다 (Dockerfile 주석). .dockerignore 를 따른다.
image = modal.Image.from_dockerfile("Dockerfile", context_dir=".").env({"PYTHONPATH": "/app"})


@app.function(
    image=image,
    # converge-claude 는 Claude API 키와 MODEL_SMALL·LARGE·VISION 만 담는다 (10-31). 뒤에 둔 비밀값이 같은 키를 덮는다 (Modal 문서).
    # CLI 에 비밀값 고치기가 없고 create --force 는 통째로 덮어써서, 기존 converge 를 건드리지 않고 따로 뒀다
    secrets=[modal.Secret.from_name("converge"), modal.Secret.from_name("converge-claude")],
    cpu=1.0,
    memory=1024,
    scaledown_window=300,
    timeout=120,
    max_containers=2,
    # 리전은 기본(us-east). 10-20 에 ap-northeast 로 옮겨 봤으나 같은 요청이 14.3초 그대로였다.
    # 느린 곳은 LLM 호출과 경로 계산이지 DB·API 왕복이 아니었다. 기본 외 리전은 단가가 높아 되돌렸다
)
@modal.concurrent(max_inputs=20)
@modal.asgi_app(label="converge-api")
def api():
    import os

    os.chdir("/app")
    from backend.app.main import app as fastapi_app

    return fastapi_app
