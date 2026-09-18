"""Verifies a release-authorization record before release.yml is allowed to publish anything.

This is the only thing standing between "someone pushed a sdk-vX.Y.Z tag" and
"this workflow uploads to PyPI/npm with real credentials." It must refuse to
publish unless ALL of:

  1. The tag's version matches the authorization's version.
  2. The checked-out commit (git rev-parse HEAD) matches the authorization's sdk_commit.
  3. The independently-recomputed contract-file digest matches the authorization's
     contract_sha256 (computed by THIS script from the checked-out tree, never
     trusted from the authorization file itself).
  4. The authorization's Ed25519 signature verifies against the embedded Algenta
     public key.

Authorizations are produced exclusively by the signing tool in Algenta's
private engine repository; this script only ever verifies them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from base64 import b64decode
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

# Public half of the engine repo's release-signing keypair. Safe to embed --
# it can only verify signatures, never create them. Rotate by adding a new
# kid-keyed entry here rather than replacing this one outright, so
# already-authorized-but-not-yet-tagged releases don't break mid-rotation.
TRUSTED_PUBLIC_KEYS: dict[str, str] = {
    "sdk-release-2026-08": """-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEA8YwNolHIvpsbTo/mV/owK0Cl8wfTge21IHpyVCu1VaA=
-----END PUBLIC KEY-----
""",
}

CONTRACT_FILES = (
    "packages/python-sdk/decision_engine/_contract.py",
    "packages/ts-sdk/src/contract.ts",
)


class AuthorizationInvalid(Exception):
    pass


def canonical_bytes(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def compute_contract_digest(repo_root: Path) -> str:
    """Combined digest over both generated contract files, in a fixed order --
    must match exactly how the engine repo's signer computed it."""
    hasher = hashlib.sha256()
    for rel_path in CONTRACT_FILES:
        hasher.update((repo_root / rel_path).read_bytes())
    return hasher.hexdigest()


def git_head(repo_root: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo_root, capture_output=True, text=True, check=True
    ).stdout.strip()


def verify(authorization: dict, *, expected_version: str, repo_root: Path) -> None:
    actual_commit = git_head(repo_root)
    if authorization.get("sdk_repo") != "thyn-ai/algenta-sdk":
        raise AuthorizationInvalid(f"wrong sdk_repo: {authorization.get('sdk_repo')!r}")
    if authorization.get("version") != expected_version:
        raise AuthorizationInvalid(
            f"version mismatch: tag says {expected_version!r}, authorization says {authorization.get('version')!r}"
        )
    if authorization.get("sdk_commit") != actual_commit:
        raise AuthorizationInvalid(
            f"commit mismatch: HEAD is {actual_commit!r}, authorization says {authorization.get('sdk_commit')!r}"
        )

    actual_contract_digest = compute_contract_digest(repo_root)
    if authorization.get("contract_sha256") != actual_contract_digest:
        raise AuthorizationInvalid(
            "contract digest mismatch: the checked-out contract files don't match what was authorized "
            f"(recomputed {actual_contract_digest!r}, authorization says {authorization.get('contract_sha256')!r})"
        )

    key_id = authorization.get("key_id")
    key_pem = TRUSTED_PUBLIC_KEYS.get(key_id)
    if key_pem is None:
        raise AuthorizationInvalid(f"unknown key_id: {key_id!r} -- not in the embedded trust set")
    public_key = load_pem_public_key(key_pem.encode("ascii"))
    if not isinstance(public_key, Ed25519PublicKey):
        raise AuthorizationInvalid(f"key_id {key_id!r} is not an Ed25519 key")

    signature_b64 = authorization.get("signature")
    if not signature_b64:
        raise AuthorizationInvalid("no signature present")
    payload = {k: v for k, v in authorization.items() if k != "signature"}
    try:
        public_key.verify(b64decode(signature_b64), canonical_bytes(payload))
    except InvalidSignature:
        raise AuthorizationInvalid("signature verification failed") from None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorization-file", required=True, type=Path)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--repo-root", default=".", type=Path)
    args = parser.parse_args()

    authorization = json.loads(args.authorization_file.read_text())
    try:
        verify(authorization, expected_version=args.expected_version, repo_root=args.repo_root)
    except AuthorizationInvalid as exc:
        print(f"::error::Release authorization REJECTED: {exc}", file=sys.stderr)
        sys.exit(1)

    print("Release authorization verified: version, commit, contract digest, and signature all match.")


if __name__ == "__main__":
    main()
