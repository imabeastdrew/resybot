FROM python:3.11-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

WORKDIR /app

# Build wheel
COPY pyproject.toml ./pyproject.toml
COPY src ./src
RUN uv build

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates docker.io && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install wheel produced by builder
COPY --from=builder /app/dist/*.whl /tmp/dist/
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"
RUN pip install --no-cache-dir /tmp/dist/*.whl

EXPOSE 8000

CMD ["uvicorn", "resbot.server.app.main:app", "--host", "0.0.0.0", "--port", "8000"]

