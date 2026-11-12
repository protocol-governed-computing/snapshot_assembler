"""Snapshot authentication — a signature over a sealed snapshot's identity.

Three things are kept apart here, and conflating any two of them defeats the purpose:

    snapshot identity        `snapshot_id`, derived from what was sealed
    snapshot authentication  a signature over that identity
    trust anchor             a public key the verifying party holds, from outside the snapshot

Verification is `Verify(K, I, sigma)` where **K comes from the node and never from the
artifact**. A snapshot carrying the key that authenticates it is self-authenticating, which
establishes nothing: whoever replaced the snapshot would replace the key with it. The
`key_id` in a signature record exists only so a refusal can say *which* failure occurred —
signed by a key this node does not anchor, versus signed badly. It MUST NOT be used to
select a key.

**What is signed is the identity, not the manifest.** The self-description sits outside the
identity it declares, so signing the file would bind the signature to bytes the identity does
not cover. And the record is a sidecar rather than a manifest field, because a sealed
snapshot's manifest is written once and never rewritten.

**Asymmetric by requirement, not by preference.** A profile requiring that a node able to
verify is unable to sign rules out every shared-secret construction, whatever its strength.

The dependency is an extra (`snapshot_assembler[signing]`) rather than a core requirement.
Signing is something a profile selects; a platform whose profile does not select it should
not acquire a cryptography dependency because the capability exists elsewhere. Absent the
extra, this module refuses — it never degrades to an unsigned success.
"""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SIGNATURE_FILENAME = "signature.json"
SIGNATURE_VERSION = "V0"
ALGORITHM = "ed25519"

# Fields recorded beside the signature that the signature does not cover. `signed_at` says
# when signing happened; it is an accompanying fact, and covering it would make an identical
# snapshot produce a different record on every run.
ACCOMPANYING = ("signed_at",)


class SigningUnavailable(RuntimeError):
    """The signing extra is not installed. Never a reason to proceed unsigned."""


class SignatureError(RuntimeError):
    """Base for every refusal this module issues."""


class SignatureAbsent(SignatureError):
    """The snapshot carries no signature and the verifying party requires one."""


class SignatureMalformed(SignatureError):
    """A signature record exists and cannot be read as one."""


class TrustRootMismatch(SignatureError):
    """Signed by a key this party does not anchor. Distinct from a bad signature."""


class SignatureInvalid(SignatureError):
    """Anchored by the right key and the signature does not verify."""


class IdentityMismatch(SignatureError):
    """The signature authenticates an identity the snapshot does not claim."""


def _ed25519():
    """The primitives, or a refusal naming what to install.

    Imported here rather than at module scope so that reading this module, and importing the
    assembler at all, costs nothing when signing is not in use.
    """
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ed25519
    except ImportError as exc:  # pragma: no cover - exercised by absence, not by tests
        raise SigningUnavailable(
            "snapshot signing requires the 'signing' extra: "
            "pip install 'snapshot-assembler[signing]'"
        ) from exc
    return serialization, ed25519


def key_id(public_key_bytes: bytes) -> str:
    """A short, stable name for a public key.

    Identifies which anchor a record was produced under so that a refusal can distinguish a
    key this party does not hold from a signature that does not verify. It is a label, never
    a credential.
    """
    return hashlib.sha256(public_key_bytes).hexdigest()[:16]


def key_id_from_public_pem(public_pem: bytes) -> str:
    """The `key_id` of a PEM-encoded public key, for reporting at mint time."""
    serialization, _ = _ed25519()
    return key_id(_raw_public(serialization.load_pem_public_key(public_pem)))


def generate_keypair() -> tuple[bytes, bytes]:
    """A new Ed25519 pair as (private_pem, public_pem).

    The private half belongs on the machine that seals snapshots and on no machine that
    executes them: a node able to sign can mint a snapshot its peers would accept.
    """
    serialization, ed25519 = _ed25519()
    private = ed25519.Ed25519PrivateKey.generate()
    private_pem = private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem, public_pem


def _raw_public(public_key) -> bytes:
    serialization, _ = _ed25519()
    return public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def sign_identity(snapshot_id: str, private_key_path: Path) -> dict[str, Any]:
    """Produce the signature record for a sealed snapshot's identity."""
    serialization, _ = _ed25519()
    private = serialization.load_pem_private_key(
        Path(private_key_path).read_bytes(), password=None
    )
    signature = private.sign(snapshot_id.encode("utf-8"))
    return {
        "signature_version": SIGNATURE_VERSION,
        "snapshot_id": snapshot_id,
        "algorithm": ALGORITHM,
        "key_id": key_id(_raw_public(private.public_key())),
        "signature": base64.b64encode(signature).decode("ascii"),
        "signed_at": datetime.now(timezone.utc).isoformat(),
    }


def write_signature(out_root: Path, record: dict[str, Any]) -> Path:
    """Write the sidecar beside the manifest, leaving the manifest untouched."""
    path = Path(out_root) / SIGNATURE_FILENAME
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def read_signature(out_root: Path) -> dict[str, Any] | None:
    """The signature record, or None where the snapshot carries none."""
    path = Path(out_root) / SIGNATURE_FILENAME
    if not path.exists():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SignatureMalformed(f"{path} is not readable as JSON: {exc}") from exc
    if not isinstance(record, dict):
        raise SignatureMalformed(f"{path} does not carry a signature record")
    return record


def verify_identity(snapshot_id: str, record: dict[str, Any], public_key_path: Path) -> str:
    """Verify a signature over a claimed identity against a party-supplied anchor.

    Returns the `key_id` of the anchor on success. Raises one of this module's refusals
    otherwise, each naming which of the four failures occurred: the record authenticates a
    different identity, it was produced under a key this party does not anchor, the record is
    unreadable, or it does not verify.

    The anchor is the caller's. `record["key_id"]` is read only to report a mismatch.
    """
    serialization, ed25519 = _ed25519()

    for field in ("snapshot_id", "algorithm", "signature"):
        if field not in record:
            raise SignatureMalformed(f"signature record carries no {field!r}")

    if record["algorithm"] != ALGORITHM:
        raise SignatureMalformed(
            f"signature algorithm is {record['algorithm']!r}; this verifier knows {ALGORITHM!r}"
        )

    # Checked before the cryptography: a record that verifies over a different identity is
    # valid and irrelevant, and reporting it as a bad signature would name the wrong fault.
    if record["snapshot_id"] != snapshot_id:
        raise IdentityMismatch(
            f"signature authenticates {record['snapshot_id'][:16]}… and this snapshot claims "
            f"{snapshot_id[:16]}…"
        )

    public = serialization.load_pem_public_key(Path(public_key_path).read_bytes())
    if not isinstance(public, ed25519.Ed25519PublicKey):
        raise SignatureMalformed(f"{public_key_path} is not an Ed25519 public key")
    anchor = key_id(_raw_public(public))

    borne = record.get("key_id")
    if borne and borne != anchor:
        raise TrustRootMismatch(
            f"signed under key {borne} and this party anchors {anchor} — the signature may be "
            f"sound and is not one this party accepts"
        )

    try:
        signature = base64.b64decode(record["signature"], validate=True)
    except (ValueError, TypeError) as exc:
        raise SignatureMalformed(f"signature is not valid base64: {exc}") from exc

    try:
        public.verify(signature, snapshot_id.encode("utf-8"))
    except Exception as exc:
        raise SignatureInvalid(
            f"signature over {snapshot_id[:16]}… does not verify under key {anchor}"
        ) from exc

    return anchor
