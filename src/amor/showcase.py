from __future__ import annotations

import hashlib
import html
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from amor import __version__


PUBLIC_REPOSITORY_URL = "https://github.com/Amorsum/amor-coding-agent"


class ShowcaseError(RuntimeError):
    pass


class ShowcaseManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = "v1"
    showcase_id: str = Field(pattern=r"^[0-9a-f]{16}$")
    title: str
    experiment_id: str
    source_artifact_id: str = Field(pattern=r"^[0-9a-f]{16}$")
    generated_at: datetime
    files: dict[str, str]


class ShowcaseExporter:
    """Create a static, redacted public view from one experiment."""

    def __init__(self, artifacts_root: Path) -> None:
        # Import lazily because ``amor.web`` exports the app factory, which in
        # turn exposes showcase routes. Keeping module import side effects out
        # of this core exporter avoids a package initialization cycle.
        from amor.web.artifacts import ArtifactStore

        self.artifacts_root = artifacts_root.resolve()
        self.output_root = self.artifacts_root / "showcases"
        self.store = ArtifactStore(self.artifacts_root)

    def export(
        self,
        experiment_id: str,
        *,
        title: str = "AMOR 策略实验",
        confirm_public: bool,
    ) -> ShowcaseManifest:
        if not confirm_public:
            raise ShowcaseError("public export requires explicit confirmation")
        cleaned_title = title.strip()
        if not cleaned_title or len(cleaned_title) > 120:
            raise ShowcaseError("showcase title must contain 1-120 characters")

        experiment = self.store.get_experiment(experiment_id)
        snapshot = _public_snapshot(experiment, cleaned_title)
        canonical = json.dumps(
            snapshot,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        showcase_id = hashlib.sha256(canonical).hexdigest()[:16]
        destination = self.output_root / showcase_id
        if destination.is_dir():
            return self.get(showcase_id)

        generated_at = datetime.now(timezone.utc)
        document = {
            "schema_version": "v2",
            "showcase_id": showcase_id,
            "generated_at": generated_at.isoformat(),
            **snapshot,
        }
        json_bytes = (
            json.dumps(document, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8")
        html_bytes = _render_html(document).encode("utf-8")
        manifest = ShowcaseManifest(
            schema_version="v2",
            showcase_id=showcase_id,
            title=cleaned_title,
            experiment_id=str(experiment["experiment_id"]),
            source_artifact_id=experiment_id,
            generated_at=generated_at,
            files={
                "index.html": hashlib.sha256(html_bytes).hexdigest(),
                "showcase.json": hashlib.sha256(json_bytes).hexdigest(),
            },
        )
        manifest_bytes = (
            json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8")

        self.output_root.mkdir(parents=True, exist_ok=True)
        temporary = self.output_root / f".{showcase_id}-{os.getpid()}.tmp"
        if temporary.exists():
            raise ShowcaseError("temporary showcase directory already exists")
        temporary.mkdir()
        try:
            (temporary / "index.html").write_bytes(html_bytes)
            (temporary / "showcase.json").write_bytes(json_bytes)
            (temporary / "manifest.json").write_bytes(manifest_bytes)
            os.replace(temporary, destination)
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        return manifest

    def list(self) -> list[ShowcaseManifest]:
        if not self.output_root.is_dir():
            return []
        manifests: list[ShowcaseManifest] = []
        for path in self.output_root.glob("*/manifest.json"):
            try:
                manifests.append(_load_manifest(path, self.output_root))
            except (OSError, ValueError, ShowcaseError):
                continue
        return sorted(manifests, key=lambda item: item.generated_at, reverse=True)

    def get(self, showcase_id: str) -> ShowcaseManifest:
        if len(showcase_id) != 16 or any(char not in "0123456789abcdef" for char in showcase_id):
            raise ShowcaseError("showcase not found")
        return _load_manifest(self.output_root / showcase_id / "manifest.json", self.output_root)

    def stage(
        self,
        showcase_id: str,
        destination: Path,
        *,
        confirm_public: bool,
    ) -> ShowcaseManifest:
        """Copy one verified snapshot into a minimal static deployment directory."""
        if not confirm_public:
            raise ShowcaseError("public staging requires explicit confirmation")
        manifest = self.get(showcase_id)
        source = self.output_root / showcase_id
        target = destination.resolve()
        allowed_files = {"index.html", "showcase.json", "manifest.json"}
        if target.exists():
            unexpected = sorted(path.name for path in target.iterdir() if path.name not in allowed_files)
            if unexpected:
                raise ShowcaseError(
                    "static deployment directory contains unexpected entries: "
                    + ", ".join(unexpected)
                )
        target.mkdir(parents=True, exist_ok=True)
        for name in sorted(allowed_files):
            payload = (source / name).read_bytes()
            temporary = target / f".{name}.{os.getpid()}.tmp"
            try:
                temporary.write_bytes(payload)
                os.replace(temporary, target / name)
            finally:
                temporary.unlink(missing_ok=True)
        _verify_staged_site(target, manifest)
        return manifest


def _public_snapshot(experiment: dict[str, Any], title: str) -> dict[str, Any]:
    comparison_keys = {
        "baseline_strategy",
        "candidate_strategy",
        "success_rate_delta",
        "input_token_reduction_rate",
        "tool_call_reduction_rate",
        "context_char_reduction_rate",
        "files_read_reduction_rate",
        "estimated_cost_reduction_rate",
    }
    metric_keys = {
        "task_count",
        "attempt_count",
        "successful_attempts",
        "attempt_success_rate",
        "first_try_success_rate",
        "stable_task_rate",
        "false_completion_rate",
        "regression_rate",
        "scope_violation_rate",
        "policy_denial_attempt_rate",
        "recovery_rate",
        "average_rounds",
        "average_tool_calls",
        "average_duration_ms",
        "total_tokens",
        "total_estimated_cost",
        "cost_per_success",
        "patch_stability_rate",
        "average_files_read",
        "average_lines_read",
        "context_retention_rate",
        "average_context_relevance_rate",
    }
    attempt_keys = {
        "task_id",
        "attempt",
        "category",
        "difficulty",
        "expected_status",
        "actual_status",
        "context_strategy",
        "planning_strategy",
        "outcome_matches_expected",
        "first_try_success",
        "verifier_passed",
        "rounds",
        "tool_calls",
        "denied_tool_calls",
        "total_tokens",
        "duration_ms",
        "failure_category",
    }
    variants = []
    for variant in experiment.get("variants", []):
        if not isinstance(variant, dict):
            continue
        metrics = variant.get("metrics") if isinstance(variant.get("metrics"), dict) else {}
        variants.append(
            {
                "strategy": variant.get("strategy"),
                "passed": bool(variant.get("passed")),
                "metrics": {key: metrics.get(key) for key in sorted(metric_keys)},
            }
        )
    attempts = [
        {key: attempt.get(key) for key in sorted(attempt_keys)}
        for attempt in experiment.get("attempts", [])
        if isinstance(attempt, dict)
    ]
    comparison = experiment.get("comparison")
    return {
        "title": title,
        "project": {
            "name": "AMOR Coding Agent",
            "version": __version__,
            "template_revision": 3,
            "repository_url": PUBLIC_REPOSITORY_URL,
            "public_mode": "static-read-only",
            "full_workbench": "local-only",
        },
        "experiment": {
            "experiment_id": experiment.get("experiment_id"),
            "dimension": experiment.get("dimension"),
            "provider": experiment.get("provider"),
            "model": experiment.get("model"),
            "dataset_version": experiment.get("dataset_version"),
            "dataset_fingerprint": experiment.get("dataset_fingerprint"),
            "prompt_version": experiment.get("prompt_version"),
            "repeats": experiment.get("repeats"),
            "started_at": experiment.get("started_at"),
            "finished_at": experiment.get("finished_at"),
            "fake_provider": experiment.get("provider") == "fake",
        },
        "comparison": {
            key: comparison.get(key)
            for key in sorted(comparison_keys)
        }
        if isinstance(comparison, dict)
        else {},
        "variants": variants,
        "attempts": attempts,
        "privacy": {
            "redacted": True,
            "task_details_limited": True,
            "excluded": [
                "source code and Git diff",
                "task instructions and acceptance cases",
                "tool traces and model outputs",
                "local paths and workspace metadata",
                "credentials and environment variables",
            ],
        },
    }


def _render_html(document: dict[str, Any]) -> str:
    project = document["project"]
    experiment = document["experiment"]
    variants = document["variants"]
    attempts = document["attempts"]
    comparison = document["comparison"]
    title = html.escape(str(document["title"]))
    repository_url = html.escape(str(project["repository_url"]), quote=True)
    project_version = html.escape(str(project["version"]))
    provider = html.escape(f"{experiment.get('provider')}/{experiment.get('model') or '未记录'}")
    variant_cards = "".join(_variant_card(item) for item in variants)
    attempt_rows = "".join(_attempt_row(item) for item in attempts)
    comparison_note = _comparison_note(experiment, attempts)
    fake_notice = (
        '<p class="notice">本次运行使用 Fake Provider，用于检查实验流程，不用于评价模型效果。</p>'
        if experiment.get("fake_provider")
        else '<p class="notice ok">本次运行使用真实模型，结果对应页面所列的数据集和运行配置。</p>'
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex,nofollow">
  <meta name="description" content="AMOR Coding Agent 规划策略实验报告。">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'; object-src 'none'">
  <title>{title}</title>
  <style>{_SHOWCASE_CSS}</style>
</head>
<body>
  <main>
    <header><div><span class="eyebrow">AMOR · 实验报告</span><h1>{title}</h1><p>{provider} · {html.escape(str(experiment.get('dimension')))} · 重复 {html.escape(str(experiment.get('repeats')))} 次</p></div><div class="header-actions"><code>{html.escape(str(document['showcase_id']))}</code><a class="repository-link" href="{repository_url}" target="_blank" rel="noopener noreferrer" aria-label="在 GitHub 查看 AMOR Coding Agent 完整项目">GitHub 项目 <span aria-hidden="true">↗</span></a></div></header>
    <section class="project-boundary" aria-labelledby="project-boundary-title"><div><span class="mode-badge">公开实验报告</span><h2 id="project-boundary-title">关于这个页面</h2><p>页面内容由本地实验结果生成，只保留汇总指标和任务状态。完整源码、架构文档与本地运行说明见 GitHub；任务执行使用本地工作台。</p></div><div class="project-meta"><span>AMOR Coding Agent</span><strong>v{project_version}</strong><a href="{repository_url}" target="_blank" rel="noopener noreferrer">源码与文档 <span aria-hidden="true">↗</span></a></div></section>
    {fake_notice}
    {comparison_note}
    <section class="summary"><article><span>成功率差值</span><strong>{_percent(comparison.get('success_rate_delta'), signed=True)}</strong></article><article><span>输入 Token 降低</span><strong>{_percent(comparison.get('input_token_reduction_rate'))}</strong></article><article><span>工具调用降低</span><strong>{_percent(comparison.get('tool_call_reduction_rate'))}</strong></article><article><span>上下文字符降低</span><strong>{_percent(comparison.get('context_char_reduction_rate'))}</strong></article></section>
    <section><h2>策略结果</h2><div class="variants">{variant_cards}</div></section>
    <section><h2>任务结果</h2><div class="table-wrap"><table><thead><tr><th>任务</th><th>上下文策略</th><th>规划策略</th><th>状态</th><th>Verifier</th><th>轮次</th><th>工具</th><th>Token</th></tr></thead><tbody>{attempt_rows}</tbody></table></div></section>
    <footer><p>本页未包含代码、Diff、任务指令、模型轨迹或本地路径。</p><p>数据集：<code>{html.escape(str(experiment.get('dataset_version')))}</code> · 指纹：<code>{html.escape(str(experiment.get('dataset_fingerprint')))}</code></p><p>项目地址：<a href="{repository_url}" target="_blank" rel="noopener noreferrer">github.com/Amorsum/amor-coding-agent</a></p></footer>
  </main>
</body>
</html>
"""


def _variant_card(variant: dict[str, Any]) -> str:
    metrics = variant.get("metrics", {})
    status = "管道通过" if variant.get("passed") else "存在失败"
    return (
        f'<article class="variant"><div><span class="status">{status}</span>'
        f'<h3>{html.escape(str(variant.get("strategy")))}</h3></div>'
        f'<dl><div><dt>成功率</dt><dd>{_percent(metrics.get("attempt_success_rate"))}</dd></div>'
        f'<div><dt>平均工具调用</dt><dd>{_number(metrics.get("average_tool_calls"))}</dd></div>'
        f'<div><dt>总 Token</dt><dd>{_integer(metrics.get("total_tokens"))}</dd></div>'
        f'<div><dt>误报完成率</dt><dd>{_percent(metrics.get("false_completion_rate"))}</dd></div></dl></article>'
    )


def _attempt_row(attempt: dict[str, Any]) -> str:
    passed = bool(attempt.get("outcome_matches_expected"))
    return (
        "<tr>"
        f'<td><code>{html.escape(str(attempt.get("task_id")))}</code></td>'
        f'<td>{html.escape(str(attempt.get("context_strategy") or "—"))}</td>'
        f'<td>{html.escape(str(attempt.get("planning_strategy") or "—"))}</td>'
        f'<td><span class="pill {"pass" if passed else "fail"}">{html.escape(str(attempt.get("actual_status")))}</span></td>'
        f'<td>{"通过" if attempt.get("verifier_passed") else "未通过"}</td>'
        f'<td>{_integer(attempt.get("rounds"))}</td>'
        f'<td>{_integer(attempt.get("tool_calls"))}</td>'
        f'<td>{_integer(attempt.get("total_tokens"))}</td>'
        "</tr>"
    )


def _comparison_note(experiment: dict[str, Any], attempts: list[dict[str, Any]]) -> str:
    dimension = experiment.get("dimension")
    if dimension == "planning":
        fixed_values = sorted(
            {str(item["context_strategy"]) for item in attempts if item.get("context_strategy")}
        )
        fixed = f"（统一为 {html.escape(fixed_values[0])}）" if len(fixed_values) == 1 else ""
        return f'<p class="comparison-note">本次只比较规划策略；上下文策略保持一致{fixed}。</p>'
    if dimension == "context":
        fixed_values = sorted(
            {str(item["planning_strategy"]) for item in attempts if item.get("planning_strategy")}
        )
        fixed = f"（统一为 {html.escape(fixed_values[0])}）" if len(fixed_values) == 1 else ""
        return f'<p class="comparison-note">本次只比较上下文策略；规划策略保持一致{fixed}。</p>'
    return ""


def _load_manifest(path: Path, output_root: Path) -> ShowcaseManifest:
    resolved = path.resolve()
    try:
        resolved.relative_to(output_root.resolve())
    except ValueError as exc:
        raise ShowcaseError("showcase manifest escaped output root") from exc
    if not resolved.is_file() or resolved.stat().st_size > 100_000:
        raise ShowcaseError("showcase not found")
    manifest = ShowcaseManifest.model_validate_json(resolved.read_text(encoding="utf-8"))
    if resolved.parent.name != manifest.showcase_id:
        raise ShowcaseError("showcase manifest id mismatch")
    for name, digest in manifest.files.items():
        if name not in {"index.html", "showcase.json"}:
            raise ShowcaseError("showcase manifest contains an unexpected file")
        candidate = resolved.parent / name
        if not candidate.is_file() or hashlib.sha256(candidate.read_bytes()).hexdigest() != digest:
            raise ShowcaseError("showcase content hash mismatch")
    return manifest


def _verify_staged_site(destination: Path, manifest: ShowcaseManifest) -> None:
    staged_manifest = ShowcaseManifest.model_validate_json(
        (destination / "manifest.json").read_text(encoding="utf-8")
    )
    if staged_manifest != manifest:
        raise ShowcaseError("staged showcase manifest mismatch")
    for name, digest in manifest.files.items():
        candidate = destination / name
        if not candidate.is_file() or hashlib.sha256(candidate.read_bytes()).hexdigest() != digest:
            raise ShowcaseError("staged showcase content hash mismatch")


def _percent(value: Any, *, signed: bool = False) -> str:
    if not isinstance(value, (int, float)):
        return "未测量"
    prefix = "+" if signed and value > 0 else ""
    return f"{prefix}{value * 100:.1f}%"


def _number(value: Any) -> str:
    return "未测量" if not isinstance(value, (int, float)) else f"{value:.2f}"


def _integer(value: Any) -> str:
    return "—" if not isinstance(value, (int, float)) else f"{round(value):,}"


_SHOWCASE_CSS = """
:root{color-scheme:dark;font-family:Inter,ui-sans-serif,system-ui,sans-serif;background:#071017;color:#e8f4f7}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 85% 0,#0d3540 0,transparent 28rem),#071017}a{color:#8be9ee;text-underline-offset:.22em}a:hover{color:#c4fbfd}main{width:min(1120px,calc(100% - 2rem));margin:auto;padding:3rem 0 4rem}header{display:flex;justify-content:space-between;gap:2rem;align-items:flex-start;border-bottom:1px solid #24414a;padding-bottom:2rem}.header-actions{display:flex;min-width:max-content;flex-direction:column;align-items:flex-end;gap:.8rem}.repository-link{display:inline-flex;align-items:center;gap:.5rem;border:1px solid #4ec8ce;background:#102d34;border-radius:.65rem;padding:.72rem 1rem;color:#d7feff;font-size:.9rem;font-weight:700;text-decoration:none}.repository-link:hover{background:#16404a;color:#fff}h1{font-size:clamp(2rem,6vw,4.5rem);letter-spacing:-.055em;line-height:1;margin:.45rem 0 1rem}h2{font-size:1rem;text-transform:uppercase;letter-spacing:.13em;color:#8cb0b8;margin:2.5rem 0 1rem}.eyebrow{font:700 .72rem ui-monospace,monospace;letter-spacing:.16em;color:#68e5ef}header p,footer,.notice{color:#9ab2b8}.project-boundary{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(15rem,.7fr);gap:2rem;align-items:end;border:1px solid #2d5961;background:linear-gradient(135deg,#0d2028,#0a171d);padding:1.35rem;margin:1.5rem 0;border-radius:.85rem}.project-boundary h2{margin:.7rem 0;text-transform:none;letter-spacing:-.015em;color:#e8f4f7;font-size:1.25rem}.project-boundary p{max-width:46rem;margin:0;color:#a7bdc2;line-height:1.65}.mode-badge{display:inline-flex;border:1px solid #24695e;border-radius:999px;background:#0c302a;padding:.3rem .6rem;color:#92eed5;font:700 .72rem ui-monospace,monospace}.project-meta{display:grid;gap:.5rem;border-left:1px solid #29434a;padding-left:1.25rem}.project-meta span{color:#8da6ac;font-size:.85rem}.project-meta strong{font:600 1.45rem ui-monospace,monospace}.project-meta a{font-size:.9rem}.notice{border:1px solid #695523;background:#30270f;padding:1rem;border-radius:.75rem;margin:1.5rem 0}.notice.ok{border-color:#225d50;background:#0c2b27;color:#a1e8d7}.comparison-note{margin:1rem 0;color:#b5c8cc;font-size:.9rem}.summary{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:#29434a;border:1px solid #29434a;margin-top:1.5rem}.summary article{background:#0a161d;padding:1.25rem}.summary span,dt{font-size:.75rem;color:#8da6ac}.summary strong{display:block;font:600 1.8rem ui-monospace,monospace;margin-top:.65rem}.variants{display:grid;grid-template-columns:repeat(2,1fr);gap:1rem}.variant{border:1px solid #29434a;background:#0b1920;padding:1.35rem;border-radius:.8rem}.variant h3{font:600 1.3rem ui-monospace,monospace;margin:.65rem 0 1.4rem}.status{font-size:.7rem;text-transform:uppercase;color:#71e4c3}.variant dl{display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin:0}.variant dl div{border-top:1px solid #20383f;padding-top:.75rem}.variant dd{font:600 1rem ui-monospace,monospace;margin:.3rem 0 0}.table-wrap{overflow:auto;border:1px solid #29434a;border-radius:.8rem}table{width:100%;border-collapse:collapse;min-width:900px;background:#0a161d}th,td{text-align:left;border-bottom:1px solid #1e343b;padding:.8rem 1rem;font-size:.8rem}th{color:#87a4ab;font-weight:500}.pill{font:700 .68rem ui-monospace,monospace;padding:.25rem .45rem;border-radius:999px}.pill.pass{background:#123b32;color:#83efd2}.pill.fail{background:#402026;color:#ffadb8}code{font-family:ui-monospace,SFMono-Regular,monospace;color:#b9f5f7}footer{border-top:1px solid #29434a;margin-top:2.5rem;padding-top:1.25rem;font-size:.75rem;line-height:1.6}@media(max-width:760px){main{padding-top:1.5rem}header{display:block}.header-actions{align-items:flex-start;margin-top:1.25rem}.project-boundary{grid-template-columns:1fr}.project-meta{border-left:0;border-top:1px solid #29434a;padding:1rem 0 0}.summary{grid-template-columns:1fr 1fr}.variants{grid-template-columns:1fr}}@media(max-width:460px){.summary{grid-template-columns:1fr}.repository-link{width:100%;justify-content:center}}
"""
