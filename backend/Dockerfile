FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev ffmpeg curl ca-certificates && rm -rf /var/lib/apt/lists/*

ARG CODEX_VERSION=0.121.0
RUN arch="$(dpkg --print-architecture)" \
    && case "$arch" in \
        amd64) codex_arch="x86_64" ;; \
        arm64) codex_arch="aarch64" ;; \
        *) echo "Unsupported architecture: $arch" && exit 1 ;; \
    esac \
    && curl -fsSL "https://github.com/openai/codex/releases/download/rust-v${CODEX_VERSION}/codex-${codex_arch}-unknown-linux-musl.tar.gz" -o /tmp/codex.tgz \
    && tar -xzf /tmp/codex.tgz -C /usr/local/bin \
    && mv "/usr/local/bin/codex-${codex_arch}-unknown-linux-musl" /usr/local/bin/codex \
    && chmod +x /usr/local/bin/codex \
    && rm -f /tmp/codex.tgz

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
RUN uv pip install --system -e .

COPY . .

ENV CODEX_HOME=/codex-home

EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
