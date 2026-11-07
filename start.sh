#!/bin/sh
cd "$(dirname "$0")" || exit 1
if [ -x .venv/bin/python ] && .venv/bin/python -c 'import sys' >/dev/null 2>&1; then
    exec .venv/bin/python start.py "$@"
fi
exec python3 start.py "$@"
