@echo off
chcp 65001 >nul
title Shorts-fabriek
cd /d "%~dp0"

where uv >nul 2>nul
if errorlevel 1 (
  echo [1/3] uv installeren ^(Python-pakketbeheer^)...
  powershell -NoProfile -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  set "PATH=%USERPROFILE%\.local\bin;%PATH%"
)

where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo [2/3] ffmpeg installeren via winget...
  winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
  set "PATH=%LOCALAPPDATA%\Microsoft\WinGet\Links;%PATH%"
)

if not exist .env copy .env.example .env >nul

echo [3/3] Pakketten bijwerken (yt-dlp altijd de nieuwste)...
uv sync --upgrade-package yt-dlp
if errorlevel 1 (
  echo Installatie mislukt. Zie de melding hierboven.
  pause
  exit /b 1
)

echo.
echo Shorts-fabriek draait op http://127.0.0.1:8765  (dit venster open laten; sluiten = stoppen)
uv run python -m app.main
pause
