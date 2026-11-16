#!/usr/bin/env bash
# Run the tests (arguments go to pytest). Same local-disk environment as run.sh.
set -euo pipefail
cd "$(dirname "$0")"
export UV_PROJECT_ENVIRONMENT="${UV_PROJECT_ENVIRONMENT:-$HOME/.local/share/alcove/venv}"
export UV_LINK_MODE=copy
exec uv run pytest "$@"
