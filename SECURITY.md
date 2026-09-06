# Security policy

## Supported version

Security fixes are made against the latest release on `main`.

## Intended deployment boundary

AMOR is a local, single-user developer tool. Keep the workbench bound to a loopback address.
Do not expose it directly to a LAN or the public internet, and do not use it as a multi-tenant
service. Prefer the Docker sandbox for repositories you did not author; host mode is a
compatibility option for trusted code only.

Dependency installation is opt-in. The bootstrap container receives validated package
requirements but does not receive the repository, provider keys, the user's home directory,
or the Docker socket. Agent and Verifier containers run without network access.

## Reporting a vulnerability

Please use GitHub's private **Security advisories → Report a vulnerability** flow for this
repository. Include the affected version, reproduction steps, expected impact, and any
suggested mitigation. Do not open a public issue for an unpatched credential exposure or
sandbox escape.
