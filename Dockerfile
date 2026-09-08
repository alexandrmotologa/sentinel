# Multi-stage minimal Dockerfile for Sentinel
FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && \
    apt-get install --no-install-recommends -y build-essential && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY sentinel/ sentinel/

RUN pip install --no-cache-dir build && \
    python -m build --wheel

FROM python:3.12-slim AS final

LABEL maintainer="Alexandr Motologa"
LABEL description="Sentinel: 24/7 Lightweight Async Uptime & Health Watcher"

WORKDIR /app

# Create unprivileged system user
RUN groupadd -g 10001 sentinel && \
    useradd -u 10001 -g sentinel -s /bin/sh -M sentinel

# Install the wheel built in builder stage
COPY --from=builder /build/dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && \
    rm -rf /tmp/*.whl

# Configure runtime directories and permissions
RUN mkdir -p /etc/sentinel /var/log/sentinel /tmp && \
    chown -R sentinel:sentinel /app /etc/sentinel /var/log/sentinel /tmp

USER sentinel

ENV PYTHONUNBUFFERED=1
ENV SENTINEL_HEARTBEAT_PATH=/tmp/sentinel.heartbeat

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD sentinel healthcheck --max-age 120 || exit 1

ENTRYPOINT ["sentinel", "run", "/etc/sentinel/sites.yaml"]
