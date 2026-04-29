# syntax=docker/dockerfile:1

FROM node:22-bookworm-slim AS frontend

WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
ARG VITE_API_BASE=
ENV VITE_API_BASE=${VITE_API_BASE}
RUN npm run build


FROM python:3.11-slim AS app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LOCAL_ASSISTANT_CONFIG=/config/config.yaml \
    LOCAL_ASSISTANT_FRONTEND_DIST=/app/frontend/dist

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        espeak-ng \
        ffmpeg \
        libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-ml.txt ./
ARG INSTALL_ML=true
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
RUN python -m pip install --upgrade pip \
    && python -m pip install --no-cache-dir -r requirements.txt \
    && if [ "${INSTALL_ML}" = "true" ]; then \
        python -m pip install --no-cache-dir torch --index-url "${TORCH_INDEX_URL}" \
        && python -m pip install --no-cache-dir -r requirements-ml.txt; \
    fi

COPY local_assistant ./local_assistant
COPY config.docker.yaml ./config.docker.yaml
COPY docker-entrypoint.sh /usr/local/bin/local-assistant-entrypoint
COPY --from=frontend /app/frontend/dist ./frontend/dist

RUN chmod +x /usr/local/bin/local-assistant-entrypoint \
    && mkdir -p /config /data

VOLUME ["/config", "/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5).read()" || exit 1

ENTRYPOINT ["local-assistant-entrypoint"]
CMD ["python", "-m", "local_assistant.server"]
