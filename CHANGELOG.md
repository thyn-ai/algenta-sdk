# Changelog

All notable changes to the Algenta SDK (both `packages/python-sdk` and
`packages/ts-sdk`) are documented here. The two packages share one version
number, since they wrap one API contract.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Security

- Removed the client-side HS256 "dev license" verification path from the
  TypeScript SDK's `Runtime` local/offline mode. Only RS256 signatures are now
  accepted, verified against public keys loaded from the environment
  (`ALGENTA_LOCAL_LICENSE_PUBLIC_KEY` / `ALGENTA_LICENSE_PUBLIC_KEY`) or from
  key files (`ALGENTA_LOCAL_LICENSE_PUBLIC_KEY_FILE` /
  `ALGENTA_LICENSE_PUBLIC_KEY_FILE`); no verification key is embedded in the
  package. A symmetric secret can no longer be used to mint or verify a
  license client-side.

## [1.0.11] - 2026-08-20

### Added

- TypeScript SDK: `Runtime.extractColumns()` — typed, rowwise-aligned column
  extraction from connected local sources (local mode only), with `pairwise`
  and `preserve` null policies, conformance-tested against the Python SDK
  through checked-in vectors (`packages/ts-sdk/conformance/extraction_vectors.json`).
- TypeScript SDK: shared canonical JSON serialization used for plan and intent
  hashing, so `plan_hash` / `intent_signature` values are byte-identical
  across the Python and TypeScript SDKs.

### Changed

- TypeScript SDK: hardened local-runtime source handling and filter/group
  payload normalization in `Runtime` local mode.

## [1.0.10] - 2026-08-20

### Fixed

- TypeScript SDK: canonicalized aggregation names and aliases (`sum`, `avg`,
  `count`, `min`, `max`) in `Runtime` local-mode queries.
- TypeScript SDK: empty aggregations (`avg`, `min`, `max` over no rows) now
  return `null` instead of `NaN` or `±Infinity`, and grouped results order
  nulls deterministically.

### Added

- TypeScript SDK: query-plane parity tests pinning local-mode query behavior
  against the Python SDK.

## [1.0.9] - 2026-08-19

### Changed

- No SDK code changes. Version bump published to validate the corrected
  release pipeline: the release workflow now reads the authorization record
  from `main` rather than the tagged tree and can republish a pre-existing
  tag through the same verification gate.

## [1.0.8] - 2026-08-19

### Added

- First release cut from this public repository under the signed
  release-authorization gate: every `sdk-vX.Y.Z` tag is bound to its exact
  commit and a digest of the generated contract files by an Ed25519-signed
  record in `releases/authorization/`, verified before any publish by
  `scripts/verify_release_authorization.py`.

## Earlier releases

Versions 1.0.0–1.0.6 predate this repository — they were published from
Algenta's private monorepo before the public extraction, so per-version
detail is not reconstructible from this repository's history. Registry dates:

- **1.0.6** — 2026-07-24 (npm only).
- **1.0.5** — 2026-08-05 (PyPI), 2026-07-24 (npm).
- **1.0.4** — 2026-07-12.
- **1.0.3** — 2026-07-12.
- **1.0.2** — 2026-07-11.
- **1.0.1** — 2026-07-11 (npm only).
- **1.0.0** — 2026-07-08 (PyPI), 2026-07-10 (npm). First published release of
  both SDKs.

1.0.7 was never published to either registry.

[Unreleased]: https://github.com/thyn-ai/algenta-sdk/compare/sdk-v1.0.11...HEAD
[1.0.11]: https://github.com/thyn-ai/algenta-sdk/compare/sdk-v1.0.10...sdk-v1.0.11
[1.0.10]: https://github.com/thyn-ai/algenta-sdk/compare/sdk-v1.0.9...sdk-v1.0.10
[1.0.9]: https://github.com/thyn-ai/algenta-sdk/compare/sdk-v1.0.8...sdk-v1.0.9
[1.0.8]: https://github.com/thyn-ai/algenta-sdk/releases/tag/sdk-v1.0.8
