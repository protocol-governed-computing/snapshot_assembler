"""
cli.py — PGC snapshot assembler CLI.

    assemble   — compose compiled projections into the assembled snapshot + manifest,
                 then run Composition Conformance over the result
    verify     — verify an assembled snapshot against its manifest (root of trust)
    conform    — run Composition Conformance alone against an assembled snapshot

Assembly and Composition Conformance are distinct lifecycle phases, not one step: the assembler
composes and proves identity; the conformance phase proves governance properties of the
composition. `assemble` runs both because an unproven snapshot should never be left on disk
looking finished — but each is separately invocable, and neither implements the other.

Paths are explicit or resolved from documented sibling defaults. No cwd guessing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from assembler import conformance, core


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="snapshot_assembler", description="PGC snapshot assembler")
    subs = p.add_subparsers(dest="command", required=True)

    a = subs.add_parser("assemble", help="Compose compiled projections into the assembled snapshot")
    a.add_argument(
        "--source", action="append", required=True, metavar="COMPILED_ROOT",
        help="A compiler compiled/ root (repeatable). e.g. .../software_governance/snapshot/compiled",
    )
    a.add_argument(
        "--out", required=True, metavar="SNAPSHOT_DIR",
        help="Assembled snapshot output dir (the product). e.g. .../protocol-governed-computing/snapshot",
    )

    v = subs.add_parser("verify", help="Verify an assembled snapshot against its manifest")
    v.add_argument("--out", required=True, metavar="SNAPSHOT_DIR", help="Assembled snapshot dir to verify")

    c = subs.add_parser("conform", help="Run Composition Conformance against an assembled snapshot")
    c.add_argument("--out", required=True, metavar="SNAPSHOT_DIR", help="Assembled snapshot dir to check")

    return p


def _fatal(msg: str) -> None:
    print(f"[assembler] Error: {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    args = _build_parser().parse_args()

    if args.command == "assemble":
        source_roots = [Path(s).resolve() for s in args.source]
        out_root = Path(args.out).resolve()
        for s in source_roots:
            if not s.is_dir():
                _fatal(f"source root is not a directory: {s}")
        try:
            manifest = core.assemble(source_roots, out_root)
            core.verify_snapshot(out_root)  # round-trip self-check
        except core.AssemblyError as exc:
            _fatal(str(exc))

        doms = [d["domain"] for d in manifest["domains"]]
        print(f"[assembler] Assembled {len(doms)} domain(s): {', '.join(doms)}")
        print(f"[assembler] snapshot_id: {manifest['snapshot_id']}")
        print(f"[assembler] out:         {out_root}")
        print(f"[assembler] manifest:    {out_root / 'manifest.json'}")
        print("[assembler] round-trip verify: OK")

        # Composition Conformance — a separate phase over the composed snapshot.
        try:
            ev = conformance.check_composition(out_root)
        except conformance.ConformanceError as exc:
            _fatal(str(exc))
        print(f"[conformance] composition: {ev['status']} "
              f"({ev['rules_evaluated']} rule(s) over {ev['artifacts_examined']} artifacts)")

    elif args.command == "verify":
        out_root = Path(args.out).resolve()
        try:
            manifest = core.verify_snapshot(out_root)
        except core.AssemblyError as exc:
            _fatal(str(exc))
        print(f"[assembler] VERIFIED  snapshot_id={manifest['snapshot_id']}")
        print(f"[assembler] domains: {json.dumps([d['domain'] for d in manifest['domains']])}")

    elif args.command == "conform":
        out_root = Path(args.out).resolve()
        try:
            ev = conformance.check_composition(out_root)
        except conformance.ConformanceError as exc:
            _fatal(str(exc))
        print(f"[conformance] {ev['status']}  snapshot_id={ev['snapshot_id']}")
        for f in ev["findings"]:
            print(f"  {f['status']:<7} {f['invariant']:<58} {f['message']}")


if __name__ == "__main__":
    main()
