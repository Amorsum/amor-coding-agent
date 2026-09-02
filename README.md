# AMOR Coding Agent

AMOR（Agentic Maintainer for Objective Repair）是一个由客观验证驱动的本地 Coding Agent。当前版本支持固定 Benchmark 演示，以及对干净的本地 Git 仓库运行自然语言修复任务。

## 当前可运行链路

```text
固定任务 → 创建隔离 Git worktree → 搜索/局部读取 → 应用补丁
        → 运行可见测试 → 独立 Verifier → diff、轨迹与报告
```

脚本化 Agent 用于稳定验证基础设施，不依赖真实 LLM。第二个任务会先应用一个不完整补丁，在测试失败后诊断并再次修复。模型 Agent 使用 Responses API 函数调用，但复用完全相同的工具策略和 Verifier。

## 本地运行

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m pytest
.venv\Scripts\amor demo
```

## 对本地仓库运行模型 Agent

目标仓库必须已经提交且工作区干净。AMOR 从当前 `HEAD` 创建隔离 worktree，不直接修改原仓库。

先进行只读分析：

```powershell
.venv\Scripts\amor profile D:\path\to\target-repository
```

设置 API Key，然后明确提供可修改范围和允许执行的验证命令：

```powershell
$env:OPENAI_API_KEY = "your-api-key"

.venv\Scripts\amor run D:\path\to\target-repository `
  --task "修复空列表输入导致的异常，并保持现有行为不变" `
  --accept "空列表不再抛出异常" `
  --accept "现有测试通过" `
  --allow "src/**" `
  --allow "tests/**" `
  --validation-json '["python","-m","pytest"]' `
  --model "your-responses-api-model-id" `
  --confirm-send-code
```

注意：

- `--validation-json` 必须是参数数组；命令不会通过 shell 执行，模型也不能改变它。
- 可以重复提供 `--validation-json`、`--accept` 和 `--allow`。
- `--confirm-send-code` 表示你确认相关代码片段和测试输出会发送给配置的模型服务。
- 可通过 `--base-url` 或 `OPENAI_BASE_URL` 使用兼容 Responses API 的服务。
- 当前仍使用本机子进程执行测试，不要对恶意或来源不明的仓库运行。
- 验证成功后，补丁仍只保存在产物目录的隔离 `workspace/` 中，不会自动提交或应用回原仓库。

运行产物写入 `artifacts/runs/<run-id>/`，每个任务包含：

- `trace.jsonl`：状态变化、工具调用和验证事件
- `final-report.json`：最终状态、验证结果、diff 和运行元数据
- `workspace/`：隔离后的目标仓库

## 安全边界

首个迭代已经实施以下约束：

- Agent 工具只能访问隔离工作区。
- `.git`、`.env*` 等敏感路径不可读取或修改。
- 补丁只能修改任务声明的路径。
- 验证命令使用参数数组执行且必须与白名单完全匹配，不通过 shell。
- 隐藏测试位于目标工作区之外，由独立 Verifier 执行。

当前隔离仍以本机子进程和 Git worktree 为基础，不等同于容器安全沙盒；不应对不受信任的第三方仓库开放。

## 项目结构

```text
src/amor/               核心实现
benchmarks/fixtures/    示例目标仓库模板
benchmarks/tasks/       Agent 可见任务规格
benchmarks/hidden_tests Verifier 专用隐藏测试
tests/                  单元、集成和端到端测试
docs/                   架构决策
```

模型 Provider 不记录 API Key。轨迹只保存响应 ID、工具名称、使用量、工具结果和简短输出摘要，不保存私有推理过程。

完整产品规划见 [AMOR-Coding-Agent项目实现方案.md](./AMOR-Coding-Agent项目实现方案.md)。
