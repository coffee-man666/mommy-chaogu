#!/bin/sh

set -eu

DATA_DIR=/app/data
SEED_DIR=/app/data-seed
EXPECTED_USER=mommy

if [ -n "${RAILWAY_VOLUME_MOUNT_PATH:-}" ] \
    && [ "$RAILWAY_VOLUME_MOUNT_PATH" != "$DATA_DIR" ]; then
    echo "error: Railway volume must be mounted at $DATA_DIR (got $RAILWAY_VOLUME_MOUNT_PATH)" >&2
    exit 64
fi

seed_data() {
    if [ -d "$SEED_DIR" ]; then
        cp -R "$SEED_DIR"/. "$DATA_DIR"/
    fi
}

if [ "$(id -u)" = "0" ]; then
    mkdir -p "$DATA_DIR"
    seed_data
    chown -R "$EXPECTED_USER:$EXPECTED_USER" "$DATA_DIR"
    exec gosu "$EXPECTED_USER" "$@"
fi

mkdir -p "$DATA_DIR"
if [ ! -w "$DATA_DIR" ]; then
    echo "error: $DATA_DIR is not writable; on Railway set RAILWAY_RUN_UID=0" >&2
    exit 73
fi

seed_data
exec "$@"
