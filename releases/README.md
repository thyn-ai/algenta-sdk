# Release verification metadata

`authorization/sdk-vX.Y.Z.json` is the signed release-authorization record
for that version: the exact commit in this repository, a SHA-256 digest of
the generated contract files, and an Ed25519 signature from Algenta's
private engine repository (`thyn-ai/algenta`). `.github/workflows/release.yml`
refuses to build or publish anything unless the tag it was triggered from,
the checked-out commit, the regenerated contract digest, and the signature
all agree with one of these files — see `scripts/verify_release_authorization.py`.

These records are delivered here automatically, as a reviewable pull
request, once the engine repo's private test suite has validated a
specific commit as releasable. They are not created directly in this
repository.

A `release-manifest.json` recording the published artifacts' SHA-256
hashes is attached to each version's [GitHub Release](https://github.com/thyn-ai/algenta-sdk/releases)
rather than committed here.
