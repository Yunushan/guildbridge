#!/usr/bin/env bash
set -euo pipefail
python -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .[dev]
cp -n .env.example .env || true
echo "Done. Edit .env, then run: guildbridge providers"
