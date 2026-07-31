"""
indexes.py — cross-domain query indexes over the assembled snapshot.

Three inspection indexes, built AFTER composition (the assembler is the only point with the full
federated view of all domains — the PGC successor to RI-0's cross-structure `build` aggregation):

  * artifact_index/index.json — FQDN → domain / kind / owner_subdomain / canonical_path /
                                evidence_paths / per-domain addresses. Consumed by `si`.
  * kind_index/index.json     — rich by-kind cross-reference (workflows / CCs / CTs / CSs / intents /
                                runtime_bindings / actors / events + cross-refs + vocabulary +
                                domain groupings). The si/tooling query database.
  * store_index/index.json    — store → owning storage STRUCTURE, declared path, and binding
                                surface (RB + CS + workflows + consumer CCs).

The assembler produces an INSPECTABLE snapshot, not merely an executable one: the compiler owns
the correctness of one domain, the assembler the correctness and indexing of the composition, and
`snapshot_inspector` the read-only query interface over it. An index is a composition-level fact —
no single domain build can compute one — which is why all three live here and none in the compiler.

Re-emission only: every fact is read from materialized projections in the consolidated snapshot
(canonical/<domain>, vocabulary/<domain>, evidence/<domain>). Zero re-derivation, deterministic
(sorted keys, no timestamps), fail-hard on malformed input.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "v0"


# ---------------------------------------------------------------------------
# Shared readers over the consolidated snapshot
# ---------------------------------------------------------------------------

def _load_canonical(out_root: Path) -> dict[str, dict]:
    """fqdn → canonical artifact doc, across all domains (canonical/<domain>/<type>/*.json)."""
    canon = out_root / "canonical"
    docs: dict[str, dict] = {}
    if not canon.is_dir():
        return docs
    for f in sorted(canon.rglob("*.json")):
        if f.name == "metadata.json":
            continue
        raw = json.loads(f.read_text(encoding="utf-8"))
        fqdn = raw.get("fqdn_id")
        if fqdn and "::" in fqdn:
            raw["_canonical_path"] = f.relative_to(out_root).as_posix()
            docs[fqdn] = raw
    return docs


def _load_membership(out_root: Path) -> dict[str, dict[str, str]]:
    """fqdn → {domain: hex_address}, from each vocabulary/<domain>/reverse.json."""
    vocab = out_root / "vocabulary"
    membership: dict[str, dict[str, str]] = {}
    if not vocab.is_dir():
        return membership
    for d in sorted(p for p in vocab.iterdir() if p.is_dir()):
        rev_path = d / "reverse.json"
        if not rev_path.is_file():
            continue
        for fqdn, addr in json.loads(rev_path.read_text(encoding="utf-8")).items():
            membership.setdefault(fqdn, {})[d.name] = addr
    return membership


def _load_evidence_edges(out_root: Path) -> list[dict]:
    """All semantic edges from every evidence/<domain>/evidence.json.

    `evidence.json` carries the SEMANTIC graph (WF_BINDS_RB, WF_CONTAINS_NODE, CC_BINDS_CS,
    NODE_NEXT, …), keyed by FQDN. Its sibling `evidence_graph.json` is the COMPILE TRACE
    (STAGE_SEQUENCE / CAUSALITY, keyed by event id) and holds none of those kinds — reading it
    here yielded zero matches and left every consumer's cross-reference silently empty.
    """
    evidence = out_root / "evidence"
    edges: list[dict] = []
    if not evidence.is_dir():
        return edges
    for eg in sorted(evidence.glob("*/evidence.json")):
        data = json.loads(eg.read_text(encoding="utf-8"))
        edges.extend(data.get("edges", []))
    return edges


def _owner_subdomain(module_path: str | None) -> str | None:
    """Owning subdomain declared by module_path (`<pkg>.registry.<subdomain>.<kind>`), else None."""
    if not module_path:
        return None
    parts = module_path.split(".")
    if len(parts) >= 4 and parts[1] == "registry" and not parts[2].startswith("FB_"):
        return parts[2]
    return None


# ---------------------------------------------------------------------------
# artifact_index
# ---------------------------------------------------------------------------

def build_artifact_index(out_root: Path) -> dict[str, Any]:
    docs = _load_canonical(out_root)
    membership = _load_membership(out_root)
    evidence_root = out_root / "evidence"

    artifacts: dict[str, dict] = {}
    for fqdn, raw in docs.items():
        domain = fqdn.split("::", 1)[0]
        scopes = membership.get(fqdn, {})
        evidence_paths = {}
        for scope in sorted(scopes):
            eg_rel = f"evidence/{scope}/evidence_graph.json"
            if (evidence_root / scope / "evidence_graph.json").is_file():
                evidence_paths[scope] = eg_rel
        artifacts[fqdn] = {
            "domain": domain,
            "kind": raw.get("artifact_type"),
            "owner_subdomain": _owner_subdomain(raw.get("module_path")),
            "canonical_path": raw["_canonical_path"],
            "evidence_paths": evidence_paths,
            "addresses": {s: scopes[s] for s in sorted(scopes)},
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_by": "snapshot_assembler",
        "artifact_count": len(artifacts),
        "artifacts": dict(sorted(artifacts.items())),
    }


# ---------------------------------------------------------------------------
# kind_index (si query database)
# ---------------------------------------------------------------------------

def build_kind_index(out_root: Path) -> dict[str, Any]:
    docs = _load_canonical(out_root)
    edges = _load_evidence_edges(out_root)

    workflows: dict[str, dict] = {}
    capability_contracts: dict[str, dict] = {}
    capability_transforms: dict[str, dict] = {}
    capability_side_effects: dict[str, dict] = {}
    intents: dict[str, dict] = {}
    runtime_bindings: dict[str, dict] = {}
    actors: dict[str, dict] = {}
    events: dict[str, dict] = {}

    for fqdn, doc in docs.items():
        atype = doc.get("artifact_type", "")
        ns = doc.get("namespace", fqdn.split("::")[0])
        fm = doc.get("frontmatter", {})
        core = fm.get("core", {})
        base = {
            "fqdn": fqdn, "namespace": ns, "code": fqdn.split("::")[-1],
            "version": fm.get("version", "v0"), "raw": doc,
        }
        if atype == "WF":
            workflows[fqdn] = {**base, "subdomain": fm.get("subdomain", ""),
                               "summary": core.get("summary", ""), "start_node": core.get("start_node", ""),
                               "nodes": core.get("nodes", {}), "actor_context": core.get("actor_context", "")}
        elif atype == "CC":
            rsc = core.get("result_status_contract", {})
            capability_contracts[fqdn] = {**base, "summary": core.get("summary", ""),
                                          "outcomes": rsc.get("allowed", []), "pipeline": core.get("pipeline", []),
                                          "inputs": core.get("inputs", {}), "outputs": core.get("outputs", {})}
        elif atype == "CT":
            machine = fm.get("machine", {})
            capability_transforms[fqdn] = {**base, "summary": core.get("summary", fm.get("description", "")),
                                           "purity": machine.get("ct_purity", "ct_pure"),
                                           "inputs": core.get("inputs", {}), "outputs": core.get("outputs", {})}
        elif atype == "CS":
            capability_side_effects[fqdn] = {**base, "operations": core.get("operations", {})}
        elif atype == "IN":
            intents[fqdn] = base
        elif atype == "RB":
            runtime_bindings[fqdn] = {**base, "bindings": core.get("bindings", {})}
        elif atype == "AC":
            actors[fqdn] = {**base, "type": core.get("type", ""), "attributes": core.get("attributes", {})}
        elif atype == "EV":
            events[fqdn] = {**base, "schema": core.get("schema", {})}

    # --- cross-references ---
    wf_to_ccs = {
        wf: [n.get("fqdn_id", f"{w['namespace']}::{code}")
             for code, n in w["nodes"].items() if n.get("type") == "CC"]
        for wf, w in workflows.items()
    }
    cc_outcomes = {cc: c["outcomes"] for cc, c in capability_contracts.items()}
    cc_to_ct_cs: dict[str, list[str]] = {}
    for cc, c in capability_contracts.items():
        cc_to_ct_cs[cc] = [s["transform"] for s in c["pipeline"] if "transform" in s]
    cc_upstream: dict[str, list[str]] = {}
    cc_downstream: dict[str, list[str]] = {}
    for edge in edges:
        k, src, tgt = edge.get("kind", ""), edge.get("source_fqdn", ""), edge.get("target_fqdn", "")
        if k == "NODE_NEXT" and src and tgt:
            cc_downstream.setdefault(src, [])
            if tgt not in cc_downstream[src]:
                cc_downstream[src].append(tgt)
            cc_upstream.setdefault(tgt, [])
            if src not in cc_upstream[tgt]:
                cc_upstream[tgt].append(src)

    # --- domain / subdomain groupings ---
    domains: dict[str, list[str]] = {}
    subdomains: dict[str, list[str]] = {}
    for fqdn in docs:
        domains.setdefault(fqdn.split("::")[0], []).append(fqdn)
    for wf, w in workflows.items():
        if w["subdomain"]:
            subdomains.setdefault(w["subdomain"], []).append(wf)

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_by": "snapshot_assembler",
        "workflows": dict(sorted(workflows.items())),
        "capability_contracts": dict(sorted(capability_contracts.items())),
        "capability_transforms": dict(sorted(capability_transforms.items())),
        "capability_side_effects": dict(sorted(capability_side_effects.items())),
        "intents": dict(sorted(intents.items())),
        "runtime_bindings": dict(sorted(runtime_bindings.items())),
        "actors": dict(sorted(actors.items())),
        "events": dict(sorted(events.items())),
        "cross_references": {
            "wf_to_ccs": dict(sorted(wf_to_ccs.items())),
            "cc_to_ct_cs": dict(sorted(cc_to_ct_cs.items())),
            "cc_outcomes": dict(sorted(cc_outcomes.items())),
            "cc_upstream": dict(sorted(cc_upstream.items())),
            "cc_downstream": dict(sorted(cc_downstream.items())),
        },
        "domains": {d: sorted(v) for d, v in sorted(domains.items())},
        "subdomains": {s: sorted(v) for s, v in sorted(subdomains.items())},
    }


# ---------------------------------------------------------------------------
# store_index (storage ownership + binding surface)
# ---------------------------------------------------------------------------

_DATA_ROOT_TEMPLATE = "{{module_data_root}}/"


def build_store_index(out_root: Path) -> dict[str, Any]:
    """Materialize the store-ownership join the composed snapshot already declares in three places:

        storage STRUCTURE artifacts  →  core.entity_stores (store name → data path)
        RB artifacts                 →  core.bindings      (CS → policy path)
        evidence.json                →  WF_BINDS_RB, WF_CONTAINS_NODE, CC_BINDS_CS

    into: store → owning structure, declared path, binding surface (RB + CS + workflows +
    consumer CCs). Re-emission of declared facts only; deterministic; no policing.
    """
    docs = _load_canonical(out_root)
    stores = _declared_stores(docs)
    rb_paths = _rb_store_paths(docs)

    wf_binds_rb: dict[str, set] = {}
    wf_contains: dict[str, set] = {}
    cc_binds_cs: dict[str, set] = {}
    for edge in _load_evidence_edges(out_root):
        kind, src, tgt = edge.get("kind"), edge.get("source_fqdn"), edge.get("target_fqdn")
        if not src or not tgt:
            continue
        if kind == "WF_BINDS_RB":
            wf_binds_rb.setdefault(src, set()).add(tgt)
        elif kind == "WF_CONTAINS_NODE":
            wf_contains.setdefault(src, set()).add(tgt)
        elif kind == "CC_BINDS_CS":
            cc_binds_cs.setdefault(src, set()).add(tgt)

    def bindings_for(path: str) -> list[dict[str, Any]]:
        bindings: list[dict[str, Any]] = []
        for (rb_fqdn, cs_fqdn), declared_path in sorted(rb_paths.items()):
            if declared_path != path:
                continue
            workflows = sorted(wf for wf, rbs in wf_binds_rb.items() if rb_fqdn in rbs)
            consumer_ccs = sorted({
                cc
                for wf in workflows
                for cc in wf_contains.get(wf, set())
                if cs_fqdn in cc_binds_cs.get(cc, set())
            })
            bindings.append({
                "rb": rb_fqdn,
                "cs": cs_fqdn,
                "workflows": workflows,
                "consumer_ccs": consumer_ccs,
            })
        return bindings

    indexed = {
        key: {
            "store": store["store"],
            "domain": store["domain"],
            "declarations": [
                {**declaration, "bindings": bindings_for(declaration["path"])}
                for declaration in store["declarations"]
            ],
        }
        for key, store in stores.items()
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_by": "snapshot_assembler",
        "store_count": len(indexed),
        "stores": dict(sorted(indexed.items())),
    }


def _declared_stores(docs: dict[str, dict]) -> dict[str, dict[str, Any]]:
    """Stores declared via core.entity_stores in storage STRUCTUREs, keyed '<domain>::<STORE>'.

    A store name may be declared by more than one storage STRUCTURE in a domain — with the same
    path (a shared store) or different paths (per-subdomain stores sharing a name). Each
    declaration is recorded as the protocol states it: no merging, no policing.
    """
    stores: dict[str, dict[str, Any]] = {}
    for fqdn, doc in docs.items():
        if doc.get("artifact_type") != "STRUCTURE":
            continue
        core = doc.get("frontmatter", {}).get("core", {})
        entity_stores = core.get("entity_stores")
        if not entity_stores:
            continue
        domain = core.get("domain") or fqdn.split("::", 1)[0]
        for store_name in sorted(entity_stores):
            declared = entity_stores[store_name]
            entry = stores.setdefault(
                f"{domain}::{store_name}",
                {"store": store_name, "domain": domain, "declarations": []},
            )
            entry["declarations"].append({
                "path": declared.get("path", ""),
                "description": declared.get("description", ""),
                "declared_by": fqdn,
            })
    for entry in stores.values():
        entry["declarations"].sort(key=lambda d: (d["path"], d["declared_by"]))
    return stores


def _rb_store_paths(docs: dict[str, dict]) -> dict[tuple[str, str], str]:
    """(RB fqdn, CS fqdn) → declared data path, with the data-root template prefix stripped.

    A binding whose policy declares no path binds no store (CS_MUTABLE_JSON_V0 under
    workload::RB_COLLATZ_V0 is the standing example) and contributes nothing to the join.
    """
    paths: dict[tuple[str, str], str] = {}
    for fqdn, doc in docs.items():
        if doc.get("artifact_type") != "RB":
            continue
        bindings = doc.get("frontmatter", {}).get("core", {}).get("bindings", {})
        for cs_fqdn in sorted(bindings):
            declared_path = ((bindings[cs_fqdn].get("policy") or {}).get("path"))
            if not declared_path:
                continue
            if declared_path.startswith(_DATA_ROOT_TEMPLATE):
                declared_path = declared_path[len(_DATA_ROOT_TEMPLATE):]
            paths[(fqdn, cs_fqdn)] = declared_path
    return paths


def write_index(out_root: Path, rel_path: str, content: dict[str, Any]) -> Path:
    path = out_root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(content, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path
