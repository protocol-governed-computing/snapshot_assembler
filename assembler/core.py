"""
core.py — PGC snapshot assembly.

Composes each domain's compiled projections (from the protocol compiler) into one
executable snapshot + a content-derived, manifest-pinned identity.

Contract: pgc_charter/doc/SNAPSHOT_ASSEMBLY_CONTRACT.md

Invariants enforced here:
  * The assembler INVENTS no per-domain identity — every hash is lifted verbatim from
    compiler-emitted metadata (tokenized/vocabulary metadata.json, trust attestation).
  * composite_hash is CONTENT-DERIVED over the identity view of domains[]; provenance and
    all timestamps are EXCLUDED. Same inputs → same composite.
  * {platform} is an ordinary one-member composition — no singleton branch.
  * Fail hard on any hash inconsistency or address-space collision. No silent skip.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from assembler import ASSEMBLER_VERSION, MANIFEST_VERSION

# The three projection kinds the runtime consumes, in their compiled + assembled dir names.
PROJECTIONS = ("tokenized", "trust", "vocabulary")


class AssemblyError(RuntimeError):
    """Raised on any assembly integrity failure. Fail hard — no fallback."""


@dataclass(frozen=True)
class DomainInput:
    """One domain located under a compiled source root."""
    domain: str
    source_root: Path          # the compiled/ root that contains this domain
    repo_root: Path | None     # nearest enclosing git repo (for provenance), or None


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def discover_domains(source_roots: list[Path]) -> list[DomainInput]:
    """
    Discover domains under each compiled source root via its tokenized/<domain>/ subdirs.

    A source root is a compiler `compiled/` directory (e.g. platform/snapshot/compiled).
    """
    found: dict[str, DomainInput] = {}
    for root in source_roots:
        tok = root / "tokenized"
        if not tok.is_dir():
            raise AssemblyError(f"Source root has no tokenized/ projection: {root}")
        for d in sorted(p.name for p in tok.iterdir() if p.is_dir()):
            if d in found:
                raise AssemblyError(
                    f"Domain {d!r} present in two source roots "
                    f"({found[d].source_root} and {root}) — ambiguous."
                )
            found[d] = DomainInput(domain=d, source_root=root, repo_root=_git_repo_root(root))
    if not found:
        raise AssemblyError(f"No domains discovered under: {[str(r) for r in source_roots]}")
    return [found[d] for d in sorted(found)]


# ---------------------------------------------------------------------------
# Per-domain identity (lifted verbatim from compiler output)
# ---------------------------------------------------------------------------

def _read_json(path: Path) -> dict:
    if not path.exists():
        raise AssemblyError(f"Required compiled projection file missing: {path}")
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _domain_identity(inp: DomainInput) -> dict[str, Any]:
    """
    Lift the domain's identity from compiler-emitted metadata and cross-check it.

    Fails hard if the compiler's own three hash statements disagree (tokenized vs trust vs
    vocabulary) — the assembler must not paper over an inconsistent compiled input.
    """
    root = inp.source_root
    tok_meta = _read_json(root / "tokenized"  / inp.domain / "metadata.json")
    voc_meta = _read_json(root / "vocabulary" / inp.domain / "metadata.json")
    trust    = _read_json(root / "trust"      / inp.domain / "structure_attestation.json")

    tok_hash = tok_meta.get("projection_hash", "")
    voc_hash = voc_meta.get("projection_hash", "")
    att_hash = trust.get("attestation_hash", "")
    graph_hash = tok_meta.get("graph_address_hash", "")

    # --- cross-check compiler's own statements (no invention, just verification) ---
    if not (tok_hash and voc_hash and att_hash):
        raise AssemblyError(f"[{inp.domain}] empty projection/attestation hash in compiled input.")
    if trust.get("tokenized_projection_hash") != tok_hash:
        raise AssemblyError(
            f"[{inp.domain}] trust.tokenized_projection_hash "
            f"{trust.get('tokenized_projection_hash')!r} != tokenized.projection_hash {tok_hash!r}"
        )
    if tok_meta.get("vocabulary_hash") != voc_hash:
        raise AssemblyError(
            f"[{inp.domain}] tokenized.vocabulary_hash {tok_meta.get('vocabulary_hash')!r} "
            f"!= vocabulary.projection_hash {voc_hash!r}"
        )

    return {
        "domain": inp.domain,
        "compiler_version": tok_meta.get("compiler_version", "unknown"),
        "graph_address_hash": graph_hash,
        "projections": {
            "tokenized":  {"path": f"tokenized/{inp.domain}",  "projection_hash": tok_hash},
            "vocabulary": {"path": f"vocabulary/{inp.domain}", "projection_hash": voc_hash},
            "trust":      {"path": f"trust/{inp.domain}",
                           "attestation_hash": att_hash,
                           "tokenized_projection_hash": tok_hash},
        },
    }


# ---------------------------------------------------------------------------
# Composite hash — content-derived, deterministic (identity view only)
# ---------------------------------------------------------------------------

def _identity_view(domains: list[dict]) -> list[dict]:
    """
    The identity view of domains[] — the ONLY input to the composite hash.

    Per contract: (domain, tokenized.projection_hash, vocabulary.projection_hash,
    trust.attestation_hash, graph_address_hash), domains sorted by name. Excludes
    provenance, timestamps, and file paths.
    """
    view = [
        {
            "domain": d["domain"],
            "tokenized_projection_hash":  d["projections"]["tokenized"]["projection_hash"],
            "vocabulary_projection_hash": d["projections"]["vocabulary"]["projection_hash"],
            "attestation_hash":           d["projections"]["trust"]["attestation_hash"],
            "graph_address_hash":         d["graph_address_hash"],
        }
        for d in domains
    ]
    return sorted(view, key=lambda e: e["domain"])


def compute_composite_hash(domains: list[dict]) -> str:
    """sha256 over canonical-JSON of the identity view. Deterministic; timestamp-free."""
    canonical = json.dumps(_identity_view(domains), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Cross-domain FQDN uniqueness (per-domain vocabularies are independent address namespaces)
# ---------------------------------------------------------------------------

def _check_address_space(domains: list[DomainInput]) -> None:
    """
    Composition safety check across domains.

    Integer addresses are DOMAIN-LOCAL: the runtime loads each domain's own
    `vocabulary/<domain>/{forward,reverse}.json` and resolves within it, so the same integer
    address legitimately recurs across independent domains (platform 0x0000 ≠ workload 0x0000).
    Cross-domain address reuse is therefore NOT a collision — it is the expected, isolated model.

    What WOULD break composition is the same FQDN owned by two domains (ambiguous ownership). That
    is what we guard here. True cross-domain *shared addressing* (reconciled composite forward/reverse
    maps) only becomes necessary when a domain references another domain's artifacts by shared
    address — deferred until the first cross-domain reference (see the assembly contract).
    """
    # Compiler-internal graph vocabulary is shared infrastructure present in every domain — not
    # domain-owned artifacts. Only artifact FQDNs carry ownership.
    system_ns = {"edge_kind", "node_kind", "outcome", "transition"}
    owner: dict[str, str] = {}  # fqdn -> domain
    for inp in domains:
        forward = _read_json(inp.source_root / "vocabulary" / inp.domain / "forward.json")
        for fqdn in forward.values():
            if "::" not in fqdn or fqdn.split("::", 1)[0] in system_ns:
                continue  # internal graph vocab — domain-local by nature, legitimately shared
            if fqdn in owner and owner[fqdn] != inp.domain:
                raise AssemblyError(
                    f"FQDN ownership conflict: {fqdn!r} present in both "
                    f"'{owner[fqdn]}' and '{inp.domain}'. A domain must not redeclare another's artifact."
                )
            owner.setdefault(fqdn, inp.domain)


# ---------------------------------------------------------------------------
# Provenance (metadata only — never enters the composite hash)
# ---------------------------------------------------------------------------

def _git_repo_root(path: Path) -> Path | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        )
        return Path(out.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def _git_commit(repo_root: Path | None) -> str:
    if repo_root is None:
        return "unknown"
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        )
        return out.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def _build_provenance(inputs: list[DomainInput], domains: list[dict]) -> dict[str, Any]:
    source_commits: dict[str, str] = {}
    for inp in inputs:
        if inp.repo_root is not None:
            source_commits[inp.repo_root.name] = _git_commit(inp.repo_root)
    compiler_versions = {d["domain"]: d["compiler_version"] for d in domains}
    return {
        "assembler_version": ASSEMBLER_VERSION,
        "assembled_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_commits": source_commits,
        "compiler_versions": compiler_versions,
    }


# ---------------------------------------------------------------------------
# Assemble
# ---------------------------------------------------------------------------

def assemble(source_roots: list[Path], out_root: Path) -> dict[str, Any]:
    """
    Assemble the domains under source_roots into out_root; write manifest.json.

    Returns the manifest dict. Regenerates the projection tree (build product); manifest.json
    is the committed identity.
    """
    inputs = discover_domains(source_roots)
    _check_address_space(inputs)

    # --- lift per-domain identity (with compiler cross-checks) ---
    domains = [_domain_identity(inp) for inp in inputs]

    # --- regenerate the assembled projection tree ---
    for kind in PROJECTIONS:
        dst_kind = out_root / kind
        if dst_kind.exists():
            shutil.rmtree(dst_kind)
    for inp in inputs:
        for kind in PROJECTIONS:
            src = inp.source_root / kind / inp.domain
            dst = out_root / kind / inp.domain
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, dst)

    # --- identity + provenance ---
    composite = compute_composite_hash(domains)
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "snapshot_id": composite,
        "composite_hash": composite,
        "domains": domains,
        "provenance": _build_provenance(inputs, domains),
    }

    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    return manifest


# ---------------------------------------------------------------------------
# Verify — the boot-time root-of-trust check, reusable by the runtime
# ---------------------------------------------------------------------------

def verify_snapshot(out_root: Path) -> dict[str, Any]:
    """
    Verify an assembled snapshot against its manifest (the root of trust).

    1. recompute composite_hash from domains[] identity view == manifest.composite_hash
    2. per domain: on-disk tokenized/vocabulary metadata.projection_hash == manifest == trust
    Returns the manifest on success; raises AssemblyError on any mismatch. No fallback.
    """
    manifest = _read_json(out_root / "manifest.json")
    domains = manifest.get("domains", [])

    recomputed = compute_composite_hash(domains)
    if recomputed != manifest.get("composite_hash"):
        raise AssemblyError(
            f"composite_hash mismatch: recomputed {recomputed!r} "
            f"!= manifest {manifest.get('composite_hash')!r} (domain-set tamper?)"
        )

    for d in domains:
        dom = d["domain"]
        tok_meta = _read_json(out_root / "tokenized"  / dom / "metadata.json")
        voc_meta = _read_json(out_root / "vocabulary" / dom / "metadata.json")
        trust    = _read_json(out_root / "trust"      / dom / "structure_attestation.json")
        man_tok = d["projections"]["tokenized"]["projection_hash"]
        man_voc = d["projections"]["vocabulary"]["projection_hash"]
        if tok_meta.get("projection_hash") != man_tok:
            raise AssemblyError(f"[{dom}] on-disk tokenized hash != manifest.")
        if trust.get("tokenized_projection_hash") != man_tok:
            raise AssemblyError(f"[{dom}] trust tokenized hash != manifest.")
        if voc_meta.get("projection_hash") != man_voc:
            raise AssemblyError(f"[{dom}] on-disk vocabulary hash != manifest.")

    return manifest
