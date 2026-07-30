"""
conformance.py — Composition Conformance: the lifecycle phase after assembly.

    compiler → verified domain → assembler → composed snapshot
        → COMPOSITION CONFORMANCE → attested snapshot

A domain is verified in isolation, against the governance surface it imported. Properties that
only exist once independently-governed domains are composed have no earlier enforcement point:
the compiler sees one domain at a time and never holds a snapshot, and the assembler is a
composition *engine* — it proves identity and integrity, not governance. This phase proves
properties **of the composition**.

Remit (the permanent home for this class of check):
  * evaluate snapshot-scoped invariants          [implemented]
  * verify profile uniqueness                    [implemented — via declared composition_check]
  * verify cross-domain uniqueness               [remit, not yet declared]
  * verify implementation resolvability          [remit, not yet declared]
  * verify composition contracts                 [remit, not yet declared]
  * emit composition evidence                    [implemented]
  * fail hard                                    [implemented]

Two boundaries this module must keep:

  1. **No dependency on the compiler.** Rules are read from the assembled snapshot's own canonical
     invariants, never from the compiler's handler registry. The phase is a peer of the compiler,
     not a client of it.
  2. **No implementation semantics in the declaration.** An invariant declares a language-neutral
     `composition_check` — a selector plus a cardinality rule. It does not name a handler, module,
     or callable. Evaluating a declaration is this module's job; *being* one is the artifact's.

Admission is by declaration: an invariant participates iff it declares
`assert_projection.composition_check`. Nothing here enumerates which invariants exist.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from assembler import ASSEMBLER_VERSION

CONFORMANCE_VERSION = "v0"

# Cardinality rules this phase can evaluate. Extending the vocabulary is a declaration act in
# SCHEMA_INVARIANT_V0 plus one entry here — never a special case inside an evaluator.
_CARDINALITY = {
    "exactly_one": lambda n: n == 1,
    "at_most_one": lambda n: n <= 1,
    "none": lambda n: n == 0,
}


class ConformanceError(RuntimeError):
    """Raised when the composed snapshot violates a composition-scoped invariant. Fail hard."""


@dataclass(frozen=True)
class Finding:
    invariant: str
    subject: str
    rule: str
    status: str          # PASSED | FAILED
    examined: int        # artifacts the selector matched — recorded so a vacuous check is visible
    matched: list[str]   # fqdn_ids of the matched artifacts
    message: str


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConformanceError(f"unreadable snapshot artifact {path}: {exc}") from exc


# ---------------------------------------------------------------------------
# Rule discovery — declared, never enumerated
# ---------------------------------------------------------------------------

def _canonical_artifacts(out_root: Path) -> list[dict]:
    """Every canonical artifact in the composed snapshot, across all domains."""
    canonical = out_root / "canonical"
    if not canonical.is_dir():
        raise ConformanceError(f"no canonical/ in snapshot: {out_root}")
    return [_read_json(p) for p in sorted(canonical.glob("*/*/*.json"))
            if p.name != "metadata.json"]


def _composition_rules(artifacts: list[dict]) -> list[tuple[str, dict]]:
    """(invariant_fqdn, composition_check) for every invariant declaring one.

    Read from the assembled snapshot itself, so the rules enforced are exactly the rules the
    composition carries — a domain cannot be checked against governance it did not compile under.
    """
    rules = []
    for a in artifacts:
        if a.get("artifact_type") != "INVARIANT":
            continue
        proj = (a.get("frontmatter", {}) or {}).get("assert_projection", {}) or {}
        check = proj.get("composition_check")
        if check:
            rules.append((a.get("fqdn_id", a.get("artifact_code", "?")), check))
    return sorted(rules)


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def _matches(artifact: dict, selector: dict) -> bool:
    """All declared selector fields must match. Unknown fields are a hard failure, not a pass."""
    for field, expected in selector.items():
        if field == "namespace":
            if artifact.get("namespace") != expected:
                return False
        elif field == "artifact_type":
            if artifact.get("artifact_type") != expected:
                return False
        elif field == "artifact_code_prefix":
            if not str(artifact.get("artifact_code", "")).startswith(expected):
                return False
        elif field == "where":
            fm = artifact.get("frontmatter", {}) or {}
            for key, value in expected.items():
                if fm.get(key) != value:
                    return False
        else:
            raise ConformanceError(
                f"unknown composition_check selector field {field!r} — the declaration is admissible "
                f"only if every field has an evaluator (no silent skip)"
            )
    return True


def _evaluate(invariant: str, check: dict, artifacts: list[dict]) -> Finding:
    rule = check.get("rule")
    predicate = _CARDINALITY.get(rule)
    if predicate is None:
        raise ConformanceError(
            f"{invariant}: unknown composition_check rule {rule!r} "
            f"(known: {', '.join(sorted(_CARDINALITY))})"
        )
    selector = check.get("selector") or {}
    if not selector:
        raise ConformanceError(f"{invariant}: composition_check declares an empty selector")

    matched = sorted(a.get("fqdn_id", a.get("artifact_code", "?"))
                     for a in artifacts if _matches(a, selector))
    subject = check.get("subject", "artifact")
    ok = predicate(len(matched))
    if ok:
        message = f"{rule}: found {len(matched)} {subject}"
    elif len(matched) == 0:
        message = (f"{rule} violated: no {subject} found in the composed snapshot. "
                   f"The composition declares none; exactly one is required.")
    else:
        plural = subject if subject.endswith("s") else f"{subject}s"
        message = (f"{rule} violated: {len(matched)} competing {plural} in the composed snapshot "
                   f"— {', '.join(matched)}. Independently-governed domains have each declared one; "
                   f"exactly one may be active across the whole composition.")
    return Finding(
        invariant=invariant, subject=subject, rule=rule,
        status="PASSED" if ok else "FAILED",
        examined=len(matched), matched=matched, message=message,
    )


# ---------------------------------------------------------------------------
# Phase entry point
# ---------------------------------------------------------------------------

def check_composition(out_root: Path) -> dict[str, Any]:
    """Run Composition Conformance over an assembled snapshot.

    Emits composition evidence to `conformance/composition.json` and raises ConformanceError on
    any violation. Evidence is written before raising: a failed composition must leave a record
    of *why* it failed, not just a non-zero exit.
    """
    artifacts = _canonical_artifacts(out_root)
    rules = _composition_rules(artifacts)
    findings = [_evaluate(fqdn, check, artifacts) for fqdn, check in rules]
    failed = [f for f in findings if f.status == "FAILED"]

    manifest_path = out_root / "manifest.json"
    manifest = _read_json(manifest_path) if manifest_path.is_file() else {}

    evidence = {
        "conformance_version": CONFORMANCE_VERSION,
        "assembler_version": ASSEMBLER_VERSION,
        "phase": "composition_conformance",
        "snapshot_id": manifest.get("snapshot_id"),
        "domains": [d.get("domain") for d in manifest.get("domains", [])],
        "artifacts_examined": len(artifacts),
        "rules_evaluated": len(findings),
        "status": "FAILED" if failed else "PASSED",
        "findings": [
            {
                "invariant": f.invariant, "subject": f.subject, "rule": f.rule,
                "status": f.status, "examined": f.examined,
                "matched": f.matched, "message": f.message,
            }
            for f in findings
        ],
        "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    out_dir = out_root / "conformance"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "composition.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")

    if failed:
        detail = "\n".join(f"  [{f.invariant}] {f.message}" for f in failed)
        raise ConformanceError(
            f"composition conformance FAILED — {len(failed)} of {len(findings)} "
            f"composition-scoped invariant(s) violated:\n{detail}"
        )
    return evidence
