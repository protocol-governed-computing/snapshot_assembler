"""
core.py — PGC snapshot assembly.

Composes each domain's compiled projections (from the protocol compiler) into one
executable snapshot + a content-derived, manifest-pinned identity.

Contract: snapshot_assembler/doc/SNAPSHOT_ASSEMBLY_CONTRACT.md

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


def _canonical_meta_path(root: Path, domain: str) -> Path:
    """`canonical/metadata.json`, in either source shape.

    The compiler emits canonical flat (`canonical/…` by artifact type) while tokenized, vocabulary
    and trust are domain-scoped; assembly re-homes canonical under `canonical/<domain>`. Both shapes
    are read here so the same hash can be lifted before and verified after assembly.
    """
    scoped = root / "canonical" / domain / "metadata.json"
    return scoped if scoped.exists() else root / "canonical" / "metadata.json"


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
    # Canonical is emitted flat by the compiler; every other projection is domain-scoped.
    can_meta = _read_json(_canonical_meta_path(root, inp.domain))

    tok_hash = tok_meta.get("projection_hash", "")
    voc_hash = voc_meta.get("projection_hash", "")
    att_hash = trust.get("attestation_hash", "")
    can_hash = can_meta.get("projection_hash", "")
    graph_hash = tok_meta.get("graph_address_hash", "")

    # --- cross-check compiler's own statements (no invention, just verification) ---
    if not (tok_hash and voc_hash and att_hash and can_hash):
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
            "canonical":  {"path": f"canonical/{inp.domain}",  "projection_hash": can_hash},
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
    canonical.projection_hash, trust.attestation_hash, graph_address_hash), domains sorted
    by name. Excludes provenance, timestamps, and file paths.

    `canonical` is here because the other four are all graph-derived, and STRUCTURE artifacts
    never enter the semantic graph — they are read as build configuration and materialized. Without
    canonical, a STRUCTURE artifact could change inside a sealed snapshot while the identity stayed
    byte-identical and every integrity check still passed. STRUCTURE is the configuration authority
    for the whole system, so that is the one class of artifact the identity could least afford to
    miss. The hash is the compiler's own statement, lifted verbatim like the rest.
    """
    view = [
        {
            "domain": d["domain"],
            "tokenized_projection_hash":  d["projections"]["tokenized"]["projection_hash"],
            "vocabulary_projection_hash": d["projections"]["vocabulary"]["projection_hash"],
            "canonical_projection_hash":  d["projections"]["canonical"]["projection_hash"],
            "attestation_hash":           d["projections"]["trust"]["attestation_hash"],
            "graph_address_hash":         d["graph_address_hash"],
        }
        for d in domains
    ]
    return sorted(view, key=lambda e: e["domain"])


# Written into the snapshot tree AFTER sealing, and therefore not constituents of what was sealed.
#
# `3b` §3: sealing constitutes the snapshot, and a representation that changed after sealing was not
# sealed. A conformance result names the snapshot_id, so it cannot exist before the identity does —
# it is a determination ABOUT the snapshot, in the sense `3b` §7 means, and evidence rather than
# content. That it is written inside the tree is a placement defect recorded in Task D; excluding it
# here is what makes the tree honest about what it sealed, not a carve-out to make a check pass.
POST_SEAL = ("conformance/",)


def _is_post_seal(rel: str) -> bool:
    return rel == "manifest.json" or rel.startswith(POST_SEAL)


# What an attestation records rather than constitutes, per
# `cryptographic_trust::CONSTITUTION_CRYPTOGRAPHIC_TRUST_V0`. The projection binding and the value
# over it are enforced by the runtime at boot and constitute the composition like any other content;
# when the signing happened records something *about* it, is read by nothing, and changes on every
# build. Counting it made a composition's identity a function of when it was built — two compiles of
# unchanged source differing in one microsecond timestamp, and every pin in the workspace expiring on
# the next rebuild.
#
# Excluding the file instead was refused: that would drop the enforced binding from the identity,
# which weakens it in the direction opposite to the fix. So the exclusion is of a field, and it is
# named here rather than inferred, exactly as the two whole-file exclusions above are.
ATTESTATION_ACCOMPANIES = ("signed_at",)


def _constituent_bytes(path: Path, rel: str) -> bytes:
    """A file's bytes as the identity takes them, with what merely accompanies removed.

    Only the attestation carries an accompanying field today. Every other file enters the identity
    exactly as it sits on disk, and the re-serialization below is confined to the one file that
    needs it so that nothing else acquires a canonical form it did not have.
    """
    raw = path.read_bytes()
    if not rel.endswith("structure_attestation.json"):
        return raw
    record = json.loads(raw)
    for field in ATTESTATION_ACCOMPANIES:
        record.pop(field, None)
    return json.dumps(record, indent=2, sort_keys=True).encode("utf-8")


def enumerate_constituents(out_root: Path) -> list[dict[str, str]]:
    """Every file the snapshot carries as itself, with an integrity value over its bytes.

    Total by construction: the tree is walked, not a list maintained. Two files are excluded, both
    stated: `manifest.json` is the self-description doing the enumerating (SN-6 covers it by the
    identity being taken over this list plus the description's determinative fields), and POST_SEAL
    material was written after the snapshot was constituted.

    One *field* is excluded, and the ground is the same one at a finer grain: an attestation's record
    of when it was signed accompanies the composition rather than constituting it.
    """
    out: list[dict[str, str]] = []
    for path in sorted(out_root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(out_root).as_posix()
        if _is_post_seal(rel):
            continue
        payload = _constituent_bytes(path, rel)
        out.append({"path": rel, "sha256": hashlib.sha256(payload).hexdigest()})
    return out


def compute_snapshot_identity(domains: list[dict], constituents: list[dict], profile: str) -> str:
    """The snapshot's identity, derived from content and covering every constituent (SN-2, SN-6).

    Three inputs, and each is there for a stated reason:

      * the domains identity view — the semantic identity of what was compiled;
      * every constituent, by path and by a hash OF ITS BYTES — so that changing any carried file
        changes the identity, which is SN-2's totality clause;
      * the claimed profile — a self-description that claims a profile and does not cover the claim
        would let the claim change without the identity changing (SN-5, SN-6).

    Provenance is excluded and that exclusion is declared in the manifest's `identity_covers`.
    It is observational content (`3e` §5): `assembled_at` differs between two assemblies of identical
    material, and including it would put GC-9 (same declarations, same identity) in conflict with
    SN-6. What SN-6 requires covered is the description's determinative content, which this is.
    """
    payload = json.dumps(
        {"domains": _identity_view(domains), "constituents": constituents, "profile": profile},
        sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# --- the claimed profile, evaluated -------------------------------------------------------------
#
# SN-5 requires a snapshot to claim a profile and SN-7 requires the claim to be evaluable. The
# realization satisfied the first and not the second: assembly recorded the identity and nothing
# ever read the profile it named. Two profiles sat side by side, one of which resolved twelve of its
# thirty-five required artifacts because a namespace migration had moved them, and **nothing
# distinguished them, because nothing read either.**
#
# Three axes are verifiable against an assembled snapshot and the profile says which: the governance
# artifacts it requires, the artifact kinds it admits, and the workload entry points it names. The
# component-capability axes are declared and unverifiable until each component emits a capability
# declaration, which the profile also says. Checking the three that can be checked is the difference
# between a claim and a conformance contract.

PROFILE_ROOT_ENV = "PGC_SNAPSHOT_PROFILES"
_DEFAULT_PROFILE_ROOT = ".github/snapshot_profiles"


def _profile_root() -> Path:
    """Where profiles are read from.

    Declared rather than derived. A profile is external to what it constrains (NP-7), and while that
    externality is authorship rather than storage today, a path guessed from the assembler's own
    location would make it neither.
    """
    import os
    declared = os.environ.get(PROFILE_ROOT_ENV)
    if declared:
        return Path(declared)
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / _DEFAULT_PROFILE_ROOT
        if candidate.is_dir():
            return candidate
    raise RuntimeError(
        f"no profile root found; set {PROFILE_ROOT_ENV} to the directory holding snapshot profiles")


def _profile_declaration(identity: str) -> dict[str, Any]:
    """The `snapshot_profile` block of the named profile.

    Read by identity, not by filename: a profile is named by what it declares itself to be, and a
    file that happens to carry the name is not the same fact.
    """
    import re
    import yaml
    root = _profile_root()
    for path in sorted(root.glob("*.md")):
        for block in re.findall(r"```yaml\n(.*?)```", path.read_text(encoding="utf-8"), re.S):
            try:
                parsed = yaml.safe_load(block) or {}
            except yaml.YAMLError:
                continue
            declared = parsed.get("snapshot_profile")
            if isinstance(declared, dict) and declared.get("identity") == identity:
                return declared
    raise RuntimeError(
        f"snapshot claims profile {identity!r} and no profile of that identity was found under "
        f"{root} — a claim nobody can read is not a claim (3b SN-7)")


def verify_profile(out_root: Path, profile: str) -> list[str]:
    """What the claimed profile requires and the composition does not carry.

    Returns the unmet requirements. Empty is conformance on the three axes a profile states are
    verifiable; it is not conformance on the four it states are not.
    """
    declared = _profile_declaration(profile)
    present: set[str] = set()
    kinds: set[str] = set()
    for path in (out_root / "canonical").rglob("*.json"):
        record = _read_json(path)
        fqdn = record.get("fqdn") or record.get("fqdn_id")
        if fqdn:
            present.add(fqdn)
        kind = (record.get("frontmatter") or {}).get("artifact_kind") or record.get("artifact_type")
        if kind:
            kinds.add(kind)

    unmet: list[str] = []
    governance = declared.get("required_governance") or {}
    for fqdn in governance.get("artifacts") or ():
        if fqdn not in present:
            unmet.append(f"required governance artifact absent: {fqdn}")
    for kind in governance.get("artifact_kinds") or ():
        if kind not in kinds:
            unmet.append(f"required artifact kind carried by nothing: {kind}")
    for fqdn in (declared.get("required_workloads") or {}).get("entry_workflows") or ():
        if fqdn not in present:
            unmet.append(f"required workload entry point absent: {fqdn}")
    return unmet


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
    # Platform-provided capabilities are legitimately CONSUMED cross-domain: a domain that invokes a
    # platform CS/CT carries its execution binding (Option A "static link"), so the same
    # capability_* FQDN appears in the owner (platform) AND every consumer. That is expected sharing,
    # not redeclaration — the domain's OWN artifacts live in its own namespace and stay single-owned.
    shared_ns = system_ns | {"capability_side_effects", "capability_transforms"}
    owner: dict[str, str] = {}  # fqdn -> domain
    for inp in domains:
        forward = _read_json(inp.source_root / "vocabulary" / inp.domain / "forward.json")
        for fqdn in forward.values():
            if "::" not in fqdn or fqdn.split("::", 1)[0] in shared_ns:
                continue  # shared infrastructure / platform-provided capability — not domain-owned
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

def assemble(source_roots: list[Path], out_root: Path, profile: str) -> dict[str, Any]:
    """
    Assemble the domains under source_roots into out_root; write manifest.json.

    `profile` is the profile identity this snapshot claims (SN-5). It is required: a snapshot that
    claims none cannot have clause 4 of `3b` §7 evaluated about it, and acceptance would be
    establishing three of four conditions while reporting success.

    Claiming a profile is not the same as the profile being external to what claims it (SN-7, NP-7).
    That is authorship rather than declaration and is not settled here.

    Returns the manifest dict. Regenerates the projection tree (build product); manifest.json
    is the committed identity.
    """
    if not profile:
        raise AssemblyError(
            "no profile claimed — a snapshot must claim the profile it asks to be evaluated "
            "against (3b SN-5). Pass --profile or set PGC_SNAPSHOT_PROFILE."
        )
    inputs = discover_domains(source_roots)
    _check_address_space(inputs)

    # --- lift per-domain identity (with compiler cross-checks) ---
    domains = [_domain_identity(inp) for inp in inputs]

    # --- regenerate the assembled projection tree ---
    # Compose EVERY projection kind the compiler emitted (tokenized / trust / vocabulary / evidence /
    # canonical / behavior_logic / …), each domain-scoped, so the consolidated snapshot is the single
    # central inspection location. Two source shapes are handled:
    #   * domain-scoped   <kind>/<domain>/…   (tokenized, trust, vocabulary, evidence) → <kind>/<domain>
    #   * flat            <kind>/…            (canonical by type, behavior_logic by WF) → <kind>/<domain>
    # Only tokenized/vocabulary/trust feed the composite identity; the rest are supplementary.
    kinds: set[str] = set()
    for inp in inputs:
        for child in inp.source_root.iterdir():
            if child.is_dir():
                kinds.add(child.name)

    for kind in kinds:
        dst_kind = out_root / kind
        if dst_kind.exists():
            shutil.rmtree(dst_kind)

    for inp in inputs:
        for kind in kinds:
            src_scoped = inp.source_root / kind / inp.domain   # domain-scoped in source
            src_flat = inp.source_root / kind                  # flat in source
            _ignore = shutil.ignore_patterns(".DS_Store")
            if src_scoped.is_dir():
                shutil.copytree(src_scoped, out_root / kind / inp.domain, ignore=_ignore)
            elif src_flat.is_dir():
                shutil.copytree(src_flat, out_root / kind / inp.domain, ignore=_ignore)

    # --- cross-domain query indexes over the composed snapshot (inspection; not identity) ---
    from assembler.indexes import (
        build_artifact_index,
        build_kind_index,
        build_store_index,
        write_index,
    )
    write_index(out_root, "artifact_index/index.json", build_artifact_index(out_root))
    write_index(out_root, "kind_index/index.json", build_kind_index(out_root))
    write_index(out_root, "store_index/index.json", build_store_index(out_root))

    # --- governance provenance: a domain must have been compiled against the governance it claims ---
    _verify_governance_provenance(out_root)

    # --- self-description: identity, constituents, integrity, provenance, claimed profile ---
    # `3b` §6 requires all five, with the enumeration total. It was four per domain; six top-level
    # constituents were carried and enumerated nowhere, which under §6 is undeclared content.
    constituents = enumerate_constituents(out_root)
    snapshot_id = compute_snapshot_identity(domains, constituents, profile)
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "snapshot_id": snapshot_id,
        "composite_hash": snapshot_id,
        # What the identity is taken over, declared so a party who did not build this snapshot can
        # recompute it without reading the assembler (AI-16). Provenance is excluded as observational
        # content (`3e` §5) — see compute_snapshot_identity.
        "identity_covers": ["domains", "constituents", "profile"],
        # Written after sealing and therefore outside what was sealed. Declared rather than silently
        # skipped, so a party recomputing the identity knows exactly what to exclude (AI-16).
        "post_seal": list(POST_SEAL),
        "profile": profile,
        "domains": domains,
        "constituents": constituents,
        "provenance": _build_provenance(inputs, domains),
    }

    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    return manifest


# ---------------------------------------------------------------------------
# Governance provenance — a domain was checked against the governance it records
# ---------------------------------------------------------------------------

# Kinds a domain build instantiates. MUST match the compiler's _inject_imported_governance
# filter (compiler/stages/s1_extract.py): a governance invariant is imported into a domain iff
# its applies_to_kinds intersects this set and it declares no layer/surface scope.
_DOMAIN_INSTANTIATED = frozenset({"WF", "CC", "CS", "CT", "RB", "AC", "IN", "EV", "TI", "TE"})


def _recompute_governance_closure(out_root: Path, source_domain: str) -> tuple[str, int]:
    """Recompute the normative-closure hash from an assembled domain's canonical governance.

    Mirrors the compiler's closure exactly — see `s1_extract._inject_imported_governance`, whose
    `closure_sources` this must track member-for-member:

      * invariants — domain-applicable (applies_to_kinds intersects the instantiated set) and not
        surface-scoped
      * vocabulary — all of it, unfiltered: a vocabulary has no subject to intersect, and it is
        the language the domain is written in

    Drift between this and the compiler is caught by the stage-5 mutation test, which asserts the
    two agree on an unchanged closure — and by assembly itself, which fails closed on a count or
    hash mismatch rather than assembling a domain checked against different governance.
    """
    canonical = out_root / "canonical" / source_domain
    members: list[tuple[str, str]] = []

    inv_dir = canonical / "invariants"
    if inv_dir.is_dir():
        for path in inv_dir.glob("*.json"):
            raw = _read_json(path)
            proj = (raw.get("frontmatter", {}) or {}).get("assert_projection", {}) or {}
            kinds = set(proj.get("applies_to_kinds", []) or [])
            if not (kinds & _DOMAIN_INSTANTIATED):
                continue
            if (proj.get("scope", {}) or {}).get("applies_to"):
                continue  # surface-specific — not generically imported
            members.append((raw.get("fqdn_id", ""), raw.get("content_hash", "")))

    vocab_dir = canonical / "vocabulary"
    if vocab_dir.is_dir():
        for path in vocab_dir.glob("*.json"):
            raw = _read_json(path)
            members.append((raw.get("fqdn_id", ""), raw.get("content_hash", "")))

    members.sort()
    h = hashlib.sha256()
    for fqdn, content_hash in members:
        h.update(fqdn.encode("utf-8")); h.update(b"\x00")
        h.update((content_hash or "").encode("utf-8")); h.update(b"\x00")
    return h.hexdigest(), len(members)


def _verify_governance_provenance(out_root: Path) -> None:
    """Fail if any domain's recorded governance closure disagrees with the assembled source.

    A domain attestation may carry `imported_governance` (the governance it was compiled against).
    Recompute that closure from the source domain present in this assembly; a mismatch means the
    domain was compiled against different governance than is being assembled — stale, fail closed.
    """
    trust_root = out_root / "trust"
    if not trust_root.is_dir():
        return
    for att_path in sorted(trust_root.glob("*/structure_attestation.json")):
        att = _read_json(att_path)
        recorded = att.get("imported_governance")
        if not recorded:
            continue
        source = recorded.get("import_domain", "")
        expected = recorded.get("governance_closure_hash", "")
        actual, count = _recompute_governance_closure(out_root, source)
        if actual != expected:
            raise AssemblyError(
                f"[{att.get('structure_id')}] governance provenance mismatch: attestation records "
                f"closure {expected[:16]}… over '{source}' ({recorded.get('closure_member_count')} members), "
                f"but the assembled '{source}' surface yields {actual[:16]}… ({count}). "
                f"The domain was compiled against different governance than is being assembled — recompile it."
            )


# ---------------------------------------------------------------------------
# Verify — the boot-time root-of-trust check, reusable by the runtime
# ---------------------------------------------------------------------------

def _verify_copies_agree(out_root: Path) -> None:
    """Every copy of one artifact identity in the composition must be identical.

    A platform artifact is compiled into each domain's own output and the assembler collects them
    all, so one identity exists in the snapshot N times — `capability_side_effects::CS_MUTABLE_JSON_V0`
    exists five times today. Nothing checked that the copies agreed, and they can disagree easily:
    editing a governance artifact and recompiling one domain leaves every other domain carrying the
    previous version. That composition assembled, reported conformance PASSED over 376 artifacts and
    round-trip verified OK, while the published capability surface answered from a stale copy.

    Compared by content_hash, which the compiler already writes per artifact.
    """
    seen: dict[str, dict[str, list[str]]] = {}
    for path in sorted((out_root / "canonical").glob("*/*/*.json")):
        if path.name == "metadata.json":
            continue
        doc = _read_json(path)
        fqdn = doc.get("fqdn_id")
        digest = doc.get("content_hash")
        if not fqdn or not digest:
            continue
        seen.setdefault(fqdn, {}).setdefault(digest, []).append(str(path.relative_to(out_root)))

    disagreeing = {fqdn: copies for fqdn, copies in seen.items() if len(copies) > 1}
    if disagreeing:
        detail = "; ".join(
            f"{fqdn} differs across {sum(len(v) for v in copies.values())} copies "
            f"({len(copies)} distinct versions: "
            + ", ".join(sorted(paths[0] for paths in copies.values())) + ")"
            for fqdn, copies in sorted(disagreeing.items())
        )
        raise AssemblyError(
            f"composition holds disagreeing copies of {len(disagreeing)} artifact identity(ies) — "
            f"recompile every domain after a governance edit: {detail}"
        )


def verify_snapshot(out_root: Path) -> dict[str, Any]:
    """Acceptance. Establish that what is in hand is what was determined.

    Construction establishes admissibility; acceptance establishes correspondence, and correspondence
    is a property of the carried bytes rather than of the act that produced them. `3b` §7 names four
    conditions and every one is established here FROM CONTENT:

      1. integrity  — each constituent's hash recomputed from its bytes, compared to the
                      self-description's value for it
      2. totality   — every file present is enumerated, every file enumerated is present
      3. identity   — recomputed from the RECOMPUTED constituent hashes, compared to the identity
                      borne. Recomputing over recorded hashes detects a tampered manifest; only
                      recomputing over recomputed hashes detects a tampered constituent
      4. profile    — the snapshot claims one

    This previously compared recorded values to recorded values — manifest against metadata.json
    against attestation — which is transitive from construction and establishes nothing to a party
    who did not build the snapshot (AI-16).

    On any failure the snapshot is refused whole (SN-9). There is no partial acceptance.
    """
    manifest = _read_json(out_root / "manifest.json")
    domains = manifest.get("domains", [])

    profile = manifest.get("profile") or ""
    if not profile:
        raise AssemblyError(
            "snapshot claims no profile — clause 4 of 3b §7 cannot be evaluated about it (SN-5)."
        )

    declared = manifest.get("constituents")
    if declared is None:
        raise AssemblyError(
            "manifest enumerates no constituents — it is a provenance record rather than a "
            "self-description, and integrity cannot be established per constituent (3b §6, SN-5)."
        )

    on_disk = {
        rel for rel in (
            p.relative_to(out_root).as_posix() for p in out_root.rglob("*") if p.is_file()
        ) if not _is_post_seal(rel)
    }
    enumerated = {c["path"] for c in declared}
    undeclared = sorted(on_disk - enumerated)
    missing = sorted(enumerated - on_disk)
    if undeclared:
        raise AssemblyError(
            f"undeclared content: {len(undeclared)} file(s) present and enumerated nowhere — "
            f"e.g. {undeclared[:3]}. A constituent absent from the self-description must be "
            f"refused at acceptance (3b §6)."
        )
    if missing:
        raise AssemblyError(
            f"missing content: {len(missing)} file(s) enumerated and absent — e.g. {missing[:3]}."
        )

    recomputed: list[dict[str, str]] = []
    for entry in declared:
        # The same bytes the identity was taken over, not the bytes on disk — an attestation's
        # record of when it was signed accompanies the composition and is excluded from both.
        actual = hashlib.sha256(
            _constituent_bytes(out_root / entry["path"], entry["path"])).hexdigest()
        if actual != entry["sha256"]:
            raise AssemblyError(
                f"integrity failure at {entry['path']}: content hashes to {actual[:16]}… but the "
                f"self-description carries {entry['sha256'][:16]}… for it (3b §7 clause 1)."
            )
        recomputed.append({"path": entry["path"], "sha256": actual})

    # The claim, evaluated. SN-5 is satisfied by claiming a profile; SN-7 asks whether the claim
    # holds, and until now nothing asked. A snapshot claiming a profile whose required artifacts it
    # does not carry is a snapshot asserting a conformance it does not have.
    unmet = verify_profile(out_root, profile)
    if unmet:
        raise AssemblyError(
            f"snapshot claims {profile} and does not satisfy it — "
            + "; ".join(unmet[:5])
            + (f"; and {len(unmet) - 5} more" if len(unmet) > 5 else ""))

    derived = compute_snapshot_identity(domains, recomputed, profile)
    borne = manifest.get("snapshot_id")
    if derived != borne:
        raise AssemblyError(
            f"identity failure: derived {derived[:16]}… from content, snapshot bears "
            f"{str(borne)[:16]}… (3b §7 clause 2, SN-2)."
        )

    # Copies of one identity across domains must agree (GC-12) — a composition obligation rather
    # than correspondence, and not subsumed by the four conditions above.
    _verify_copies_agree(out_root)

    return manifest
