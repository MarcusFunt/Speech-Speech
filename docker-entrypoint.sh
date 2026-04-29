#!/usr/bin/env sh
set -eu

CONFIG_PATH="${LOCAL_ASSISTANT_CONFIG:-/config/config.yaml}"
CONFIG_DIR="$(dirname "${CONFIG_PATH}")"

mkdir -p "${CONFIG_DIR}" /data

if [ ! -f "${CONFIG_PATH}" ]; then
    cp /app/config.docker.yaml "${CONFIG_PATH}"
fi

exec "$@"
