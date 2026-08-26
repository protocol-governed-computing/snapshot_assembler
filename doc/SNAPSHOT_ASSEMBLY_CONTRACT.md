# PGC Snapshot Assembly Contract

- **Governed by:** `standards/spec/3b_snapshot.md` (what an assembled snapshot must be),
  `standards/spec/4b_projection.md` (the compiled projections it composes)

---

## Principle

**The snapshot is the product. Repositories are inputs. The runtime consumes an assembled
snapshot — never an individual repo's compiled layout.**

```
source repos → protocol_compiler → each repo's compiled/ projections
                                          │
                                          ▼
                                   SNAPSHOT ASSEMBLER      (composes the domain set + manifest)
                                          │
                                          ▼
                      protocol-governed-computing/snapshot/    (the product)
                                          │
                                          ▼
                                   runtime  →  warm reboot
```

- `{platform}` is an **ordinary one-member composition** — no singleton branch, no special
  platform runtime. `{platform, blockchain, ai_governance, …}` uses the *same* assembly.
- **transformation / change-mgmt** feeds the **compiler** (admitted protocol deltas), not the
  assembler. **transport** wraps the **runtime**, produces no projection. Neither is an
  assembler input. The assembler's only inputs are **compiled projections from the protocol
  compiler**.

---

## Assembled snapshot layout (the product)

```
protocol-governed-computing/snapshot/
  manifest.json            ← COMMITTED. The identity + root of trust.
  tokenized/<domain>/      ← regenerated build output (gitignored)
  trust/<domain>/          ← regenerated build output (gitignored)
  vocabulary/<domain>/     ← regenerated build output (gitignored)
```

- **Identity model (Option 1, locked):** **the manifest is the committed identity record. The
  assembled projections are regenerated build products whose contents MUST match the manifest
  during warm reboot.** (A committed manifest alone is *not* sufficient to reconstruct the
  snapshot — it *pins* and *verifies* the projections; reproduction requires the inputs recorded
  in `provenance`.)
- **Tool vs product home (kept conceptually separate):**
  ```
  snapshot_assembler/      # the tool (code)
          │
          ▼
  snapshot/                # the assembled product (manifest committed; projections regenerated)
  ```
  Whether `snapshot_assembler/` earns a permanent standalone repo is validated by the second
  domain — deferred.

---

## `manifest.json` schema (v0)

```json
{
  "manifest_version": "v0",
  "snapshot_id": "<composite_hash>",
  "composite_hash": "<sha256 hex>",
  "domains": [
    {
      "domain": "platform",
      "compiler_version": "0.9.0",
      "graph_address_hash": "ec023c23166ac7c3fc0548c9e00136111ac820506bc62eaf8d37671126c74217",
      "projections": {
        "tokenized":  { "path": "tokenized/platform",  "projection_hash": "1dbce6ef642a007cff5e590126f57247fed72b53d62c91325fcc1fb4aeca86aa" },
        "vocabulary": { "path": "vocabulary/platform", "projection_hash": "955c792ef5e380213bf499ae3e7484084019b88e21dc22bece67f6143b59330d" },
        "trust":      { "path": "trust/platform",      "attestation_hash": "d9890484429bd7b2927fa0f100ac00bf31184310ace4eb78f2c3b9ab48f4b80b",
                                                       "tokenized_projection_hash": "1dbce6ef642a007cff5e590126f57247fed72b53d62c91325fcc1fb4aeca86aa" } }
    }
  ],
  "provenance": {
    "assembler_version": "0.1.0",
    "assembled_at": "2026-07-22T05:24:07Z",
    "source_commits":    { "platform": "<git sha>", "protocol_compiler": "<git sha>" },
    "compiler_versions": { "platform": "0.9.0" }
  }
}
```

- **The assembler INVENTS no per-domain identity.** Every domain hash is *lifted verbatim* from
  what the compiler already emits: `tokenized/<d>/metadata.json.projection_hash`,
  `vocabulary/<d>/metadata.json.projection_hash`, `trust/<d>/structure_attestation.json`
  (`attestation_hash`, `tokenized_projection_hash`), `graph_address_hash`.

### Identity vs reproducibility (normative)

**The manifest's identity is content-derived from the emitted projection hashes. `provenance` is
non-identity metadata, but it MUST be sufficient to reproduce or audit the projections.** The MNP
fields (`assembler_version`, `assembled_at`, `source_commits`, `compiler_versions`) are adequate
for `{platform}`, but the distinction is explicit: as inputs or build configuration gain degrees
of freedom, `provenance` MUST grow to capture whatever is needed to reproduce the exact projections
— e.g. source repository commit(s), protocol compiler commit, compiler version, assembler version,
and relevant build/configuration identity. Do not overdesign now; do not let `provenance` bleed
into the composite hash.

---

## Composite hash — content-derived, deterministic (PATCH, locked)

```
same source inputs  +  same compiler  +  same assembler   →   same composite_hash
```

- **`composite_hash = sha256(canonical_digest)`** where `canonical_digest` is the canonical-JSON
  (sorted keys, no whitespace) serialization of the **identity view** of `domains[]`:
  for each domain, the tuple
  `(domain, tokenized.projection_hash, vocabulary.projection_hash, canonical.projection_hash,
  trust.attestation_hash, graph_address_hash)`,
  with domains sorted by `domain`.
- **Why `canonical` is included.** The other members are all graph-derived, and STRUCTURE artifacts
  never enter the semantic graph — they are read as build configuration and materialized alongside
  it. Without `canonical.projection_hash`, a STRUCTURE artifact could change inside a sealed
  snapshot while the identity remained byte-identical and every integrity check still passed.
  STRUCTURE is the configuration authority for the whole system, so it is the class of artifact the
  identity can least afford to miss. Every hash is still the compiler's own statement, lifted
  verbatim — the assembler invents no identity.
- **`snapshot_id == composite_hash`.**
- **EXCLUDED from the composite:** `provenance` (all of it), `assembled_at`, any timestamp, file
  paths. Timestamps are **metadata only** — identical inputs must not yield different identities
  merely because they were built at different times.

---

## Root of trust — boot sequence (PATCH, locked)

The **manifest is the root of trust.** The runtime boots *through* it, never by scanning the
filesystem.

```
runtime
  └─ 1. load manifest.json
     2. recompute composite_hash from domains[] identity view  →  MUST equal manifest.composite_hash
            (self-consistency; detects domain-set tampering)
     3. for each domain in manifest.domains:
            load tokenized/trust/vocabulary from the declared paths
            verify tokenized metadata.projection_hash
                   == manifest tokenized.projection_hash
                   == trust.tokenized_projection_hash          (existing loader check, now anchored to the manifest)
            verify vocabulary metadata.projection_hash == manifest vocabulary.projection_hash
     4. build one RuntimePackage per domain
     5. warm reboot complete  =  all manifest domains resident + hash-verified
```

Any mismatch → hard failure. No silent skip, no fallback (Zero Inference / Fail Hard).

---

## Assembler responsibilities

- **N = 1 (now):** near-identity. Copy/link each domain's compiled projections into
  `snapshot/<projection>/<domain>/`, lift per-domain hashes from emitted metadata, compute the
  content-derived composite, write `manifest.json`. No semantic merge.
- **N ≥ 2 (future — where the assembler earns its keep):** **vocabulary address-space
  reconciliation** — detect integer-address collisions across domains, compose the composite
  forward/reverse maps, resolve cross-domain references. The per-structure compiler cannot own
  this (it compiles one structure); the runtime must not. This is the assembler's real,
  latent-while-N=1 job — and why assembly is a first-class concern, not identity.

---

## Invariants / non-goals

- Runtime **never** reads an individual repo's compiled layout — only the assembled snapshot via
  the manifest.
- No timestamp in identity.
- No singleton special case; `{platform}` is one-member composition.
- Assembler stays **thin** until the second domain lands.
