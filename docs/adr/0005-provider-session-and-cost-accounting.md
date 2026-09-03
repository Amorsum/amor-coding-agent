# ADR 0005：Provider 独立会话与币种明确的成本统计

## 状态

已采纳。

## 背景

第五迭代需要在不改变工具、安全策略和独立 Verifier 的前提下接入第二个真实模型 Provider。不同 Responses 实现的会话语义不能被“兼容 API”这个名称掩盖：OpenAI 可以用 `previous_response_id` 续接响应，而 DeepSeek Responses 当前是无状态接口，不支持 `previous_response_id` 或 `conversation`。

Token 价格还可能采用不同币种，并区分普通输入、缓存输入和输出。把所有费用字段固定命名为美元会让跨 Provider 对照产生误导。

## 决策

- `openai-responses` 保持服务端会话续接，每轮仍重发稳定 instructions。
- `deepseek-responses` 在单个 Provider 实例中维护本地历史。每轮请求包含最初用户输入、此前每个模型 `output` 项，以及对应的 `function_call_output`。
- 每个任务的每次 Benchmark attempt 都创建全新的 Provider 实例，禁止跨任务复用历史。
- 两个 Provider 使用独立的 `OPENAI_API_KEY` 和 `DEEPSEEK_API_KEY`，不回退到另一家的密钥，也不把密钥写入日志或产物。
- usage 统一提取输入、缓存输入、输出、推理和总 Token。推理 Token 作为输出 Token 的明细记录，不重复计费。
- 费用字段使用中性的 `estimated_cost`，并在配置与汇总中记录 `cost_currency`。价格由运行者按当时快照显式提供，不在代码中固化。
- 缓存输入价格可单独提供；未提供时使用普通输入价格，避免漏计费用。
- Benchmark 和实验支持覆盖单任务 `max_total_tokens`，便于在真实 Provider 冒烟测试时设置硬预算。

## 后果

- DeepSeek 请求会随轮数携带更多历史，这是无状态协议保证工具调用连续性的必要成本。
- Provider 工厂是会话隔离边界；复用同一个 DeepSeek Provider 启动第二个任务会被明确拒绝。
- 不同币种的实验结果不能直接横向比较，调用方必须先进行币种归一化。
- Fake Provider 仍只验证管道正确性；真实效果与成本结论需要用户在本地配置 Key 后运行固定任务获得。

## 参考

- [OpenAI latest model guide](https://developers.openai.com/api/docs/guides/latest-model)
- [DeepSeek Responses API guide](https://api-docs.deepseek.com/guides/responses_api/)
