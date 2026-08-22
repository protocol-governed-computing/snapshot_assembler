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
            "owner_subdomain": (raw.get("frontmatter") or {}).get("concern") or None,
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
    cc_stores = _cc_declared_stores(docs)

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

    def bindings_for(path: str, store_name: str) -> list[dict[str, Any]]:
        bindings: list[dict[str, Any]] = []
        for (rb_fqdn, cs_fqdn), declared_paths in sorted(rb_paths.items()):
            if path not in declared_paths:
                continue
            # Which contracts consume *this* store, not every store the binding reaches. A binding
            # declared through a storage structure reaches every path that structure owns, so
            # asking the binding alone answers "which contracts touch this domain's storage" and
            # reports identical consumers for three different stores. A contract names the store
            # each of its steps uses, and that is the fact being asked for.
            # Scoped to what this binding actually reaches: the workflows bound to this RB,
            # the contracts they contain, and of those the ones binding this capability.
            rb_workflows = {wf for wf, rbs in wf_binds_rb.items() if rb_fqdn in rbs}
            candidates = {cc for wf in rb_workflows
                          for cc in wf_contains.get(wf, set())
                          if cs_fqdn in cc_binds_cs.get(cc, set())}
            if len(declared_paths) > 1:
                # The binding reaches every store its structure owns, so it cannot say which one a
                # contract used; the contract's own step declaration can. Filtering only here keeps
                # a binding naming one concrete path — where the path *is* the store — answering for
                # contracts that never needed to name it.
                candidates = {cc for cc in candidates
                              if store_name in cc_stores.get(cc, set())}
            consumer_ccs = sorted(candidates)
            workflows = sorted({wf for wf in rb_workflows
                                if wf_contains.get(wf, set()) & candidates})
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
                {**declaration, "bindings": bindings_for(declaration["path"], store["store"])}
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


def _cc_declared_stores(docs: dict[str, dict]) -> dict[str, set[str]]:
    """CC fqdn → the store names its pipeline steps declare.

    A contract states the store each side-effect step reaches. Nothing else in the composition
    records which store a contract uses: the runtime binding names a capability and a structure,
    and the evidence graph records that a contract binds a capability — neither says which of the
    structure's stores the contract writes.
    """
    out: dict[str, set[str]] = {}
    for fqdn, doc in docs.items():
        if doc.get("artifact_type") != "CC":
            continue
        pipeline = doc.get("frontmatter", {}).get("core", {}).get("pipeline") or []
        named = {step.get("store") for step in pipeline
                 if isinstance(step, dict) and step.get("store")}
        if named:
            out[fqdn] = named
    return out


def _rb_store_paths(docs: dict[str, dict]) -> dict[tuple[str, str], set[str]]:
    """(RB fqdn, CS fqdn) → the data paths that binding reaches.

    A binding declares where its capability writes in one of two ways, and reading only the first
    left this join blind to fourteen of the composition's fifteen stores:

      policy.path       one concrete path, with the data-root template prefix stripped
      policy.structure  a storage STRUCTURE, whose `entity_stores` declare every path it owns

    The second is what every pipeline-authored domain uses, and the reference workload besides;
    only `ai_governance` names paths in its policies. Resolving just the concrete form meant
    `si.store.consumers` answered for that one domain and reported no consumer for every other
    store in the composition — including stores three contracts demonstrably write.

    A binding whose policy declares neither binds no store (CS_CLOCK_V0 under any RB is the
    standing example) and contributes nothing to the join.
    """
    paths: dict[tuple[str, str], set[str]] = {}
    for fqdn, doc in docs.items():
        if doc.get("artifact_type") != "RB":
            continue
        core = doc.get("frontmatter", {}).get("core", {})
        bindings = core.get("bindings", {})
        for cs_fqdn in sorted(bindings):
            policy = bindings[cs_fqdn].get("policy") or {}
            declared: set[str] = set()

            concrete = policy.get("path")
            if concrete:
                if concrete.startswith(_DATA_ROOT_TEMPLATE):
                    concrete = concrete[len(_DATA_ROOT_TEMPLATE):]
                declared.add(concrete)

            # A binding may declare its structure, or lean on the one the runtime binding declares
            # for all of them. Reading only the per-binding form left every store whose binding
            # carries an empty policy unreachable, though the RB says plainly where it writes.
            # A binding may declare its structure, or lean on the one the runtime binding declares
            # for all of them — but only when it names no path of its own. A binding that names one
            # concrete path has already said where it writes, and adding its structure's other
            # paths on top would make an unambiguous binding look like it reached them all.
            structure = policy.get("structure") or (None if declared else core.get("storage_structure"))
            if structure:
                entity_stores = ((docs.get(structure) or {})
                                 .get("frontmatter", {}).get("core", {}).get("entity_stores") or {})
                declared.update(store.get("path") for store in entity_stores.values()
                                if isinstance(store, dict) and store.get("path"))

            if declared:
                paths[(fqdn, cs_fqdn)] = declared
    return paths


def write_index(out_root: Path, rel_path: str, content: dict[str, Any]) -> Path:
    path = out_root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(content, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path
