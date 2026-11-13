#!/bin/zsh
set -e
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
cd -- "${0:A:h}"
if [[ -x .venv/bin/python ]]; then
  PYTHON=.venv/bin/python
elif command -v python3 >/dev/null; then
  PYTHON=python3
else
  echo 'Python 3.10+ is required: https://www.python.org/downloads/'
  read -r '?Press Enter to close.'
  exit 1
fi
if ! "$PYTHON" -B scripts/check_dependencies.py --runtime-only; then
  read -r '?Resolve the missing requirements, then restart. Press Enter to close.'
  exit 1
fi
if [[ ! -x .venv/bin/python ]]; then
  printf 'Create a local Python virtual environment? [y/N] '
  read -r answer
  [[ "$answer" == [yY] ]] || exit 0
  "$PYTHON" -m venv .venv
fi
if ! .venv/bin/python -B scripts/check_dependencies.py --packages-only; then
  printf 'Install the exact listed dependency versions from PyPI into .venv? [y/N] '
  read -r answer
  [[ "$answer" == [yY] ]] || exit 0
  .venv/bin/python -m pip install -r scripts/requirements-docx.lock
fi
.venv/bin/python -B scripts/check_dependencies.py
.venv/bin/python -B scripts/app.py
