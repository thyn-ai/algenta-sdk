# Release verification metadata

`authorization/sdk-vX.Y.Z.json` is the signed release-authorization record
for that version: the exact commit in this repository, a SHA-256 digest of
the generated contract files, and an Ed25519 signature from Algenta's
private engine repository. `.github/workflows/release.yml`
refuses to build or publish anything unless the tag it was triggered from,
the checked-out commit, the regenerated contract digest, and the signature
all agree with one of these files — see `scripts/verify_release_authorization.py`.

## History note (September 2026)

Before this repository was made public, its git history was rewritten once to
remove accidentally committed third-party fixture data (`test_files/`). Commit
SHAs changed as a result. The authorization records for 1.0.8–1.0.11 below
still reference the pre-rewrite commits they were signed for; those commits
are archived outside this repository. Authorizations from the next release
onward bind commits in the rewritten history, and the published PyPI/npm
artifacts for 1.0.8–1.0.11 are unaffected.

These records are delivered here automatically, as a reviewable pull
request, once the engine repo's private test suite has validated a
specific commit as releasable. They are not created directly in this
repository.

A `release-manifest.json` recording the published artifacts' SHA-256
hashes is attached to each version's [GitHub Release](https://github.com/thyn-ai/algenta-sdk/releases)
rather than committed here.
