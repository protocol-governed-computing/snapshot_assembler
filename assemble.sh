#!/usr/bin/env bash
#
# PGC snapshot assembler runner — no PYTHONPATH / env fuss.
#
# Usage:
#   ./assemble.sh                       # AUTO-DISCOVER: platform + every compiled reference workload
#   ./assemble.sh --source A --out B    # explicit
#
# Env overrides:
#   PGC_SOURCE_ROOTS   colon-separated compiled/ roots (overrides auto-discovery)
#   PGC_SNAPSHOT_OUT   assembled snapshot dir          (default: ../snapshot)
#   PYTHON             (default: python)
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"     # snapshot_assembler/ = the `assembler` package root
UMBRELLA="$(cd "$SCRIPT_DIR/.." && pwd)"                       # protocol-governed-computing/
PYTHON="${PYTHON:-python}"

export PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}"

if [[ $# -gt 0 ]]; then
  exec "$PYTHON" -m assembler.cli assemble "$@"
fi

# Auto-discover the compiled domains that make up the universe: the platform surface plus every
# reference workload that has been compiled. Set PGC_SOURCE_ROOTS to override.
ROOTS=()
if [[ -n "${PGC_SOURCE_ROOTS:-}" ]]; then
  IFS=':' read -ra ROOTS <<< "$PGC_SOURCE_ROOTS"
else
  [[ -d "$UMBRELLA/platform/snapshot/compiled" ]] && ROOTS+=("$UMBRELLA/platform/snapshot/compiled")
  for d in "$UMBRELLA"/platform/reference_workloads/*/snapshot/compiled; do
    [[ -d "$d" ]] && ROOTS+=("$d")
  done
fi

if [[ ${#ROOTS[@]} -eq 0 ]]; then
  echo "No compiled domains found. Run ./protocol_compiler/compile.sh first." >&2
  exit 1
fi

OUT="${PGC_SNAPSHOT_OUT:-$UMBRELLA/snapshot}"

SRC_ARGS=()
for r in "${ROOTS[@]}"; do
  SRC_ARGS+=(--source "$r")
done

echo "PGC assemble"
echo "  sources :"
for r in "${ROOTS[@]}"; do echo "    - $r"; done
echo "  out     : $OUT"
echo

exec "$PYTHON" -m assembler.cli assemble "${SRC_ARGS[@]}" --out "$OUT"
