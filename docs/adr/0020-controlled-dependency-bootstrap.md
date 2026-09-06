# ADR 0020：受控依赖准备与分阶段网络

## 状态

已采纳，适用于 `v0.20.0`。

## 背景

v0.19 的真实任务命令始终在 `--network none` 的基础镜像中运行。该边界可以阻止任务代码访问网络，但干净镜像通常不包含 `pytest` 等验证工具，导致代码修复完成后因环境缺失而被错误归类为 Agent 阻断。普通用户也不应提前判断需要在宿主机安装哪些依赖。

## 决策

- Docker 模式可由用户显式批准一次自动 Python 依赖准备。
- AMOR 只读取 `pyproject.toml`、`requirements.txt`、`requirements-dev.txt`、`requirements-test.txt` 和已批准验证命令。
- 拒绝 URL、路径、递归 requirements、可编辑安装和命令行选项，只接受包索引需求字符串。
- 下载固定使用 `https://pypi.org/simple`，并要求二进制 wheel，避免执行源码构建脚本。
- 联网安装容器不挂载目标源码、Provider Key、用户主目录或 Docker socket。
- 依赖安装到本次运行产物的独立目录；Agent 与 Verifier 只读挂载该目录。
- Agent、可见测试、结构化验收和最终 Verifier 继续使用 `--network none`。
- 依赖准备受独立超时和存储增长限制约束；失败记录为 `ENVIRONMENT_BLOCKED`，不再显示为安全阻断或代码测试失败。
- Docker 基础镜像仍需由用户或管理员预先准备，本流程不会自动拉取镜像。

## 后果

常见 Python 项目可以在不污染宿主机的情况下自动获得 pytest 和已声明依赖。分阶段网络缩小了联网窗口，但 PyPI 和下载链仍属于外部供应链；后续版本可增加锁文件哈希校验、组织镜像源、跨任务只读缓存和更严格的出口代理。
