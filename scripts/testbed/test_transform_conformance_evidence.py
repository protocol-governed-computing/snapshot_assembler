#!/usr/bin/env python3
"""
Transform conformance in the assembled snapshot — the assembler's half of
software_governance/dossiers/transform_conformance.

Each domain's build proves its transforms and writes what it found beside its compiled projections;
the assembler carries it. Shown here, against the snapshot the regression just assembled:

  * every domain built with conformance has its result carried to `transform_conformance/<domain>/`,
    naming that domain;
  * the result is kept apart from composition conformance, which alone occupies `conformance/`;
  * the result is a constituent: listed in the manifest with the hash of its bytes, so the snapshot's
    identity covers what its domains proved. In an admitted build the result follows from the
    declarations alone — a build with a failing case is never assembled — so it adds no instability,
    and excluding it would be a carve-out the identity's totality refuses.

The platform is absent by decision: its build carries no conformance (STRUCTURE_BUILD_PLATFORM_CONFIG_V1),
because the platform does not own a domain's implementations.

Run: python scripts/testbed/test_transform_conformance_evidence.py [snapshot_root]
"""

import hashlib
import json
import sys
from pathlib import Path

W = Path(__file__).resolve().parents[3]
PLATFORM = "platform"

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


def main(snapshot: Path) -> int:
    manifest = json.loads((snapshot / "manifest.json").read_text())
    domains = sorted(d["domain"] for d in manifest["domains"] if d["domain"] != PLATFORM)
    constituents = {c["path"]: c["sha256"] for c in manifest["constituents"]}

    check("the snapshot composes domains built with conformance", bool(domains), str(domains))
    for domain in domains:
        rel = f"transform_conformance/{domain}/result.json"
        path = snapshot / rel
        if not path.is_file():
            check(f"{domain}: result carried", False, f"missing {rel}")
            continue
        result = json.loads(path.read_text())
        check(f"{domain}: result carried, naming its domain", result.get("domain") == domain,
              f"names {result.get('domain')!r}")
        # Against the snapshot's own record of the domain's transforms, not the result's arithmetic: a
        # transform the result forgot would otherwise be neither proven nor unproven, and uncounted.
        own = sorted(json.loads(f.read_text())["fqdn_id"]
                     for f in (snapshot / "canonical" / domain / "capability_transforms").glob("*.json")
                     if f.name.startswith(f"{domain}__"))
        named = sorted(result.get("proven", []) + result.get("unproven", []) + result.get("refused", []))
        check(f"{domain}: every one of its {len(own)} transform(s) is named, none refused",
              named == own and not result.get("refused"), f"named {named}, declared {own}")
        check(f"{domain}: result is a constituent the identity covers",
              constituents.get(rel) == hashlib.sha256(path.read_bytes()).hexdigest(),
              "absent from manifest constituents, or hashed differently")

    check("no result is carried for the platform, whose build runs no conformance",
          not (snapshot / "transform_conformance" / PLATFORM).exists())
    composition = sorted(p.name for p in (snapshot / "conformance").iterdir())
    check("composition conformance alone occupies conformance/", composition == ["composition.json"],
          str(composition))

    print(f"\nPASSED: {PASS}/{PASS + FAIL}" if not FAIL else f"\nFAILED: {FAIL} of {PASS + FAIL}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else W / "snapshot"))
