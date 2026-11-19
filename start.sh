#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

echo "===================================="
echo "          MP3 CLOUD"
echo "===================================="

# Check application source
if [[ ! -f app.py ]]; then
    echo "ERROR: app.py not found."
    exit 1
fi

# Check whether installation needs repair
NEEDS_SETUP=false

if ! command -v python3 >/dev/null 2>&1; then
    NEEDS_SETUP=true
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
    NEEDS_SETUP=true
fi

if [[ ! -x venv/bin/python ]]; then
    NEEDS_SETUP=true
fi

if [[ "$NEEDS_SETUP" == false ]]; then
    if ! venv/bin/python -c \
        "import fastapi, uvicorn, yt_dlp, multipart" \
        >/dev/null 2>&1; then
        NEEDS_SETUP=true
    fi
fi

# Automatically install missing dependencies
if [[ "$NEEDS_SETUP" == true ]]; then

    echo "Missing dependencies detected."
    echo "Running installation..."

    bash "$PROJECT_DIR/setup-linux.sh"
fi

# Final verification
if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "ERROR: FFmpeg is unavailable."
    exit 1
fi

echo ""
echo "Starting MP3 Cloud..."
echo "Open http://localhost:8000"
echo ""

exec "$PROJECT_DIR/venv/bin/python" "$PROJECT_DIR/app.py"
