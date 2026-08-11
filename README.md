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

`{platform}` is an ordinary **one-member composition** — no singleton branch.

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

## Scope

- **Now (N=1):** near-identity — copy each domain's projections, lift hashes from compiler output,
  write the manifest. Round-trip `verify` runs after every `assemble`.
- **N ≥ 2 (future):** **vocabulary address-space reconciliation** — collision detection is already
  enforced; composing the reconciled forward/reverse maps is the deferred real job.

## License

Apache-2.0.
