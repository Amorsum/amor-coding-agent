# AMOR demo task

## Task

修复 `average` 在空列表输入时抛出 `ZeroDivisionError` 的问题，同时保持现有非空输入行为不变。

## Known acceptance criteria

- `average([])` returns `0.0`.
- `average([2, 4, 6])` still returns `4.0`.
- Existing tests pass.
- Changes are limited to `src/**` and `tests/**`.

## Validation command

```json
["python", "-m", "pytest"]
```

The repository intentionally starts with a failing edge case that is not covered by its visible
test. This lets the acceptance planner turn the known criterion into an external structured case,
while the implementation Agent never sees verifier-only test source.
