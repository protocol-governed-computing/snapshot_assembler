# Architecture — `snapshot_assembler`

This document describes what this repository is, what it owns, and what it must never do. It is
written to be read before any code, and assumes no prior familiarity with Protocol-Governed
Computing.

For the big picture — what PGC is and how the repositories compose — see
**https://github.com/protocol-governed-computing**.

---

## 1. What this repo is

This is the **assembler**. The compiler produces one set of compiled output per domain. The
assembler takes those separate outputs and composes them into a **single sealed artifact** — the
snapshot — and gives it an identity derived from its contents.

The snapshot is the object the whole architecture turns on. Everything before it produces it;
everything after it consumes it and may not change it.

> A snapshot is not a build output among others. It is **the system, at one moment, in a form that
> can be named, checked, and executed** — and nothing else is.

**What this repo is not.** It does not compile anything, judge any declaration, or execute anything.
By the time material reaches the assembler it has already been ruled admissible. The assembler's job
is composition and sealing, and it is deliberately incapable of changing what it seals.

## 2. Where it sits

```
   each domain compiled separately            one sealed thing
   ────────────────────────────────           ────────────────

   software_governance  ──▶ compiled ─┐
   business domains     ──▶ compiled ─┼──▶  snapshot_assembler   ← YOU ARE HERE
   conformance workloads──▶ compiled ─┘             │
                                                    ▼
                                            ┌───────────────┐
                                            │   snapshot    │  sealed · identified
                                            │  manifest.json│  immutable
                                            └───────┬───────┘
                                                    │  read-only, by everything below
                                    ┌───────────────┼───────────────┐
                                    ▼               ▼               ▼
                            protocol_runtime  protocol_transport  snapshot_inspector
```

Note the shape: **many in, one out, then many readers.** This is the only place where the pieces
become a whole, which is why identity and verification live here rather than anywhere else.

## 3. Why sealing matters

A running system is normally a set of parts that happen to be deployed together, and answering *"what
exactly is running?"* means reconstructing it from versions, configs and environments.

A snapshot answers that question directly. It has a **content-derived identity**: change any
governed artifact anywhere in the composition and the identity changes. Two people comparing
snapshot identities are comparing the systems themselves, not their descriptions of them.

```
     composition of compiled parts
                 │
                 │   assemble
                 ▼
        ┌──────────────────┐
        │  snapshot_id     │ ◀── derived from content, not assigned
        │  composite_hash  │ ◀── the domain set, hashed
        │  provenance      │ ◀── what went in
        └──────────────────┘
                 │
        the manifest is the root of trust:
        everything else is checked against it
```

This is what makes the rest of the architecture expressible. To *pin* a baseline is to name a
snapshot. To ask whether two systems are the same is to compare two identities. To claim a build is
reproducible is to rebuild and get the same identity back.

## 4. What it owns, and what it must never do

**It owns:**

- composing many compiled domains into one snapshot;
- computing the snapshot's identity and writing the manifest;
- building the **indexes** that make the snapshot answerable — what artifacts exist, what kinds, what
  stores, what vocabulary, what evidence;
- **verifying its own output** before declaring success;
- running **composition conformance** — the rules that can only be checked once the parts are
  together.

**It must never:**

- **change what it seals.** The assembler composes and verifies; it does not edit, normalize, or
  repair. An artifact that arrives wrong is sealed wrong or refused, never quietly fixed.
- **judge a single artifact.** That already happened at compile time. The assembler judges only
  properties *of the composition*.
- **produce a snapshot it has not verified.** Assembly and verification are one act, not two steps
  someone might skip.

## 5. Composition-level checks

Some things cannot be wrong in a part and can only be wrong in a whole. Those are checked here.

**Round-trip verification.** The manifest's identity is recomputed from what was actually written and
compared with what was recorded. A mismatch means the snapshot on disk is not the snapshot that was
built, and the assembler refuses it.

**Copies must agree.** A governance artifact is compiled into *every* domain that imports it, so one
identity exists in the snapshot several times over. Nothing else checks that those copies match — and
they can silently diverge if a governance artifact is edited and only one domain is recompiled. The
assembler compares every copy of an identity by content and refuses a composition whose copies
disagree. This check exists because that failure occurred: five copies of one capability, in two
versions, in a composition that otherwise passed every gate.

**Composition conformance.** Rules that quantify over the whole composition — for example, that
exactly one artifact of a given kind may be active across all domains. These are declared by the
governance surface, not by this repository, and are read from the snapshot being assembled: **a
domain is checked against the governance it actually compiled under**, never against whatever this
tool happens to know.

## 6. What a snapshot contains

```
snapshot/
    manifest.json      identity, domain set, provenance   ← root of trust
    canonical/         the artifacts themselves
    behavior_logic/    execution graphs, and rendered diagrams of them
    artifact_index/    what exists, and where
    kind_index/        what kinds exist
    store_index/       what stores exist, and what consumes them
    vocabulary/        every named concept
    evidence/          why each artifact was admitted
    tokenized/         address-resolved forms
    trust/             attestation
    conformance/       the composition-conformance record
```

The indexes are not conveniences. They are what allow the composition to be *interrogated* rather
than read — a governed system that cannot answer questions about itself is governed only in
principle.

## 7. Layout

```
assemble.sh         assemble the compiled projections into a snapshot
                    PGC_SNAPSHOT_PROFILE is required — a snapshot names the profile it
                    claims (1b §11); there is no default (6a §8, §11)

assembler/
    core.py         composition, sealing, and the manifest-pinned identity
    indexes.py      the indexes that make a snapshot interrogable
    conformance.py  composition-level checks over the assembled result
    cli.py          the `snapshot_assembler` console script

scripts/testbed/    test_indexes.py — run explicitly, not pytest-collected
```

## 8. Rules this repo enforces

1. **A snapshot is sealed at assembly and never modified afterwards.** Downstream consumers read; none writes.
2. **Identity is derived from content**, never assigned, so two identical compositions have one identity.
3. **The manifest is the root of trust**; every other check is against it.
4. **No snapshot is emitted unverified.**
5. **Every copy of an artifact identity within a composition is identical.**
6. **Every domain declaring source must be compiled.** A missing domain is refused rather than
   silently assembled from stale output — the assembler names the command to run.

## 9. How to know it works

```bash
PGC_SNAPSHOT_PROFILE=REFERENCE_PLATFORM_PROFILE_V1 ./assemble.sh
```

A successful run reports the domains composed, the resulting `snapshot_id`, round-trip verification,
and the composition-conformance result. The strongest check available is reproducibility: delete
every build output, rebuild from committed source against the declared pinned inputs, and expect the
**same `snapshot_id`**. An identity that changes without a source change means something entered the
build that nobody declared.

## 10. Where the architecture is explained

This document describes *this repository*. The architecture it realizes is developed in the papers
indexed at **https://github.com/protocol-governed-computing**:

- **A Conceptual Model** — the protocol snapshot as the immutable admissibility boundary.
- **Realizing the Normative Platform and Its Governed Transformation** — why the snapshot is the
  hinge between what a system *is* and how it *changes*, and what sealing must mean operationally
  for the claim to hold.
- **An Architecture for Deterministic Declarative Execution** — what the runtime does with what is
  sealed here.
