#!/usr/bin/env bash
# Windows Git Bash entry point. Arguments use the PowerShell launcher syntax.
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
case "$(uname -s)" in
  MINGW*|MSYS*) ;;
  *) printf '%s\n' 'These launchers require Windows Git Bash and Windows Task Scheduler.' 'Linux/macOS scheduling is not implemented.' >&2; exit 2 ;;
esac
if ! command -v powershell.exe >/dev/null 2>&1; then
  printf '%s\n' 'powershell.exe was not found.' >&2
  exit 1
fi
action="${1:-Run}"
if (($#)); then shift; fi
# Convert only known path arguments, preserving spaces and all other values.
args=()
while (($#)); do
  case "$1" in
    -Config|-config|-CodexRoot|-codexroot)
      flag="$1"; shift
      if (($# == 0)); then printf 'Missing value for %s\n' "$flag" >&2; exit 2; fi
      value="$1"
      if [[ "$value" == /* ]]; then value="$(cygpath -w -- "$value")"; fi
      args+=("$flag" "$value") ;;
    *) args+=("$1") ;;
  esac
  shift
done
launcher="$(cygpath -w -- "$root/src/launcher/launch.ps1")"
# Prevent MSYS from reinterpreting Windows parameters and paths.
export MSYS2_ARG_CONV_EXCL='*'
exec powershell.exe -NoProfile -ExecutionPolicy Bypass -STA -File "$launcher" -Action "$action" "${args[@]}"
