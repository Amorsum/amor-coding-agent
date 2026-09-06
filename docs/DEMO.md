# AMOR interview demo

This walkthrough is designed for a 60-second screen recording or a short live interview demo.
It uses a deterministic, versioned fixture but creates a fresh Git repository for every run.

## Prepare the repository

From the AMOR repository root:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\create-demo-repository.ps1
.venv\Scripts\python -m pytest artifacts\demo-calculator\tests
```

The visible test passes. The known empty-list acceptance case still fails, which is intentional.

## Run it in the workbench

```powershell
.venv\Scripts\amor web --artifacts artifacts
```

Open `http://127.0.0.1:8765/`, select **真实任务**, and enter:

- Repository: the absolute path printed by `create-demo-repository.ps1`
- Task: `修复 average 在空列表输入时抛出异常的问题，同时保持现有行为不变`
- Known acceptance: `average([]) 返回 0.0；现有测试继续通过`
- Allowed paths: `src/**`, `tests/**`

Then configure a provider key in the session-only settings, inspect the repository, generate and
approve the acceptance contract, approve dependency preparation, and run with the Docker sandbox.

## 60-second narration

1. **0–10 s — boundary:** show that the source repository already has a commit and remains untouched.
2. **10–25 s — contract:** show the read-only planner converting the requirement into a frozen,
   hash-bound acceptance contract.
3. **25–40 s — sandbox:** approve PyPI dependency bootstrap, then point out that Agent and Verifier
   run offline in a separate worktree.
4. **40–52 s — evidence:** show the final pytest result, external acceptance result, bounded diff,
   patch fingerprint, and trace.
5. **52–60 s — delivery:** create a new local delivery branch only after re-verification; explain
   that AMOR never changes the user's current checkout or pushes automatically.

## Expected result

The smallest valid patch adds an empty-input guard returning `0.0`. AMOR should finish as
`SUCCEEDED`, with all visible and structured external checks passing and no files outside the
approved paths changed. Model output is nondeterministic, so the exact patch text and token usage
may vary; the repository, policy, and acceptance result are reproducible.
