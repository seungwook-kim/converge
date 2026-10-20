# 백엔드 이미지. FastAPI 에 /mcp 를 마운트해 한 프로세스로 띄운다.
# Vercel 은 컨테이너를 돌리지 않는다. 배포는 modal_app.py 가 이 파일로 이미지를 만든다 (docs/deploy.md).
FROM python:3.12-slim

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
# skills/ 는 규칙값 문서(domain/rules.py 가 읽는다), mcp_server/ 는 /mcp 마운트.
# 빌드 컨텍스트가 루트인 이유가 이 둘이다 (SDD 1절).
COPY skills/ ./skills/
COPY mcp_server/ ./mcp_server/

# 슬롯 추출은 기본으로 호스팅 모델을 쓴다 (.env 의 MODEL_SMALL). 그래서 모델 가중치를 넣지 않는다.
# 로컬 GGUF 로 돌리려면 아래처럼 빌드한다. 이미지가 1.3GiB 커지고 llama-cpp-python 이 필요하다.
#   docker build --build-arg WITH_LOCAL_MODEL=1 -t converge .
ARG WITH_LOCAL_MODEL=0
ARG HF_REPO=kimseunguk/converge-slot-extractor
ARG GGUF_FILE=kanana_2.1b-Q4_K_M.gguf
RUN if [ "$WITH_LOCAL_MODEL" = "1" ]; then         pip install --no-cache-dir huggingface_hub llama-cpp-python &&         python -c "from huggingface_hub import hf_hub_download; hf_hub_download(repo_id='${HF_REPO}', filename='${GGUF_FILE}', local_dir='/app/backend/app/models'); hf_hub_download(repo_id='${HF_REPO}', filename='${GGUF_FILE%.gguf}.prompt.json', local_dir='/app/backend/app/models'); hf_hub_download(repo_id='${HF_REPO}', filename='grammar.gbnf', local_dir='/app/backend/app/models')" &&         pip uninstall -y huggingface_hub;     fi

# 컨테이너 호스트가 PORT 로 포트를 알려 주면 그걸 쓴다. 로컬은 8000. Modal 은 CMD 를 쓰지 않는다.
ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT}"]
