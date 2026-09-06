# ADR 0016：已验收交付的 GitHub Draft PR 发布

## 状态

已接受，随 `v0.16.0` 实施。

## 背景

`v0.12.0` 可以把已验收补丁交付到新的本地分支并再次验证，但远端推送和 PR 仍依赖人工命令。直接自动推送会扩大 GitHub 凭据暴露、覆盖已有分支、发布错误 commit 和意外触发协作通知的风险。

## 决策

- 先提供独立 `publish-pr` CLI，不让本地网页在没有新增审批模型前直接执行 GitHub 写操作。
- 只接受状态为 `SUCCEEDED`、落地后二次 Verifier 通过、且已经创建本地 commit 的 `delivery-report.json`。
- 发布前重新检查交付 worktree 仍存在且干净、当前分支与 commit 未变化，并重新计算 baseline 到 commit 的二进制 Git Diff；SHA-256 必须与交付报告一致。
- 远端仅允许标准 `github.com` HTTPS 或 SSH 仓库地址；发布时统一使用无凭据 HTTPS URL。
- 分支推送使用“预期远端引用不存在”的 force-with-lease。已有同名远端分支时失败，不允许覆盖或追加提交。
- 用户必须提供 `--confirm-publish`。访问令牌只读取 `GH_TOKEN` 或 `GITHUB_TOKEN`，通过子进程环境中的临时 Git Header 和 GitHub API Header 使用，不进入命令行、远端 URL、Git 配置或 Artifact。
- PR 固定创建为 Draft，不自动请求 Reviewer、转为 Ready、合并或删除分支。PR 正文只包含交付 ID、commit、补丁哈希及检查名称，不包含任务指令、测试输出、文件路径或模型轨迹。
- 每次发布在 `github-publications/` 中生成独立证据，记录推送是否成功和 PR URL。若推送后 API 失败，明确保留远端分支已创建的事实，避免盲目重试或覆盖历史尝试。
- 可选 HTTP(S) 代理必须是不带账号密码、路径、查询或片段的 URL。

## 结果

AMOR 可以把“Agent 自认为完成”推进到“已独立复验、可在 GitHub 审阅的 Draft PR”，同时把远端写操作限制在单一、显式、可追踪的审批边界。当前版本不支持 GitHub Enterprise、不自动处理同名 PR，也尚未把该操作接入 Web 工作台。
