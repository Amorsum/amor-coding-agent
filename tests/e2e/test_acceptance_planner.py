from pathlib import Path

from amor.acceptance import load_acceptance_plan, run_acceptance_planning
from amor.benchmarks import BenchmarkLayout
from amor.providers import FakeModelProvider, ModelToolCall, ModelTurn
from amor.workspace import WorkspaceManager


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def turn(number: int, name: str, arguments: dict) -> ModelTurn:
    return ModelTurn(
        response_id=f"plan_resp_{number}",
        tool_calls=[ModelToolCall(call_id=f"plan_call_{number}", name=name, arguments=arguments)],
        usage={"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
    )


def test_read_only_planner_freezes_an_external_acceptance_contract(tmp_path: Path) -> None:
    layout = BenchmarkLayout(project_root() / "benchmarks")
    fixture = WorkspaceManager().create_from_fixture(
        layout.fixtures / "python_utils",
        tmp_path / "repository-fixture",
    )
    provider = FakeModelProvider(
        [
            turn(1, "search_code", {"query": "def average", "path": "src"}),
            turn(2, "read_file", {"path": "src/calculator.py", "start_line": 1, "end_line": 40}),
            turn(3, "read_file", {"path": "tests/test_calculator.py", "start_line": 1, "end_line": 80}),
            turn(
                4,
                "submit_acceptance_plan",
                {
                    "acceptance_criteria": [
                        "average([]) returns 0.0",
                        "non-empty averages remain unchanged",
                    ],
                    "preserved_behaviors": ["non-empty inputs keep arithmetic mean behavior"],
                    "edge_cases": ["empty list"],
                    "python_cases": [
                        {
                            "name": "empty collection",
                            "module": "src.calculator",
                            "callable": "average",
                            "args_json": "[[]]",
                            "kwargs_json": "{}",
                            "expectation": "equals",
                            "expected_json": "0.0",
                            "exception_type": "",
                            "rationale": "directly exercises the requested empty-input behavior",
                        },
                        {
                            "name": "existing arithmetic mean",
                            "module": "src.calculator",
                            "callable": "average",
                            "args_json": "[[2.0, 4.0]]",
                            "kwargs_json": "{}",
                            "expectation": "equals",
                            "expected_json": "3.0",
                            "exception_type": "",
                            "rationale": "protects existing non-empty behavior",
                        },
                    ],
                    "questions": [],
                    "summary": "Verify the new empty-input result without changing non-empty averages.",
                },
            ),
        ]
    )

    plan = run_acceptance_planning(
        repository=fixture.source_repository,
        instruction="average([]) must return 0.0",
        acceptance_criteria=["average([]) returns 0.0"],
        allowed_paths=["src/**"],
        validation_commands=None,
        provider_name="fake",
        model="fake-planner",
        provider=provider,
        artifacts_root=tmp_path / "plans",
    )

    assert plan.status == "READY"
    assert plan.baseline_commit
    assert len(plan.python_cases) == 2
    assert plan.evidence_files == ["src/calculator.py", "tests/test_calculator.py"]
    plan_path = tmp_path / "plans" / plan.plan_id / "acceptance-plan.json"
    assert load_acceptance_plan(plan_path) == plan
    assert (tmp_path / "plans" / plan.plan_id / "report.md").is_file()
    planned_source = (tmp_path / "plans" / plan.plan_id / "workspace" / "src/calculator.py")
    assert planned_source.read_text(encoding="utf-8") == (
        fixture.source_repository / "src/calculator.py"
    ).read_text(encoding="utf-8")
    exposed_tools = {tool["name"] for tool in provider.requests[0]["tools"]}
    assert exposed_tools == {"list_files", "search_code", "read_file", "submit_acceptance_plan"}
