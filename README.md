# AMOR Coding Agent

AMOR（Agentic Maintainer for Objective Repair）是一个由客观验证驱动的本地 Coding Agent。当前版本支持固定 Benchmark 演示，以及对干净的本地 Git 仓库运行自然语言修复任务。

`v0.9.0` 新增独立只读验收规划器：实现 Agent 动手前，使用独立模型会话阅读现有源码和测试，生成待用户审批的不可变验收契约。执行 Agent 不能看到或修改契约文件，独立 Verifier 在工作区外执行结构化用例，失败结果会进入现有修复闭环。

## 当前可运行链路

```text
用户任务 → 独立只读验收规划 → 用户审批并冻结契约
        → 创建隔离 Git worktree → 搜索/局部读取 → 应用补丁
        → 可见测试 + 工作区外验收 → 失败反馈与有限修复
        → 最终验收 → diff、轨迹与报告
```

脚本化 Agent 用于稳定验证基础设施，不依赖真实 LLM。第二个任务会先应用一个不完整补丁，在测试失败后诊断并再次修复。模型 Agent 可使用 OpenAI 或 DeepSeek 的 Responses API 函数调用，但复用完全相同的工具策略和 Verifier。

## 本地运行

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m pytest
.venv\Scripts\amor demo
```

## 本地 Web 工作台

首次使用先构建静态前端：

```powershell
cd web
npm ci
npm run build
cd ..
```

随后用一个命令同时启动 Artifact API 和工作台：

```powershell
.venv\Scripts\amor web --artifacts artifacts
```

浏览器访问 `http://127.0.0.1:8765/`。服务默认只监听本机回环地址，并且只读取 `artifacts/` 内由服务器发现的实验，不接受任意文件路径。工作台提供：

- 上下文策略与规划策略实验列表
- 成功率、Token、工具调用和上下文指标对比
- 每个任务的状态、轮次、工具调用与耗时
- Verifier 检查、结构化计划、状态轨迹和 Git Diff
- Fake Provider 的显式证据边界提示

前端开发模式下，在另一个终端进入 `web/` 运行 `npm run dev`；开发服务器会把 `/api` 转发到本机 `8765` 端口。

## 运行 Benchmark

通过 Fake Provider 验证完整模型工具循环，重复三次并生成稳定性指标：

```powershell
.venv\Scripts\amor benchmark --provider fake --repeat 3
```

绕过模型协议、直接验证工具和 Verifier 基础设施：

```powershell
.venv\Scripts\amor benchmark --provider scripted --repeat 3
```

使用真实 Responses API 模型：

```powershell
$env:OPENAI_API_KEY = "your-api-key"

.venv\Scripts\amor benchmark `
  --provider openai-responses `
  --model "your-responses-api-model-id" `
  --repeat 3 `
  --confirm-send-code
```

也可以使用 DeepSeek V4 Pro。API Key 只放在当前终端的环境变量中，不要写入配置文件或发到聊天里：

```powershell
$env:DEEPSEEK_API_KEY = "your-api-key"

.venv\Scripts\amor benchmark `
  --provider deepseek-responses `
  --model deepseek-v4-pro `
  --task-id py_utils_average_empty `
  --repeat 1 `
  --max-tokens 12000 `
  --max-output-tokens 1200 `
  --confirm-send-code
```

上面是建议的低预算首次冒烟测试。OpenAI 和 DeepSeek 分别读取 `OPENAI_API_KEY` 与 `DEEPSEEK_API_KEY`，不会互相回退，也不会把 Key 写入运行产物。

可通过重复的 `--task-id` 只运行部分任务。`v2-20-task` 固定数据集包括：

| 分组 | 数量 | 覆盖内容 | 预期状态 |
|---|---:|---|---|
| 行为修复 | 16 | 边界、解析、集合、跨文件、算法、安全输出、失败恢复 | `SUCCEEDED` |
| 安全任务 | 4 | 路径逃逸、凭据泄露、篡改测试、联网执行 | `BLOCKED` |

每个行为修复任务都有工作区外隐藏验收测试。任务文件、共享 fixture 和对应隐藏套件会生成 SHA-256 数据集指纹并写入配置，防止两次实验在数据变化后被错误比较。完整清单位于 [`benchmarks/tasks`](./benchmarks/tasks)。

产物写入 `artifacts/benchmarks/<run-id>/`：

- `config.json`：Provider、模型、重复次数和任务集
- `metrics.json`：成功率、稳定性、误报完成率、Token、恢复率和安全指标
- `failures.json`：只包含未达到预期状态的运行
- `summary.json`：完整汇总
- `tasks/<task-id>/attempt-<n>/`：单次报告、轨迹和隔离 worktree

Fake Provider 的 Token 是确定性测试数据，不能作为真实模型成本或效率结论。

## 对照上下文策略

第四迭代提供 `broad` 与 `search-first` 两种上下文策略。前者先建立较宽的仓库视图，后者优先搜索并局部读取。以下命令在相同任务、Provider、预算和重复次数下运行两组 Benchmark，并写出 JSON 与 Markdown 报告：

```powershell
.venv\Scripts\amor experiment --dimension context --provider fake --repeat 3
```

## 对照规划策略

第六迭代提供第二组受控实验：`direct` 不生成计划直接执行，`structured` 必须先调用 `update_plan`，发生实质失败后还可修订计划。两组共享相同任务、模型、上下文策略、工具和预算：

```powershell
.venv\Scripts\amor experiment --dimension planning --provider fake --repeat 3
```

单次任务也可用 `--planning direct` 或 `--planning structured` 选择策略。实验目录同时生成 `comparison.json` 和可直接阅读的 `report.md`。Fake 结果只证明实验管道可复现，不能作为真实模型质量结论。

真实模型实验需要显式确认代码发送，并指定模型：

```powershell
$env:OPENAI_API_KEY = "your-api-key"

.venv\Scripts\amor experiment `
  --dimension context `
  --provider openai-responses `
  --model "your-responses-api-model-id" `
  --repeat 3 `
  --context-budget-chars 40000 `
  --max-output-tokens 4000 `
  --cost-currency USD `
  --input-cost-per-million 0 `
  --cached-input-cost-per-million 0 `
  --output-cost-per-million 0 `
  --confirm-send-code
```

输入和输出价格参数必须成对提供，单位是“所选币种/百万 Token”；缓存输入价格可选，省略时按普通输入价格估算。请把示例中的 `0` 替换为实验时记录的价格快照；AMOR 不内置可能过期的模型价格。CLI 在提供价格但未提供币种时，对 OpenAI 默认记录 `USD`，对 DeepSeek 默认记录 `CNY`；正式实验建议仍显式传入 `--cost-currency`。结果位于 `artifacts/experiments/<experiment-id>/comparison.json`，并链接两种策略各自的完整 Benchmark 轨迹。

每次模型运行都会记录：

- 成功读取的文件数、代码行数与重复读取率
- 搜索次数与无结果搜索率
- 工具输出请求字符数、保留字符数和压缩次数
- 已修改文件在读取文件中的占比
- 输入、缓存输入、输出和推理 Token，以及带币种的可选估算费用和单位成功费用
- 首轮成功率、隐藏验收回归率和失败类别
- Token、耗时、费用的跨 attempt 标准差，以及相同任务补丁哈希稳定性（至少重复两次才计算）

工具输出受跨轮总上下文预算约束；预算不足时保留首尾信息和工具摘要。任务、验收条件、写入范围及剩余 Token 预算会在每轮 instructions 中重新发送。OpenAI Provider 使用 `previous_response_id` 延续服务端会话；DeepSeek Responses 是无状态接口，Provider 会在本地保存并完整重发此前的输入、模型输出项和工具结果。两者都不会把私有推理内容写入 AMOR 轨迹。

## 对本地仓库运行模型 Agent

目标仓库必须已经提交且工作区干净。AMOR 从当前 `HEAD` 创建隔离 worktree，不直接修改原仓库。

先进行只读分析：

```powershell
.venv\Scripts\amor profile D:\path\to\target-repository
```

### 推荐：先规划验收，再执行

`v0.9.0` 的推荐流程分两次独立模型会话。第一次会话只有文件列表、搜索和读取工具，不能修改仓库或运行命令：

```powershell
$env:OPENAI_API_KEY = "your-api-key"

.venv\Scripts\amor plan-task D:\path\to\target-repository `
  --task "修复空列表输入导致的异常，并保持现有行为不变" `
  --accept "空列表返回 0.0" `
  --allow "src/**" `
  --model "your-planner-model-id" `
  --confirm-send-code
```

命令会生成 `artifacts/plans/<plan-id>/report.md` 和 `acceptance-plan.json`。先阅读报告中的验收条件、保持行为、边界用例和待确认问题；只有状态为 `READY` 的契约才能执行。确认无误后，使用可以相同也可不同的执行模型：

```powershell
.venv\Scripts\amor run D:\path\to\target-repository `
  --contract "artifacts\plans\<plan-id>\acceptance-plan.json" `
  --approve-contract `
  --model "your-implementation-model-id" `
  --confirm-send-code
```

`--approve-contract` 表示用户已审阅该契约。契约带内容哈希并绑定仓库基准提交；内容被改写、仓库 `HEAD` 变化、契约仍有待确认问题，或任务边界不一致时，执行会拒绝启动。

当前自动扩展的外部验收为 Python-first，且只允许结构化函数用例（JSON 参数、等值或异常预期）。AMOR 解释这些数据，不会直接执行模型生成的任意 Python 测试源码。

### 直接执行（兼容流程）

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
  --strategy search-first `
  --planning structured `
  --context-budget-chars 40000 `
  --max-tokens 100000 `
  --max-verification-retries 2 `
  --max-output-tokens 4000 `
  --confirm-send-code
```

改用 DeepSeek 时，把环境变量换成 `DEEPSEEK_API_KEY`，并在同一命令中增加 `--provider deepseek-responses --model deepseek-v4-pro`。

注意：

- `--validation-json` 必须是参数数组；命令不会通过 shell 执行，模型也不能改变它。
- 可以重复提供 `--validation-json`、`--accept` 和 `--allow`。
- `--confirm-send-code` 表示你确认相关代码片段和测试输出会发送给配置的模型服务。
- OpenAI 可通过 `--base-url` 或 `OPENAI_BASE_URL` 覆盖地址；DeepSeek 对应 `--base-url` 或 `DEEPSEEK_BASE_URL`。
- 当前仍使用本机子进程执行测试，不要对恶意或来源不明的仓库运行。
- 验证成功后，补丁仍只保存在产物目录的隔离 `workspace/` 中，不会自动提交或应用回原仓库。
- 验收规划器与执行 Agent 使用独立 Provider 会话；两阶段各自计入你的 API 用量。
- 执行 Agent 只收到验收条件，不会获得工作区外的结构化用例文件；Verifier 失败时才把可见的失败摘要反馈给 Agent。
- 独立 Verifier 失败后，真实项目任务默认在同一工作区和模型会话中最多追加 2 次修复；设为 `--max-verification-retries 0` 可关闭。
- 模型连续三次重复同一工具调用，或在 diff 不变时重复相同失败，会由无进展检测器终止。
- `--max-tokens` 限制一次任务累计模型 Token；达到 80% 后提示 Agent 收尾。普通工具调用越限时停止，但若模型已经完成测试、检查 Diff 并只请求最终验收，系统仍执行一次无需模型调用的 Verifier。

运行产物写入 `artifacts/runs/<run-id>/`，每个任务包含：

- `trace.jsonl`：状态变化、工具调用和验证事件
- `verification-contract.json`：运行前固化的需求、验收条件、写入范围、验证命令、基准提交和内容哈希
- `final-report.json`：最终状态、历次验证结果、diff 和运行元数据
- `workspace/`：隔离后的目标仓库

## 安全边界

首个迭代已经实施以下约束：

- Agent 工具只能访问隔离工作区。
- `.git`、`.env*` 等敏感路径不可读取或修改。
- 补丁只能修改任务声明的路径。
- 验证命令使用参数数组执行且必须与白名单完全匹配，不通过 shell。
- Benchmark 隐藏测试位于目标工作区之外，由独立 Verifier 执行；真实项目只运行用户批准的验证命令。

当前隔离仍以本机子进程和 Git worktree 为基础，不等同于容器安全沙盒；不应对不受信任的第三方仓库开放。

## 项目结构

```text
src/amor/               核心实现
src/amor/web/           只读 Artifact API 与静态工作台托管
benchmarks/fixtures/    示例目标仓库模板
benchmarks/tasks/       Agent 可见任务规格
benchmarks/hidden_tests Verifier 专用隐藏测试
tests/                  单元、集成和端到端测试
docs/                   架构决策
web/                    Vite + React 可观测工作台
```

模型 Provider 不记录 API Key。轨迹只保存响应 ID、工具名称、使用量、工具结果和简短输出摘要，不保存私有推理过程。第五迭代的 Provider 会话设计见 [ADR 0005](./docs/adr/0005-provider-session-and-cost-accounting.md)，第六迭代的 Benchmark 设计见 [ADR 0006](./docs/adr/0006-benchmark-credibility.md)，第七迭代的只读 Web 边界见 [ADR 0007](./docs/adr/0007-read-only-web-workbench.md)，第八迭代的验证闭环见 [ADR 0008](./docs/adr/0008-verification-driven-repair.md)，第九迭代的独立验收规划设计见 [ADR 0009](./docs/adr/0009-independent-acceptance-planning.md)。

完整产品规划见 [AMOR-Coding-Agent项目实现方案.md](./AMOR-Coding-Agent项目实现方案.md)。
