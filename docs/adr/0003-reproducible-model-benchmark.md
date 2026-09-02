# ADR 0003：固定任务上的可重复模型 Benchmark

## 状态

已接受。

## 决策

第三迭代新增统一 `amor benchmark` 入口，支持三种 Provider：

- `scripted`：不经过模型协议，用于隔离验证工作区、工具和 Verifier。
- `fake`：经过完整函数调用循环，使用确定性响应验证编排和指标。
- `openai-responses`：使用用户明确指定的 Responses API 模型。

Benchmark 任务从两个扩展到五个，包括边界条件、错误恢复、跨文件逻辑、类型配置和 Prompt Injection。成功任务由隐藏测试验收；安全任务必须在读取指定证据后以 `BLOCKED` 停止并保持空 diff。

每个任务可以重复运行，单次运行保存独立 worktree、轨迹和报告。汇总同时报告单次成功率、至少成功一次的任务比例和全部重复均成功的稳定任务比例。

## 无进展终止

模型循环不能只依赖最大轮数。系统在工具层之外记录调用与失败指纹：

- 连续三次完全相同的工具调用会终止任务。
- diff 不变时，连续出现相同工具失败会终止任务。
- 修改导致 diff 变化后，旧失败指纹失效，允许继续验证。

## 指标边界

Responses API 的 `input_tokens`、`output_tokens` 和 `total_tokens` 按运行累加。Fake Provider 也生成固定 Token 数据，但它仅用于测试指标管道，不能与真实模型成本比较。

当前没有模型价格配置，因此本阶段不计算费用。
