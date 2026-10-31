FROM python:3.12-slim
WORKDIR /app/backend
RUN pip install --no-cache-dir --timeout=60 --retries=1 uv==0.11.15
COPY backend/pyproject.toml backend/uv.lock ./
COPY backend/src ./src
COPY backend/migrations ./migrations
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev
ENV PATH="/app/backend/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1
CMD ["uvicorn", "leornian.entrypoints.api:app", "--host", "0.0.0.0", "--port", "8088"]
