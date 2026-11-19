#!/usr/bin/env bash

set -Eeuo pipefail

# Always work from the project directory
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

echo "===================================="
echo "       MP3 CLOUD INSTALLER"
echo "===================================="

# Check operating system
if [[ ! -f /etc/os-release ]]; then
    echo "ERROR: Unsupported Linux distribution."
    exit 1
fi

source /etc/os-release

echo "Detected OS: ${PRETTY_NAME:-Linux}"

# Run commands with appropriate privileges
run_privileged() {
    if [[ "$EUID" -eq 0 ]]; then
        "$@"
    elif command -v sudo >/dev/null 2>&1; then
        sudo "$@"
    else
        echo "ERROR: sudo or root access is required."
        exit 1
    fi
}

# Install system dependencies
install_system_dependencies() {

    echo ""
    echo "[1/5] Checking system dependencies..."

    if command -v apt-get >/dev/null 2>&1; then

        run_privileged apt-get update

        run_privileged apt-get install -y \
            python3 \
            python3-venv \
            python3-pip \
            ffmpeg \
            ca-certificates

    elif command -v dnf >/dev/null 2>&1; then

        run_privileged dnf install -y \
            python3 \
            python3-pip \
            ffmpeg \
            ca-certificates

    elif command -v pacman >/dev/null 2>&1; then

        run_privileged pacman -Sy --needed --noconfirm \
            python \
            python-pip \
            ffmpeg \
            ca-certificates

    elif command -v zypper >/dev/null 2>&1; then

        run_privileged zypper --non-interactive install \
            python3 \
            python3-pip \
            ffmpeg \
            ca-certificates

    else
        echo "ERROR: Unsupported package manager."
        echo "Install Python 3, pip and FFmpeg manually."
        exit 1
    fi
}

# Verify Python
check_python() {

    echo ""
    echo "[2/5] Checking Python..."

    if ! command -v python3 >/dev/null 2>&1; then
        echo "ERROR: Python installation failed."
        exit 1
    fi

    python3 --version

    if ! python3 -m venv --help >/dev/null 2>&1; then
        echo "ERROR: Python venv module is unavailable."
        echo "Install your distribution's python3-venv package."
        exit 1
    fi
}

# Verify FFmpeg
check_ffmpeg() {

    echo ""
    echo "[3/5] Checking FFmpeg..."

    if ! command -v ffmpeg >/dev/null 2>&1; then
        echo "ERROR: FFmpeg installation failed."
        echo "Check whether your distribution provides FFmpeg."
        exit 1
    fi

    ffmpeg -version | head -n 1
}

# Create virtual environment
setup_venv() {

    echo ""
    echo "[4/5] Setting up Python environment..."

    if [[ ! -f requirements.txt ]]; then
        echo "ERROR: requirements.txt not found."
        exit 1
    fi

    if [[ ! -x venv/bin/python ]]; then
        python3 -m venv venv
    fi

    venv/bin/python -m pip install --upgrade pip

    venv/bin/python -m pip install -r requirements.txt
}

# Verify application dependencies
verify_installation() {

    echo ""
    echo "[5/5] Verifying installation..."

    venv/bin/python -c "
import fastapi
import uvicorn
import yt_dlp
import multipart
print('Python dependencies verified successfully.')
"

    if [[ ! -f app.py ]]; then
        echo "ERROR: app.py not found."
        exit 1
    fi
}

# Execute installation
install_system_dependencies
check_python
check_ffmpeg
setup_venv
verify_installation

echo ""
echo "===================================="
echo "     INSTALLATION SUCCESSFUL"
echo "===================================="
echo ""
echo "To start MP3 Cloud, run:"
echo "./start-linux.sh"
echo ""
