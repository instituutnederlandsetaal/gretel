#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"
uv run --locked python -m flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics
