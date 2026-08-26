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
#   PGC_SNAPSHOT_PROFILE  profile identity the snapshot claims (3b SN-5) — REQUIRED, no default.
#                         `1b` §11: a genesis proposal MUST name the profile it claims, and the
#                         profile is "supplied from outside the system being constituted". A default
#                         would have the assembler supply the one condition genesis takes from
#                         elsewhere. No profile is privileged (6a §11) and none is minimal by nature
#                         (6a §8), so there is no floor to default to.
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
#
# Discovery finds COMPILED OUTPUT, not domains — it cannot tell "not compiled yet" from "not part
# of this composition". A domain whose compile step was skipped would simply vanish from the
# assembly, and composition conformance would pass over the smaller set and report nothing wrong.
# So each candidate is a (domain_root, compiled_dir) pair: a domain root that declares a build
# STRUCTURE is SOURCE PRESENT, and source present without compiled output is a hard error naming
# the compile command. Absent source is genuinely not part of this composition and is skipped.
ROOTS=()
if [[ -n "${PGC_SOURCE_ROOTS:-}" ]]; then
  IFS=':' read -ra ROOTS <<< "$PGC_SOURCE_ROOTS"
else
  CANDIDATES=("$UMBRELLA/software_governance")
  for d in "$UMBRELLA"/conformance_workloads/workloads/*; do
    [[ -d "$d" ]] && CANDIDATES+=("$d")
  done
  for d in "$UMBRELLA"/business_domains/*; do
    [[ -d "$d" ]] && CANDIDATES+=("$d")
  done
  # Tool domains — repo-rooted rather than nested, one per tool. A tool domain declares
  # capabilities ABOUT a snapshot rather than within one; it composes like any other domain.
  CANDIDATES+=("$UMBRELLA/snapshot_inspector" "$UMBRELLA/transformation")

  UNCOMPILED=()
  for root in "${CANDIDATES[@]}"; do
    # Source present? A domain declares itself with a build STRUCTURE manifest. Layouts differ:
    # domains and tools keep it at registry/structures/, the governance surface one level deeper
    # at registry/structure/structures/ — so search rather than assume either.
    [[ -n "$(find "$root/registry" -maxdepth 3 -name 'STRUCTURE_BUILD_*_CONFIG_V*.md' -print -quit 2>/dev/null)" ]] || continue
    if [[ -d "$root/snapshot/compiled" ]]; then
      ROOTS+=("$root/snapshot/compiled")
    else
      UNCOMPILED+=("$root")
    fi
  done

  if [[ ${#UNCOMPILED[@]} -gt 0 ]]; then
    echo "Refusing to assemble — these domains declare source but have no compiled output:" >&2
    for root in "${UNCOMPILED[@]}"; do
      echo "  $root" >&2
      echo "    ./protocol_compiler/compile_domain.sh $root" >&2
    done
    echo >&2
    echo "Assembling without them would silently produce a smaller composition, and conformance" >&2
    echo "would pass over the reduced set. Compile them, or set PGC_SOURCE_ROOTS to assemble a" >&2
    echo "deliberately narrower composition." >&2
    exit 1
  fi
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

PROFILE="${PGC_SNAPSHOT_PROFILE:?a snapshot must NAME the profile it claims (1b §11, 3b SN-5).
  Set PGC_SNAPSHOT_PROFILE=<PROFILE_IDENTITY>, or pass --profile explicitly.
  There is no default: no profile is privileged (6a §11), and minimality is relative to a
  profile (6a §8) — so there is no minimal platform to default to.}"
exec "$PYTHON" -m assembler.cli assemble "${SRC_ARGS[@]}" --out "$OUT" --profile "$PROFILE"
