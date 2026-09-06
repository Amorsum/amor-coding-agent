# Changelog

All notable changes to AMOR Coding Agent are documented here. The project follows
[Semantic Versioning](https://semver.org/).

## [1.0.1] - 2026-09-06

### Fixed

- Added a bounded Python search fallback so clean machines and CI runners do not require ripgrep.
- Matched the host UID/GID in Linux Docker containers so bind-mounted workspaces and dependency directories remain writable without root-owned output.
- Updated GitHub Actions to their Node 24-based major versions.

## [1.0.0] - 2026-09-06

First portfolio-ready local release.

### Added

- Independent, read-only acceptance planning followed by an explicitly approved and frozen contract.
- Isolated Git worktrees for implementation, verification, and optional delivery.
- OpenAI Responses and DeepSeek Responses providers plus deterministic scripted and fake providers.
- Python-first repository profiling, bounded file tools, path policy, command allowlists, progress guards, and token budgets.
- Per-task Docker command sandbox with no-network Agent and Verifier stages.
- Explicit PyPI-only dependency bootstrap in a separate container that never receives the target source tree or provider credentials.
- Protected snapshots for repositories with confirmed uncommitted changes.
- Local React workbench with live task events, contract revision, dependency consent, delivery, and artifact inspection.
- Reproducible benchmark and controlled strategy-experiment pipelines with redacted static reports.
- Reverified local-branch delivery and optional GitHub Draft PR publication.
- Cross-platform Python CI, frontend checks, and a real Docker security/integration job.
- A reproducible calculator repository for the interview demo.

### Security boundaries

- The interactive workbench is loopback-only and is not designed as a public multi-tenant service.
- API keys remain in process memory and are excluded from artifacts.
- Network access is limited to an explicitly approved dependency-bootstrap phase.

## [0.20.0] - 2026-09-06

- Added controlled Python dependency discovery and binary-wheel installation.
- Added `ENVIRONMENT_BLOCKED` outcomes and dependency-aware retry from the workbench.

## [0.19.0] - 2026-09-06

- Added repository preflight and protected snapshots for confirmed working-tree changes.
- Preserved the user's original checkout while planning and execution use isolated worktrees.

[1.0.1]: https://github.com/Amorsum/amor-coding-agent/releases/tag/v1.0.1
[1.0.0]: https://github.com/Amorsum/amor-coding-agent/releases/tag/v1.0.0
[0.20.0]: https://github.com/Amorsum/amor-coding-agent/compare/v0.19.0...v1.0.0
[0.19.0]: https://github.com/Amorsum/amor-coding-agent/commit/44ca601
