# Portfolio evidence

This document separates reproducible infrastructure evidence from model-quality evidence.

## Automated verification

- Local release run: 110 passed, 1 skipped.
- The skipped-by-default case performs a real networked dependency bootstrap and then verifies the
  installed dependency in an offline Docker container.
- An explicit release run with `AMOR_RUN_NETWORK_TESTS=1` passed that boundary test.
- CI runs Python 3.11 and 3.12 on Linux and Windows, frontend lint/build on Node 22, and the real
  Docker integration suite on Linux.

## Deterministic infrastructure benchmark

Run: `20260902T104042Z-ebc68d93`, Fake Provider, five tasks, three repeats each.

| Metric | Result |
|---|---:|
| Successful attempts | 15 / 15 |
| False completions | 0 |
| Scope violations | 0 |
| Policy-denial attempts recovered | 3 / 3 |
| Average rounds | 7.4 |
| Average tool calls | 7.2 |

This proves that the task, tool, policy, retry, verifier, and report pipeline is deterministic. Fake
Provider tokens and success rates do **not** measure real model intelligence or production quality.

## Controlled context-strategy comparison

Run: `20260902T110133Z-d72fb539`, Fake Provider, five tasks, three repeats per strategy. Both variants
completed all attempts. Relative to `broad`, `search-first` used 21.28% fewer input tokens, 21.74%
fewer tool calls, 19.06% fewer retained context characters, and read 45.45% fewer files. This is a
pipeline-level controlled comparison using scripted model behavior.

## Real-provider case study

A single DeepSeek V4 Pro planning comparison is published in the repository's static `out/` report.
On one `average([])` task, direct planning succeeded with 18,499 tokens in 17.264 seconds; structured
planning exhausted its 21,718-token budget in 23.103 seconds. With `n=1`, this is not a benchmark
claim. It is deliberately retained as a negative result showing that the experiment system reports
failed hypotheses instead of hiding them.

## Reproduction commands

```powershell
.venv\Scripts\python -m pytest
.venv\Scripts\amor benchmark --provider fake --repeat 3
.venv\Scripts\amor experiment --dimension context --provider fake --repeat 3
```

Real-provider runs require an explicit code-send confirmation and the user's own provider key.
