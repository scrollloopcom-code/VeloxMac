#!/usr/bin/env bash
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

# Automatically open macOS browser
(sleep 1.2 && open http://127.0.0.1:8899) &

echo "==========================================================="
echo "⚡️ LoopCatch by Scroll Loop — Next-Gen Media & IDM Downloader"
echo "🌐 UI Dashboard: http://127.0.0.1:8899"
echo "📁 Download Location: ~/Downloads/LoopCatchDownloads"
echo "==========================================================="

exec uvicorn app:app --host 127.0.0.1 --port 8899
