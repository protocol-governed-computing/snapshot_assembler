#!/usr/bin/env bash
#
# PGC snapshot assembler runner — no PYTHONPATH / env fuss.
#
# Usage:
#   ./assemble.sh                       # AUTO-DISCOVER: governance + every compiled workload
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

# Auto-discover the compiled domains that make up the PNP: the software_governance surface, every
# compiled conformance workload, every compiled business domain, and every compiled TOOL domain.
# A tool domain declares capabilities ABOUT a snapshot rather than within one; it composes exactly
# like any other domain. Set PGC_SOURCE_ROOTS to override.
ROOTS=()
if [[ -n "${PGC_SOURCE_ROOTS:-}" ]]; then
  IFS=':' read -ra ROOTS <<< "$PGC_SOURCE_ROOTS"
else
  [[ -d "$UMBRELLA/software_governance/snapshot/compiled" ]] && ROOTS+=("$UMBRELLA/software_governance/snapshot/compiled")
  for d in "$UMBRELLA"/conformance_workloads/workloads/*/snapshot/compiled; do
    [[ -d "$d" ]] && ROOTS+=("$d")
  done
  for d in "$UMBRELLA"/business_domains/*/snapshot/compiled; do
    [[ -d "$d" ]] && ROOTS+=("$d")
  done
  # Tool domains — repo-rooted rather than nested, one per tool.
  [[ -d "$UMBRELLA/snapshot_inspector/snapshot/compiled" ]] && ROOTS+=("$UMBRELLA/snapshot_inspector/snapshot/compiled")
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
