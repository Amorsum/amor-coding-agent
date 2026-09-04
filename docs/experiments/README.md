# AMOR 实验运行协议

## 离线管道验证

```powershell
.venv\Scripts\amor benchmark --provider fake --repeat 3
.venv\Scripts\amor experiment --dimension context --provider fake --repeat 3
.venv\Scripts\amor experiment --dimension planning --provider fake --repeat 3
```

Fake Provider 是确定性的，只用于证明任务、工具、Verifier、指标和报告管道可重复，不代表模型能力。

## 真实模型实验

1. 固定 Git commit、模型 ID、任务集、Prompt 版本、上下文预算、Token 上限和价格快照。
2. 先对一个任务运行一次低预算冒烟测试。
3. 冒烟通过后，每个实验变体至少重复三次。
4. 保留 `config.json`、`comparison.json`、`report.md`、失败列表和任务轨迹。
5. 只有 `dataset_fingerprint` 完全一致的运行可以直接比较。

真实实验示例：

```powershell
$env:DEEPSEEK_API_KEY = "your-api-key"

.venv\Scripts\amor experiment `
  --dimension planning `
  --provider deepseek-responses `
  --model deepseek-v4-pro `
  --repeat 3 `
  --max-tokens 20000 `
  --max-output-tokens 2000 `
  --confirm-send-code
```

API Key 只能放在本机环境变量中。价格参数应使用实验当天的官方价格快照并显式记录币种。
