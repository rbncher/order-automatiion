#!/usr/bin/env bash
set -euo pipefail
source ~/.ascot_env 2>/dev/null || true
cd "$(dirname "$0")"
source venv/bin/activate 2>/dev/null || true
python3 main.py
