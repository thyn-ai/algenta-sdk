# Changelog

All notable changes to the Algenta SDK (both `packages/python-sdk` and
`packages/ts-sdk`) are documented here. The two packages share one version
number, since they wrap one API contract.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Security

- Removed the client-side HS256 "dev license" verification path from the
  TypeScript SDK's `Runtime` local/offline mode. Only RS256 signatures
  verified against an embedded public key are now accepted; a symmetric
  secret can no longer be used to mint or verify a license client-side.
