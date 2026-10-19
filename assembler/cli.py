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
import os
import sys
from pathlib import Path

from assembler import conformance, core, signing


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
    a.add_argument(
        "--profile", default=os.environ.get("PGC_SNAPSHOT_PROFILE", ""), metavar="PROFILE_IDENTITY",
        help="The profile identity this snapshot claims (3b SN-5). Required; a snapshot that claims "
             "none cannot have clause 4 of 3b §7 evaluated about it.",
    )

    a.add_argument(
        "--signing-key", metavar="PEM", default=None,
        help="Private key authenticating the sealed snapshot's identity. The build machine "
             "holds this and no node that executes a workflow does: a node able to sign can "
             "mint a snapshot its peers would accept.")

    v = subs.add_parser("verify", help="Verify an assembled snapshot against its manifest")
    v.add_argument("--out", required=True, metavar="SNAPSHOT_DIR", help="Assembled snapshot dir to verify")

    k = subs.add_parser("keygen", help="Mint a signing keypair for a snapshot trust root")
    k.add_argument("--private", required=True, metavar="PEM", help="Where to write the private half")
    k.add_argument("--public", required=True, metavar="PEM", help="Where to write the public half")

    c = subs.add_parser("conform", help="Run Composition Conformance against an assembled snapshot")
    c.add_argument("--out", required=True, metavar="SNAPSHOT_DIR", help="Assembled snapshot dir to check")

    return p


def _fatal(msg: str) -> None:
    print(f"[assembler] Error: {msg}", file=sys.stderr)
    sys.exit(1)


def _report_authentication(out_root: Path, snapshot_id: str) -> None:
    """Report whether the snapshot is authenticated, and refuse where this party requires it.

    A party holding a trust root is a party that requires one. Absent `PGC_TRUST_ROOT_PUBKEY`
    this reports what it finds and refuses nothing: an unsigned snapshot is well-formed, and a
    platform whose profile does not select signing must still verify. Holding an anchor is the
    opt-in, and it lives outside the artifact being authenticated — which is also why the key
    is read from here and never from the signature record.
    """
    anchor = os.environ.get("PGC_TRUST_ROOT_PUBKEY")
    try:
        record = signing.read_signature(out_root)
    except signing.SignatureMalformed as exc:
        _fatal(f"snapshot authentication: {exc}")

    if not anchor:
        state = (f"present, unchecked (signed under key {record.get('key_id', '?')})"
                 if record else "absent")
        print(f"[signing] {state} — set PGC_TRUST_ROOT_PUBKEY to require and check one")
        return

    if record is None:
        _fatal("snapshot authentication: this party anchors a trust root and the snapshot "
               "carries no signature. An unsigned snapshot is not one this party accepts.")
    try:
        key = signing.verify_identity(snapshot_id, record, Path(anchor))
    except (signing.SignatureError, signing.SigningUnavailable, OSError) as exc:
        _fatal(f"snapshot authentication: {type(exc).__name__}: {exc}")
    print(f"[signing] AUTHENTICATED under trust root {key}")


def main() -> None:
    args = _build_parser().parse_args()

    if args.command == "assemble":
        source_roots = [Path(s).resolve() for s in args.source]
        out_root = Path(args.out).resolve()
        for s in source_roots:
            if not s.is_dir():
                _fatal(f"source root is not a directory: {s}")
        try:
            manifest = core.assemble(source_roots, out_root, args.profile)
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

        # Signing follows sealing and never precedes it: what is authenticated is the identity
        # the seal produced. A snapshot is sealed whether or not anyone signs it; a signature
        # says who vouches for the one that was sealed.
        if args.signing_key:
            try:
                record = signing.sign_identity(manifest["snapshot_id"], Path(args.signing_key))
                path = signing.write_signature(out_root, record)
            except (signing.SigningUnavailable, OSError, ValueError) as exc:
                _fatal(f"signing failed: {exc}")
            print(f"[signing] signed under key {record['key_id']} -> {path}")

    elif args.command == "verify":
        out_root = Path(args.out).resolve()
        try:
            manifest = core.verify_snapshot(out_root)
        except core.AssemblyError as exc:
            _fatal(str(exc))
        print(f"[assembler] VERIFIED  snapshot_id={manifest['snapshot_id']}")
        print(f"[assembler] domains: {json.dumps([d['domain'] for d in manifest['domains']])}")
        _report_authentication(out_root, manifest["snapshot_id"])

    elif args.command == "keygen":
        try:
            private_pem, public_pem = signing.generate_keypair()
        except signing.SigningUnavailable as exc:
            _fatal(str(exc))
        priv, pub = Path(args.private), Path(args.public)
        priv.write_bytes(private_pem)
        priv.chmod(0o600)
        pub.write_bytes(public_pem)
        print(f"[keygen] key_id:  {signing.key_id_from_public_pem(public_pem)}")
        print(f"[keygen] private: {priv}  (build machine only — never on an executing node)")
        print(f"[keygen] public:  {pub}   (each node holds this, from outside the snapshot)")

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
