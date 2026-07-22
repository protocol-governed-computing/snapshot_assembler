#!/usr/bin/env bash
#
# PGC snapshot assembler runner — no PYTHONPATH / env fuss.
#
# Usage:
#   ./assemble.sh                       # assemble sibling platform compiled/ -> sibling snapshot/
#   ./assemble.sh --source A --out B    # explicit
#
# Env overrides:
#   PGC_SOURCE_ROOTS   colon-separated compiled/ roots (default: ../platform/snapshot/compiled)
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

SOURCE_ROOTS="${PGC_SOURCE_ROOTS:-$UMBRELLA/platform/snapshot/compiled}"
OUT="${PGC_SNAPSHOT_OUT:-$UMBRELLA/snapshot}"

SRC_ARGS=()
IFS=':' read -ra ROOTS <<< "$SOURCE_ROOTS"
for r in "${ROOTS[@]}"; do
  SRC_ARGS+=(--source "$r")
done

echo "PGC assemble"
echo "  sources : $SOURCE_ROOTS"
echo "  out     : $OUT"
echo

exec "$PYTHON" -m assembler.cli assemble "${SRC_ARGS[@]}" --out "$OUT"
