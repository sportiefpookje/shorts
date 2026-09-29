#!/usr/bin/env bash
# Shorts-fabriek starten op macOS/Linux
set -e
cd "$(dirname "$0")"
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
command -v ffmpeg >/dev/null || { echo "Installeer eerst ffmpeg (bijv. 'brew install ffmpeg' of 'sudo apt install ffmpeg')"; exit 1; }
[ -f .env ] || cp .env.example .env
uv sync --upgrade-package yt-dlp
echo "Shorts-fabriek draait op http://127.0.0.1:8765"
exec uv run python -m app.main
