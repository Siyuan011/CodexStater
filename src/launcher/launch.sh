#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
case "$(uname -s)" in
  Linux|Darwin) ;;
  *) printf '%s\n' 'Bash supports Linux/macOS only. On Windows, use run.cmd.' >&2; exit 2 ;;
esac
python="${STATER_PYTHON:-python3}"
if ! command -v "$python" >/dev/null 2>&1; then
  printf '%s\n' 'Python 3.9+ is required. Set STATER_PYTHON to its executable.' >&2; exit 1
fi
"$python" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' || {
  printf '%s\n' 'Python 3.9+ is required.' >&2; exit 1;
}
action="${1:-Run}"
if (($#)); then shift; fi
exec "$python" "$root/src/launcher/launch.py" "$action" "$@"
