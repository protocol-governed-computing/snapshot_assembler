#!/usr/bin/env python3
"""
Index testbed — the store-ownership join and the semantic-edge source the indexes read.

Self-contained: fixtures are built in temp directories in the assembled snapshot's layout
(canonical/<domain>/<kind>/, evidence/<domain>/evidence.json); the builders stay write-free.

Run: python scripts/testbed/test_indexes.py
"""

import json
import sys
import tempfile
from pathlib import Path

from assembler.indexes import build_artifact_index, build_kind_index, build_store_index

PASS = 0
FAIL = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}  {detail}")


def _write(root: Path, relative: str, payload: dict) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _fixture(root: Path) -> None:
    """One domain: a storage STRUCTURE, an RB binding one of its stores, and semantic edges."""
    _write(root, "canonical/d/structures/d__STRUCTURE_D_STORAGE_V0.json", {
        "fqdn_id": "d::STRUCTURE_D_STORAGE_V0",
        "artifact_type": "STRUCTURE",
        "frontmatter": {"core": {
            "domain": "d",
            "entity_stores": {
                "ACTOR": {"path": "d/identity/actors.json", "description": "actors"},
            },
        }},
    })
    _write(root, "canonical/d/runtime_bindings/d__RB_X_V0.json", {
        "fqdn_id": "d::RB_X_V0",
        "artifact_type": "RB",
        "frontmatter": {"core": {"bindings": {
            "cse::CS_REG_V0": {"policy": {"path": "{{module_data_root}}/d/identity/actors.json"}},
            "cse::CS_MAIL_V0": {"policy": {"enabled": True}},
        }}},
    })
    _write(root, "evidence/d/evidence.json", {
        "nodes": [], "event_catalog": [],
        "edges": [
            {"kind": "WF_BINDS_RB", "source_fqdn": "d::WF_X_V0", "target_fqdn": "d::RB_X_V0"},
            {"kind": "WF_CONTAINS_NODE", "source_fqdn": "d::WF_X_V0", "target_fqdn": "d::CC_PERSIST_V0"},
            {"kind": "CC_BINDS_CS", "source_fqdn": "d::CC_PERSIST_V0", "target_fqdn": "cse::CS_REG_V0"},
            {"kind": "NODE_NEXT", "source_fqdn": "d::CC_FIRST_V0", "target_fqdn": "d::CC_PERSIST_V0"},
        ],
    })
    # The compile trace — a sibling file holding no semantic edges. Present so a builder that
    # reads the wrong one produces an empty join rather than an error.
    _write(root, "evidence/d/evidence_graph.json", {
        "edges": [{"kind": "STAGE_SEQUENCE", "source_event_id": 1, "target_event_id": 2}],
    })


def test_store_index_join() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        _fixture(ws)
        index = build_store_index(ws)
        entry = index["stores"]["d::ACTOR"]
        declaration = entry["declarations"][0]
        check("store_join_count", index["store_count"] == 1)
        check("store_join_owner", declaration["declared_by"] == "d::STRUCTURE_D_STORAGE_V0")
        bindings = declaration["bindings"]
        check("store_join_rb", len(bindings) == 1 and bindings[0]["rb"] == "d::RB_X_V0")
        check("store_join_wf", bindings[0]["workflows"] == ["d::WF_X_V0"])
        check("store_join_cc", bindings[0]["consumer_ccs"] == ["d::CC_PERSIST_V0"])
        check("store_join_deterministic", build_store_index(ws) == index)


def test_store_index_pathless_binding() -> None:
    """A binding declaring no policy path binds no store — it must not join by accident."""
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        _fixture(ws)
        bindings = build_store_index(ws)["stores"]["d::ACTOR"]["declarations"][0]["bindings"]
        check("store_join_pathless_excluded", all(b["cs"] != "cse::CS_MAIL_V0" for b in bindings))


def test_store_index_empty_snapshot() -> None:
    """A composition declaring no stores is legal and yields an empty index, never a raise."""
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        _write(ws, "canonical/d/workflows/d__WF_X_V0.json",
               {"fqdn_id": "d::WF_X_V0", "artifact_type": "WF", "frontmatter": {"core": {}}})
        index = build_store_index(ws)
        check("store_empty_count", index["store_count"] == 0)
        check("store_empty_stores", index["stores"] == {})


def test_kind_index_reads_semantic_edges() -> None:
    """NODE_NEXT lives in evidence.json, not evidence_graph.json (the compile trace).

    Reading the trace file yielded zero matches and left cc_upstream/cc_downstream silently
    empty — a vacuous cross-reference that looked green. This pins the source.
    """
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        _fixture(ws)
        xrefs = build_kind_index(ws)["cross_references"]
        check("kind_index_downstream", xrefs["cc_downstream"] == {"d::CC_FIRST_V0": ["d::CC_PERSIST_V0"]})
        check("kind_index_upstream", xrefs["cc_upstream"] == {"d::CC_PERSIST_V0": ["d::CC_FIRST_V0"]})


def _republished_fixture(root: Path, consumer: str) -> None:
    """One identity published twice: the platform's authoring copy and a consumer's binding.

    The two differ exactly as the compiler emits them — `content_hash` and `frontmatter` identical,
    the binding carrying no authored `content` and no `references`, under the consuming layer.
    """
    for domain, layer, content, refs in (
        ("platform", "REUSABLE_SIDE_EFFECTS", "# CS_X_V0\n\n## 1. Intent\n", ["cse::CONSTITUTION_CSE_V0"]),
        (consumer, consumer.upper(), "", []),
    ):
        _write(root, f"canonical/{domain}/capability_side_effects/cse__CS_X_V0.json", {
            "fqdn_id": "cse::CS_X_V0",
            "artifact_type": "CS",
            "content": content,
            "content_hash": "7f1c0914",     # identical on both — the binding carries a hash of
            "references": refs,             # content it does not hold
            "layer_code": layer,
            "frontmatter": {"concern": "capability_side_effects"},
        })


def test_artifact_index_prefers_the_authoring_copy() -> None:
    """An identity published twice resolves to the copy that carries authored content.

    A domain consuming a platform capability carries it as an execution binding; both copies are
    canonical, and only the authoring one answers `si.artifact.show`, which promises the artifact
    "as authored".
    """
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        _republished_fixture(ws, "workload")
        entry = build_artifact_index(ws)["artifacts"]["cse::CS_X_V0"]
        check("artifact_index_resolves_to_authoring_copy",
              entry["canonical_path"].startswith("canonical/platform/"),
              f'got {entry["canonical_path"]}')


def test_artifact_index_resolution_is_not_alphabetical() -> None:
    """The same identity resolves the same way whatever the consuming domain is called.

    Selection was last-write-wins over a sorted walk, so a consumer sorting after `platform`
    (`workload`, `transformation`) won and one sorting before it (`blockchain`) lost. Resolution
    tracked domain naming, and renaming a domain would silently change what an identity returns.
    """
    resolved = {}
    for consumer in ("blockchain", "workload", "transformation"):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            _republished_fixture(ws, consumer)
            resolved[consumer] = build_artifact_index(ws)["artifacts"]["cse::CS_X_V0"]["canonical_path"]
    check("artifact_index_ignores_domain_name_order",
          len(set(resolved.values())) == 1 and all(
              p.startswith("canonical/platform/") for p in resolved.values()),
          str(resolved))


def main() -> None:
    for test in (
        test_store_index_join,
        test_store_index_pathless_binding,
        test_store_index_empty_snapshot,
        test_kind_index_reads_semantic_edges,
        test_artifact_index_prefers_the_authoring_copy,
        test_artifact_index_resolution_is_not_alphabetical,
    ):
        test()
    print(f"\nPASSED: {PASS}/{PASS + FAIL}")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
