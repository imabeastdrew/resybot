FROM ubuntu:24.04
LABEL org.opencontainers.image.title="resbot-runner" \
      org.opencontainers.image.description="Resbot runner with Codex CLI" \
      org.opencontainers.image.source="https://github.com/your-org/resbot"

ENV DEBIAN_FRONTEND=noninteractive \
    UV_LINK_MODE=copy

RUN apt-get update && apt-get install -y --no-install-recommends \
    git rsync curl jq ca-certificates python3 python3-pip tar && \
    rm -rf /var/lib/apt/lists/*

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

WORKDIR /app

# Install Codex CLI release
ARG CODEX_TAG=rust-v0.50.0
ARG TARGETARCH
RUN set -eux; \
  case "${TARGETARCH}" in \
    amd64) COD_ARCH="x86_64-unknown-linux-gnu" ;; \
    arm64) COD_ARCH="aarch64-unknown-linux-gnu" ;; \
    *) echo "unsupported arch: ${TARGETARCH}"; exit 1 ;; \
  esac; \
  curl -fsSL -o /tmp/codex.tar.gz \
    "https://github.com/openai/codex/releases/download/${CODEX_TAG}/codex-${COD_ARCH}.tar.gz"; \
  tar -xzf /tmp/codex.tar.gz -C /usr/local/bin; \
  test -f "/usr/local/bin/codex-${COD_ARCH}"; \
  install -m 0755 "/usr/local/bin/codex-${COD_ARCH}" /usr/local/bin/codex; \
  codex --version

# OCI labels including codex version
LABEL codex.version=${CODEX_TAG}
# Project deps (shared)
COPY pyproject.toml ./pyproject.toml
RUN uv sync --no-dev

# Runner code
COPY runner ./runner
COPY codex ./codex

# Workspace directories
RUN mkdir -p /ws/base /ws/left /ws/right /ws/out

ENTRYPOINT ["uv", "run", "python3", "runner/main.py"]

