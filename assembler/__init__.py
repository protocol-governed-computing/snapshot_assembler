"""PGC Snapshot Assembler — composes compiled projections into a manifest-pinned snapshot.

Contract: standards/doc/SNAPSHOT_ASSEMBLY_CONTRACT.md
"""

from pathlib import Path


def _release() -> str:
    """The composition's release ordinal, read from the repo's single version declaration.

    PGC versions the *composition*, not each repo independently: all repos are released together
    and the governance closure forces lockstep, so a monotonic integer names which composition a
    repo belongs to. `VERSION` is the sole declaration — pyproject derives it, and so does this.
    Never restate it as a literal; two statements of one fact is how they drift apart.
    """
    return (Path(__file__).resolve().parent.parent / "VERSION").read_text(encoding="utf-8").strip()


ASSEMBLER_VERSION = _release()   # derived from VERSION — never edited here
MANIFEST_VERSION = "v0"
