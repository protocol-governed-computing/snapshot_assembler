## Response Style

Keep responses under ~400 output tokens. Prefer terse bullet summaries over prose narration. When a full document is needed, Write it to a file instead of printing it in chat.

## Document Authoring Rules

- Never include internal review notes, meta-scaffolding, work-order framing, cross-reference stubs, or 'Status:' metadata in deliverable docs or figures.
- Do not add dates to papers or appendices.
- An 'outline' means a clean reader-facing outline of the paper, not an execution plan.

# Snapshot Assembler (PGC) — Architectural Rules

## What this repo is

Composes each domain's compiled projections into **one executable snapshot** with a
content-derived, manifest-pinned identity. The runtime consumes only the assembled snapshot, never
an individual repo's compiled layout.

- **Repo:** `snapshot_assembler`. **Import package:** `assembler` — the org provides the namespace.
- **Contract:** `snapshot_assembler/CONTRACT.md` — the path four modules cite
  in `boot.py`, `loader.py`, `assembler/__init__.py` and `assembler/core.py`.

```
repos → protocol_compiler → each repo's compiled/ projections
      → snapshot_assembler → protocol-governed-computing/snapshot/ → runtime warm reboot
```

## The assembler's remit — correctness AND indexing of the composition

The division of responsibility across the toolchain:

| Component | Owns |
|---|---|
| `protocol_compiler` | correctness of an **individual domain** |
| `snapshot_assembler` | correctness **and indexing** of the **composed snapshot** |
| `snapshot_inspector` | read-only query interface over that snapshot |

**The assembler produces an *inspectable* snapshot, not merely an executable one.** An index is a
composition-level fact — no single domain build can compute one — which is why all three indexes
live here and none in the compiler:

- `artifact_index/index.json` — FQDN → domain / kind / owner_subdomain / canonical_path / addresses
- `kind_index/index.json` — by-kind cross-reference database
- `store_index/index.json` — store → owning STRUCTURE, declared path, binding surface

## Composition Conformance

A **lifecycle phase**, not an assembler feature. Four design constraints, all load-bearing:

1. *The assembler does not become the thing that checks invariants.* `core.assemble()` is untouched;
   the phase is a separate module (`conformance.py`) and a separate CLI verb (`conform`).
2. *No dependency on the compiler.* Rules are read from the assembled snapshot's own canonical
   invariants, never from the compiler's handler registry. **`snapshot_assembler` imports nothing
   from `compiler`.**
3. *No implementation semantics in the declaration.* An invariant declares a language-neutral
   `composition_check` — a selector plus a cardinality rule. It names no handler, module or
   callable.
4. *Admission by declaration.* An invariant participates iff it declares `composition_check`;
   nothing here enumerates which invariants exist.

Extending the rule vocabulary or the selector is **a declaration act in `SCHEMA_INVARIANT_V0` plus
one table entry** — never a special case inside the evaluator.

Evidence is written to `conformance/composition.json` **before** raising: a failed composition must
leave a record of *why*, not just a non-zero exit. Every rule records `examined`, so a vacuous
check is visible by construction.

## Read the semantic graph, not the compile trace

`evidence/<domain>/evidence.json` is the **semantic** graph (typed, FQDN-keyed edges:
`NODE_NEXT`, `WF_BINDS_RB`, `CC_BINDS_CS`, …). Its sibling `evidence_graph.json` is the **compile
trace** (`STAGE_SEQUENCE` / `CAUSALITY`, keyed by event id) and carries no artifact-level edges.

Reading the wrong one yields an empty result, not an error. `kind_index.cross_references` was `{}`
for two releases because of exactly this, hidden by a `try/except: continue`. **Fail hard on a
malformed evidence file; never fall back.**

## Identity

- The assembler **INVENTS no per-domain identity** — every hash is lifted verbatim from compiler
  output and cross-checked.
- `composite_hash` is content-derived over the identity view of `domains[]`; only
  tokenized/vocabulary/trust feed it. Provenance and timestamps do not.
- `snapshot_id` attests **identity, not content**. Do not treat it as a content seal.
- Governance provenance is verified against the assembled surface: a domain compiled against a
  different governance closure is rejected at assembly, by design.

## Auto-discovery

`assemble.sh` with **no arguments** discovers the governance surface, every compiled workload,
every business domain and every tool domain. **Any argument bypasses discovery entirely**
(`exec … assemble "$@"`), so an explicit `--source` list becomes the complete source set and
silently omits domains added later. Prefer no arguments.

## Import rules (MANDATORY)

- Absolute, fully-qualified from `assembler.*`. No relative imports.
- **No `compiler.*`, no `runtime.*`, no `inspector.*`, no `pgs_*`, no domain imports.** The
  assembler reads the compiled on-disk format — an input contract — never the tools that produced it.
- Stdlib only.

## Workflow rules (MANDATORY)

Diagnose → plan → **get approval before multi-file changes.** Present the complete file list first.

## Testbed

`scripts/testbed/test_indexes.py` — not pytest-collected; run it explicitly:
`python3 scripts/testbed/test_indexes.py`.

## One-line summary

Composes compiled projections into one identity-pinned snapshot and indexes it; invariants are
evaluated from the snapshot's own declarations, never from the compiler; the assembler produces an
inspectable snapshot, and invents no identity of its own.
