#!/usr/bin/env sh
set -eu

CONFIG_PATH="${LOCAL_ASSISTANT_CONFIG:-/config/config.yaml}"
CONFIG_DIR="$(dirname "${CONFIG_PATH}")"

mkdir -p "${CONFIG_DIR}" /data

exec "$@"
