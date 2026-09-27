#!/usr/bin/env python3
"""
Transform conformance in the assembled snapshot — the assembler's half of
software_governance/dossiers/transform_conformance and software_governance/dossiers/platform_test_data.

Each build proves the transforms it supplies and writes what it found beside its compiled projections;
the assembler carries it. Shown here, against the snapshot the regression just assembled:

  * every build — each domain's, and the platform's — has its result carried to
    `transform_conformance/<build>/`, naming that build;
  * each result names every transform the build supplies, none refused, and names as carried exactly
    the transforms its attestation records as carried in — never judged by a transform's name;
  * the platform proves its own transforms: every one with a vector is proven, and each such vector is
    carried as a declaration beside the transforms, so what was proven is inspectable;
  * the result is kept apart from composition conformance, which alone occupies `conformance/`;
  * the result is a constituent: listed in the manifest with the hash of its bytes, so the snapshot's
    identity covers what its builds proved. In an admitted build the result follows from the
    declarations alone — a build with a failing case is never assembled — so it adds no instability,
    and excluding it would be a carve-out the identity's totality refuses.

Run: python scripts/testbed/test_transform_conformance_evidence.py [snapshot_root]
"""

import hashlib
import json
import sys
from pathlib import Path

W = Path(__file__).resolve().parents[3]
PLATFORM = "platform"
# The platform transform no inherited vector tests; it stays unproven until a change gives it one.
PLATFORM_UNPROVEN = ["capability_transforms::CT_PURE_COMPARE_EQUAL_V0"]

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


def _json(path: Path) -> dict:
    return json.loads(path.read_text())


def main(snapshot: Path) -> int:
    manifest = _json(snapshot / "manifest.json")
    builds = sorted(d["domain"] for d in manifest["domains"])
    constituents = {c["path"]: c["sha256"] for c in manifest["constituents"]}

    check("the snapshot composes the platform and domains built with conformance",
          PLATFORM in builds and len(builds) > 1, str(builds))
    for build in builds:
        rel = f"transform_conformance/{build}/result.json"
        path = snapshot / rel
        if not path.is_file():
            check(f"{build}: result carried", False, f"missing {rel}")
            continue
        result = _json(path)
        check(f"{build}: result carried, naming its build", result.get("domain") == build,
              f"names {result.get('domain')!r}")
        # Against the snapshot's own record of the build's transforms and of what it carried in, not
        # the result's arithmetic: a transform the result forgot would otherwise be uncounted.
        transforms = sorted(_json(f)["fqdn_id"]
                            for f in (snapshot / "canonical" / build / "capability_transforms").glob("*.json"))
        attestation = _json(snapshot / "trust" / build / "structure_attestation.json")
        carried = sorted(set(attestation.get("imported_capabilities", [])) & set(transforms))
        supplied = [t for t in transforms if t not in carried]
        named = sorted(result.get("proven", []) + result.get("unproven", []) + result.get("refused", []))
        check(f"{build}: every one of its {len(supplied)} supplied transform(s) is named, none refused",
              named == supplied and not result.get("refused"), f"named {named}, supplied {supplied}")
        check(f"{build}: the {len(carried)} carried transform(s) are those its attestation records",
              result.get("carried", []) == carried, f"result {result.get('carried')}, attested {carried}")
        check(f"{build}: result is a constituent the identity covers",
              constituents.get(rel) == hashlib.sha256(path.read_bytes()).hexdigest(),
              "absent from manifest constituents, or hashed differently")

    platform = _json(snapshot / "transform_conformance" / PLATFORM / "result.json")
    vectors = sorted(_json(f)["frontmatter"]["target"]
                     for f in (snapshot / "canonical" / PLATFORM / "test_data").glob("*.json"))
    check("the platform proves every transform it has a vector for, and no other",
          platform.get("proven") == vectors and platform.get("unproven") == PLATFORM_UNPROVEN,
          f"proven {platform.get('proven')}, vectors {vectors}, unproven {platform.get('unproven')}")
    check("every platform vector is carried as a declaration beside the transforms", len(vectors) > 0,
          "no platform vector in canonical/platform/test_data")
    composition = sorted(p.name for p in (snapshot / "conformance").iterdir())
    check("composition conformance alone occupies conformance/", composition == ["composition.json"],
          str(composition))

    print(f"\nPASSED: {PASS}/{PASS + FAIL}" if not FAIL else f"\nFAILED: {FAIL} of {PASS + FAIL}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else W / "snapshot"))
