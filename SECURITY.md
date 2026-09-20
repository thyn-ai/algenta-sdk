# Security Policy

This repository contains Algenta's public Python and TypeScript client SDKs.
We take the security of the SDKs seriously and appreciate responsible
disclosure from the community.

## Supported versions

Security fixes land on `main` and in the latest published release of each
package (`algenta-sdk` on PyPI, `algenta-sdk` on npm).

| Channel | Supported |
| --- | --- |
| Latest release / `main` | :white_check_mark: |
| Older tagged releases | Best-effort; please upgrade to the latest |

## Reporting a vulnerability

**Please do not open a public issue, pull request, or discussion for
security problems.** Public disclosure before a fix is available puts other
users at risk.

Report privately through either channel:

1. **GitHub Security Advisories** (preferred) — open a private report from
   this repository's **Security → Report a vulnerability** tab.
2. **Email** — `security@algenta.ai`.

Please include, where possible: a description of the issue and its impact,
the affected component (Python SDK or TypeScript SDK, and which module),
steps to reproduce or a proof of concept, and the package version you tested.

## What to expect

- Acknowledgement within 3 business days.
- An initial assessment and severity triage within 7 business days.
- Regular updates as we work on a fix, and credit in the published advisory
  (unless you prefer to remain anonymous).
- Coordinated disclosure: we agree on a timeline with you and publish a
  GitHub Security Advisory once a fix is available.

## Scope

**In scope** — this repository's own code, including:

- Transport and auth handling in both SDKs (e.g. how credentials are sent,
  stored, or logged)
- The SDK's implementation of the OAuth device-authorization client flow —
  polling behavior, token storage, accidental token logging, local callback
  handling, validation, and transport security
- Deserialization, injection, or other memory/logic-safety bugs in SDK code
- Insecure defaults in either package

**Out of scope for this repository** (redirect privately to
`security@algenta.ai`, same as above, rather than filing here):

- The private control-plane license-issuance service
- Algenta engine entitlement/license enforcement itself
- Any private activation or relay infrastructure

We also want to be upfront about the trust model: the SDK is designed to be
**assumed untrusted** — a report showing that the SDK's own client-side
checks (e.g. an optional local-license preflight) can be bypassed by
modifying the SDK is informational, not a vulnerability, unless it also
demonstrates that the closed engine's independent, server-side entitlement
enforcement was bypassed. The engine, not this SDK, is the sole authority
over licensed capacity.

**Also out of scope:** third-party dependencies (report those upstream; we
still want to hear how they affect Algenta), and social-engineering,
physical, or denial-of-service testing against any hosted environment.

Thank you for helping keep Algenta and its users safe.
