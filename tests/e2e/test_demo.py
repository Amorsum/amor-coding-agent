import json
from pathlib import Path

from amor.domain import TerminalStatus
from amor.runner import run_demo


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_two_task_demo_produces_verified_reports_and_recovery_trace(tmp_path: Path) -> None:
    reports = run_demo(project_root(), tmp_path / "artifacts")

    assert len(reports) == 2
    assert all(report.final_status == TerminalStatus.SUCCEEDED for report in reports)
    assert all(report.verification.passed for report in reports)
    assert all(report.git_diff for report in reports)
    assert len({report.baseline_commit for report in reports}) == 1

    by_id = {report.task.task_id: report for report in reports}
    assert by_id["py_utils_average_empty"].state.round == 1
    assert by_id["py_utils_port_range"].state.round == 2

    port_trace_path = Path(by_id["py_utils_port_range"].trace_path)
    port_trace = port_trace_path.read_text(encoding="utf-8")
    assert '"to": "DIAGNOSING"' in port_trace
    assert port_trace.count('"tool": "run_validation"') == 2
    assert '"tool": "get_git_diff"' in port_trace

    report_path = port_trace_path.parent / "final-report.json"
    report_data = json.loads(report_path.read_text(encoding="utf-8"))
    assert report_data["verification"]["passed"] is True
    assert any(check["name"] == "hidden_tests" for check in report_data["verification"]["checks"])
