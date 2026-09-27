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
currently assembles **eight domains**: `platform`, `workload`, `inspection`, `transformation`,
and the business domains `ai_governance`, `blockchain`, `book_library_mgmt` and
`causal_language_model`. A deliberately narrower composition is assembled by naming its roots in
`PGC_SOURCE_ROOTS`.

## Install

```bash
pip install pgc-assembler
```

Once installed:

```bash
snapshot_assembler --help
```

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

---

## The package family

| Package | Repository | Role |
|---|---|---|
| `pgc-compiler` | `protocol_compiler` | declarations → compiled projections |
| `pgc-assembler` | `snapshot_assembler` | projections → sealed snapshot |
| `pgc-runtime` | `protocol_runtime` | snapshot → governed execution |
| `pgc-inspector` | `snapshot_inspector` | snapshot → read-only inspection |
| `pgc-transformation` | `transformation` | change request → protocol artifacts |
| `pgc-governance` | `software_governance` | the governance surface and its capability implementations |
| `pgc-workloads` | `conformance_workloads` | the workloads that make conformance observable |
| `pgc-domains` | `business_domains` | the business domain implementations the composed snapshot binds |

`pip install protocol-governed-computing` brings in the whole family.

**Installing the toolchain is one of two steps.** The compiler resolves the governance surface from
`PGC_PLATFORM_ROOT` — fail-hard, cwd-independent, zero inference — so the *declarations* come from a
repository you point at, never from a wheel. A registry inside a package would be a second governance
surface competing with the repository's, and a build could then be governed by a stale copy.

```bash
git clone https://github.com/protocol-governed-computing/software_governance
export PGC_PLATFORM_ROOT=$PWD/software_governance
pgc            # reports what is installed and whether the anchor resolves
```

`PGC_DOMAIN_ROOTS` names an additional domain contributing its own `registry/structures` — the
directory that *directly contains* it, not the repository above it; pointing one level too high is a
silent no-op. `PGC_SNAPSHOT_ROOT` is where compiled output is written, and each domain build needs
its own: every layer's output consolidates into one root, and verification rejects any file in that
root the current build did not declare. `PGC_SNAPSHOT_PROFILES` is the directory holding snapshot
profiles, required by the assembler and the runtime alike.

`PGC_BUILD_ROOT` is accepted and reported and **nothing reads it** — `PGC_SNAPSHOT_ROOT` is the
anchor that controls output.

The full sequence, with the repositories it needs, is in
[`pgc_install`](https://github.com/protocol-governed-computing/pgc_install).

**Versioning.** Two schemes, and the published version follows the second.

- **Internal** — each repository's `VERSION` file, a monotonic composition ordinal. PGC versions the
  composition rather than each repo: they release together and the governance closure forces lockstep,
  so the ordinal names which composition a repo belongs to. Development happens on `dev/<N>` and each
  cycle is tagged `release-<N>`. This is not published.
- **Public** — `PUBLIC_VERSION`, tagged on every component repository. The platform is at **`v3`**.

**The published version is the public one: `v4` is `4.0.0`.** The standard the packages implement is a
separate artifact on its own track and is not this number.

The standard these packages implement is published separately: https://doi.org/10.5281/zenodo.22150616
