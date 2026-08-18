# snapshot_assembler

**Protocol-Governed Computing — snapshot assembler** (import package: `assembler`).

Composes each domain's compiled projections (from the protocol compiler) into one **executable
snapshot** with a content-derived, **manifest-pinned identity**. The runtime consumes only the
assembled snapshot — never an individual repo's compiled layout.

> The assembly contract — what a compiled projection must look like for the assembler to
> accept it — is governed by the standard, not by this repository.

```
repos → protocol_compiler → each repo's compiled/ projections
        → snapshot_assembler → protocol-governed-computing/snapshot/ → runtime warm reboot
```

The platform is an ordinary member of the composition — no singleton branch. The composition
currently assembles **seven domains**: `platform`, `workload`, `inspection`, `transformation`,
and the business domains `ai_governance`, `blockchain` and `book_library_mgmt`.

## Use

```bash
# assemble sibling platform compiled/ -> sibling snapshot/
./assemble.sh

# explicit / multi-source (future domains)
./assemble.sh --source /abs/software_governance/snapshot/compiled --out /abs/protocol-governed-computing/snapshot

# module form
PYTHONPATH=. python -m assembler.cli assemble --source <compiled_root> --out <snapshot_dir>
PYTHONPATH=. python -m assembler.cli verify  --out <snapshot_dir>
```

## Product

```
protocol-governed-computing/snapshot/
  manifest.json         # COMMITTED — the identity + root of trust
  tokenized/<domain>/   # regenerated build product (gitignored)
  trust/<domain>/       # regenerated build product (gitignored)
  vocabulary/<domain>/  # regenerated build product (gitignored)
```

- **`manifest.json` is the committed identity record.** The assembled projections are regenerated
  build products whose contents MUST match the manifest during warm reboot.
- **`composite_hash`** is content-derived over the identity view of `domains[]` (per-domain
  projection/attestation/graph hashes). Provenance and timestamps are excluded → same inputs +
  same compiler + same assembler ⇒ same identity.

## Composition conformance

Assembly does not end at the manifest. **Composition Conformance** is the lifecycle phase after it:
rules that can only be asked of the whole — the ones a single domain build contains no evidence for.
It runs on every assemble and its result is written to `conformance/composition.json`, so a snapshot
carries the record of having been judged as a composition rather than as a pile of domains.

## Scope

- **Copy and pin:** each domain's projections are copied, hashes are lifted from compiler output, the
  manifest is written, and round-trip `verify` runs after every `assemble`.
- **Vocabulary address-space reconciliation** remains the deferred real job. Collision detection is
  enforced today; composing the reconciled forward/reverse maps across domains is not yet done, and
  the composition has grown past the one-domain case that made it postponable.

## License

Apache-2.0.
