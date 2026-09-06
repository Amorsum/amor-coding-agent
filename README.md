# AMOR Coding Agent

AMOR（Agentic Maintainer for Objective Repair）是一个由客观验证驱动的本地 Coding Agent。当前版本支持固定 Benchmark 演示，以及对本地 Python Git 仓库运行自然语言修复任务。

`v0.20.0` 增加受控的 Python 依赖准备阶段。用户批准后，AMOR 从 `pyproject.toml`、常见 requirements 文件和验证命令中识别包，通过只接收包名的临时 Docker 容器从 PyPI 下载二进制 wheel，并安装到本次任务的独立依赖目录。依赖准备结束后，Agent 与 Verifier 仍使用无网络容器；Provider Key、用户主目录、Docker socket 和目标源码均不会进入联网安装容器。

`v0.19.0` 增加本地仓库预检和受保护工作区快照：项目仍需至少有一次 Git Commit，但不再要求用户先提交或 stash 当前修改。页面会列出未提交文件并要求确认，AMOR 随后从当前文件内容创建只读 Git 基线，在独立 worktree 中规划、执行和验证，全程不改动原工作区。

## 当前可运行链路

```text
用户任务 → 独立只读验收规划 → 回答问题或人工修订 → 用户审批并冻结契约
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

真实仓库默认使用 Docker 沙箱。先启动 Docker Desktop，并显式准备固定基础镜像；AMOR 运行任务时不会自动联网拉取镜像：

```powershell
docker pull python:3.12-slim
```

## 本地 Web 工作台

首次使用先构建静态前端：

```powershell
cd web
npm ci
npm run build
cd ..
```

API Key 有两种配置方式。推荐启动后在“真实任务”页面粘贴 Key：它只会发送到回环地址并驻留当前 AMOR 服务进程内存，页面刷新后仍可使用，关闭服务后自动失效，也不会写入任务记录或浏览器存储。也可以在启动终端预先设置环境变量：

```powershell
$env:OPENAI_API_KEY = "your-api-key"
# 或：$env:DEEPSEEK_API_KEY = "your-api-key"
```

随后用一个命令同时启动本地任务 API、Artifact API 和工作台：

```powershell
.venv\Scripts\amor web --artifacts artifacts
```

浏览器访问 `http://127.0.0.1:8765/`。交互服务只允许监听 `127.0.0.1`、`localhost` 或 `::1`，不能通过参数改成公网地址。

“真实任务”页签提供：

- 输入本地 Git 仓库绝对路径、任务、已知验收条件和允许修改范围
- 创建任务前检查 Git 仓库、HEAD、语言和未提交文件；干净仓库可直接继续
- 对已确认的未提交文件创建受保护快照，后续内容或 HEAD 漂移会拒绝审批、执行与交付
- 在页面内配置或清除仅当前服务会话有效的 Provider Key；页面只显示来源状态，不回传 Key
- 通过启动前自检查看模型凭据、仓库、任务、模型 ID、发送确认和 Docker 的具体阻塞原因
- 使用独立只读模型会话生成验收契约
- 逐项审阅结构化用例、验证命令、证据文件和契约哈希
- 在同一任务中回答 `NEEDS_INPUT` 问题，并让独立规划器基于上一版契约局部修订
- 直接编辑验收文本、允许路径和验证命令；结构化外部用例保持只读
- 查看契约修订来源、说明、时间和哈希；任何修改都会使旧审批失效
- 人工批准后启动执行 Agent
- 在 Docker 分阶段网络沙箱和宿主机兼容模式之间显式选择；页面会展示 Docker 引擎与镜像就绪状态
- 可批准 AMOR 自动识别并准备 Python 依赖；联网仅限 PyPI 二进制 wheel 下载，Agent 和 Verifier 始终无网络
- Docker 模式限制为 1 CPU、512 MB 内存、128 个进程、64 MB 临时盘和 256 MB 工作区增长，并支持超时/取消强制终止
- 通过 SSE 实时展示状态变化、模型轮次、工具结果和 Verifier 事件
- 协作式取消：队列任务立即取消；运行任务在当前模型请求或验证子进程的安全边界停止
- 展示最终状态、Token、验证历史和 Git Diff
- 对 Git Diff 生成 SHA-256 指纹，并完整包含受范围约束的新文件
- 将已验收补丁应用到新的本地分支，在交付 worktree 中重新验收并可选 commit
- 交付前检查仓库基准、工作区、契约哈希和补丁哈希；任一漂移都会拒绝操作
- 对已提交且再次验收通过的交付结果，通过独立 CLI 审批创建 GitHub Draft PR
- 刷新页面后从 `artifacts/jobs/` 恢复任务记录；服务重启时未完成任务会明确标记为中断

“实验分析”页签继续提供：

- 上下文策略与规划策略实验列表
- 成功率、Token、工具调用和上下文指标对比
- 每个任务的状态、轮次、工具调用与耗时
- Verifier 检查、结构化计划、状态轨迹和 Git Diff
- Fake Provider 的显式证据边界提示
- 对选中实验生成聚合数据公开快照，并在本机打开最终静态页面
- 每个快照使用内容派生 ID，源实验变化时不会静默覆盖旧版本

网页任务仍遵守 CLI 的全部边界：目标仓库必须至少存在一个 Commit；干净工作区直接使用 `HEAD`，已确认的未提交内容使用 `refs/amor/snapshots/` 下的受保护基线。Agent 修改和补丁交付分别发生在隔离 worktree 中，验证命令必须预先批准。Docker 模式只把目标项目命令放入容器；仓库分析、文件工具、Git 工作区管理和模型调用仍由本地 AMOR 服务控制。只有用户再次确认后才会创建新的本地分支并可选提交；原仓库当前分支、文件和 index 不会被切换或修改，系统也不会自动推送。基于未提交快照的交付包含用户原有修改，必须人工审阅，不能直接使用自动 Draft PR 发布。当前工作台仍只允许本机访问。

前端开发模式下，在另一个终端进入 `web/` 运行 `npm run dev`；开发服务器会把 `/api` 转发到本机 `8765` 端口。

## 导出公开实验快照

网页中的“生成公开快照”会列出脱敏范围并要求再次确认。也可以通过 CLI 导出；参数使用 Artifact API 生成的 16 位实验 ID，不接受文件路径：

```powershell
.venv\Scripts\amor export-showcase `
  --experiment <experiment-artifact-id> `
  --title "AMOR 规划策略实验" `
  --confirm-public
```

产物位于 `artifacts/showcases/<showcase-id>/`：

- `index.html`：无外部脚本、字体、图片或网络请求的静态展示页
- `showcase.json`：同一份脱敏指标与有限任务状态，便于后续部署或复核
- `manifest.json`：来源实验 ID、生成时间以及两个公开文件的 SHA-256

公开页面同时包含固定的完整项目入口、当前版本和运行边界说明。这些字段参与快照内容哈希，不能在不改变快照 ID 的情况下被替换；链接只指向项目公开仓库，不指向本机工作台或任何任务 API。

本地工作台通过 `/showcases/<showcase-id>/` 预览。此功能不会开放任务 API；公开部署只能使用下一节生成的独立静态目录，不能把本地 AMOR 服务整体暴露到公网。

## 暂存与部署公开页面

先把已经验证的快照暂存到专用目录。命令会再次要求公开确认，并拒绝目录中的 `.env`、源代码或其他未知文件：

```powershell
.venv\Scripts\amor stage-showcase `
  --showcase <showcase-id> `
  --output out `
  --confirm-public
```

仓库根目录的 `.openai/hosting.json` 只将 `out/` 声明为静态发布内容。当前公开地址计划绑定为 `https://amor.amorsum.top`；更新线上报告时，需要重新导出、暂存并发布一个新版本，旧内容不会在没有确认的情况下自动变化。

## 发布已验收交付到 GitHub Draft PR

只有选择“生成本地 Commit”并且落地后二次验收通过的交付结果才能发布。使用 Fine-grained PAT 时，目标仓库需要 `Contents: write` 和 `Pull requests: write`；Token 只放在当前终端，不要写入命令参数或项目文件：

```powershell
$env:GH_TOKEN = "your-fine-grained-token"

.venv\Scripts\amor publish-pr `
  --delivery "artifacts\jobs\<job-id>\deliveries\attempt-0001\delivery-report.json" `
  --remote origin `
  --base main `
  --title "fix: apply verified AMOR patch" `
  --proxy "http://127.0.0.1:7890" `
  --confirm-publish
```

`--proxy` 可省略；它只接受不带账号密码的 HTTP(S) 代理 URL。发布固定创建 Draft PR，不会自动请求评审、合并或删除分支。系统只把检查名称与哈希证据写入 PR 描述，不上传测试输出、任务指令、代码片段或本地路径。每次结果独立保存在交付目录的 `github-publications/<publication-id>.json`；若分支推送成功但 PR 创建失败，报告会保留这一事实，方便人工恢复。

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

CLI 流程仍要求目标仓库已经提交且工作区干净，并从当前 `HEAD` 创建隔离 worktree。需要保留未提交修改时，请使用 v0.19 本地 Web 工作台的“检查仓库”和受保护快照流程。

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
  --sandbox docker `
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
  --sandbox docker `
  --confirm-send-code
```

改用 DeepSeek 时，把环境变量换成 `DEEPSEEK_API_KEY`，并在同一命令中增加 `--provider deepseek-responses --model deepseek-v4-pro`。

注意：

- `--validation-json` 必须是参数数组；命令不会通过 shell 执行，模型也不能改变它。
- 可以重复提供 `--validation-json`、`--accept` 和 `--allow`。
- `--confirm-send-code` 表示你确认相关代码片段和测试输出会发送给配置的模型服务。
- OpenAI 可通过 `--base-url` 或 `OPENAI_BASE_URL` 覆盖地址；DeepSeek 对应 `--base-url` 或 `DEEPSEEK_BASE_URL`。
- `--sandbox docker` 是真实仓库的默认值；Docker 引擎未运行或镜像未提前准备时会失败关闭，不会自动回退或拉取镜像。
- `--install-dependencies` 会先从项目声明和验证命令识别 Python 包，在不挂载源码的临时容器中从固定 PyPI 索引下载二进制 wheel。没有该显式参数时，CLI 不会联网安装依赖。
- Docker 的 Agent 和验证阶段始终使用 `--network none`、只读容器根文件系统、能力移除和资源限额；只有隔离 worktree 可写。需要兼容尚未容器化的工具链时可显式使用 `--sandbox host`，但它不提供容器级隔离。
- 可用 `--sandbox-cpus`、`--sandbox-memory-mb`、`--sandbox-pids`、`--sandbox-tmpfs-mb` 和 `--sandbox-workspace-growth-mb` 调整资源边界。
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

Web 任务还会写入：

- `artifacts/jobs/<job-id>/job.json`：不含凭据的任务状态、审批信息和实时事件快照
- `artifacts/plans/<plan-id>/`：验收契约、中文报告和规划轨迹
- `artifacts/runs/<run-id>/`：执行报告、验证契约、轨迹和隔离 worktree
- `artifacts/jobs/<job-id>/deliveries/`：交付报告、二次验收现场和独立交付 worktree

## 安全边界

首个迭代已经实施以下约束：

- Agent 工具只能访问隔离工作区。
- `.git`、`.env*` 等敏感路径不可读取或修改。
- 补丁只能修改任务声明的路径。
- 验证命令使用参数数组执行且必须与白名单完全匹配，不通过 shell。
- Benchmark 隐藏测试位于目标工作区之外，由独立 Verifier 执行；真实项目只运行用户批准的验证命令。
- 公开快照使用字段白名单重新构造，不复制原始报告；输出 CSP 禁止脚本、表单和外部资源，并用清单哈希检测改写。
- 公开展示页没有脚本和表单，只允许访客阅读脱敏证据或导航到固定的 GitHub 项目地址；本机工作台不会被代理到公网。
- 公网暂存只接受 `index.html`、`showcase.json` 和 `manifest.json`，并在复制后再次校验哈希；任何额外文件都会关闭发布流程。
- GitHub 发布只允许二次验收通过的交付 commit，使用“预期远端分支不存在”的 lease 推送，禁止覆盖已有远端分支；Token 只进入子进程环境和 HTTPS 请求头。

真实任务默认在每任务 Docker 容器中执行目标项目命令。依赖准备需要用户单独确认，仅向联网容器传递经过校验的包需求字符串，不挂载目标源码；依赖写入本次运行产物目录并以只读方式挂载到后续容器。Agent 与 Verifier 容器禁网，所有容器均不挂载 API Key、用户主目录或 Docker socket。文件检索与补丁仍由宿主 AMOR 进程在隔离 worktree 内完成，并受路径策略约束。宿主机兼容模式只适合受信任仓库。即使使用容器，当前本地路径选择、Provider 凭据和服务访问模型也不满足多租户公网要求。

## 项目结构

```text
src/amor/               核心实现
src/amor/execution/     宿主机与 Docker 命令执行边界
src/amor/showcase.py    静态脱敏快照生成与完整性清单
src/amor/github.py      GitHub 分支推送与 Draft PR 证据边界
src/amor/web/           本地任务 API、Artifact API 与静态工作台托管
benchmarks/fixtures/    示例目标仓库模板
benchmarks/tasks/       Agent 可见任务规格
benchmarks/hidden_tests Verifier 专用隐藏测试
tests/                  单元、集成和端到端测试
docs/                   架构决策
web/                    Vite + React 可观测工作台
out/                    经确认并验证的公网静态页面
.openai/hosting.json    公网托管的静态目录边界
```

模型 Provider 不记录 API Key。轨迹只保存响应 ID、工具名称、使用量、工具结果和简短输出摘要，不保存私有推理过程。第五迭代的 Provider 会话设计见 [ADR 0005](./docs/adr/0005-provider-session-and-cost-accounting.md)，第六迭代的 Benchmark 设计见 [ADR 0006](./docs/adr/0006-benchmark-credibility.md)，第七迭代的只读 Web 边界见 [ADR 0007](./docs/adr/0007-read-only-web-workbench.md)，第八迭代的验证闭环见 [ADR 0008](./docs/adr/0008-verification-driven-repair.md)，第九迭代的独立验收规划设计见 [ADR 0009](./docs/adr/0009-independent-acceptance-planning.md)，第十迭代的本地交互式任务边界见 [ADR 0010](./docs/adr/0010-local-interactive-workbench.md)，第十一迭代的契约修订设计见 [ADR 0011](./docs/adr/0011-contract-revision-loop.md)，第十二迭代的补丁交付边界见 [ADR 0012](./docs/adr/0012-verified-patch-delivery.md)，第十三迭代的容器命令沙箱见 [ADR 0013](./docs/adr/0013-per-task-container-sandbox.md)，第十四迭代的公开快照边界见 [ADR 0014](./docs/adr/0014-static-redacted-showcase.md)，第十五迭代的静态公网发布边界见 [ADR 0015](./docs/adr/0015-static-public-deployment.md)，第十六迭代的 GitHub Draft PR 边界见 [ADR 0016](./docs/adr/0016-verified-github-draft-pr.md)，第十七迭代的只读项目展示入口见 [ADR 0017](./docs/adr/0017-static-project-showcase-boundary.md)，第十八迭代的进程内凭据与本地就绪检查见 [ADR 0018](./docs/adr/0018-local-session-credentials.md)，第十九迭代的受保护工作区快照见 [ADR 0019](./docs/adr/0019-protected-working-tree-snapshots.md)，第二十迭代的受控依赖准备见 [ADR 0020](./docs/adr/0020-controlled-dependency-bootstrap.md)。

完整产品规划见 [AMOR-Coding-Agent项目实现方案.md](./AMOR-Coding-Agent项目实现方案.md)。
