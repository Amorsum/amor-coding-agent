from pathlib import Path

import pytest

from amor.policy import PolicyEngine, PolicyViolation


def make_policy(root: Path) -> PolicyEngine:
    return PolicyEngine(
        root,
        allowed_write_patterns=["src/**"],
        allowed_commands=[["python", "-m", "unittest"]],
    )


def test_allows_scoped_source_write(tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    target = source / "example.py"
    target.write_text("value = 1\n", encoding="utf-8")

    assert make_policy(tmp_path).resolve_write("src/example.py") == target.resolve()


@pytest.mark.parametrize(
    "requested",
    ["../outside.txt", ".git/config", ".env", "nested/.env.local"],
)
def test_denies_workspace_escape_and_sensitive_paths(tmp_path: Path, requested: str) -> None:
    with pytest.raises(PolicyViolation):
        make_policy(tmp_path).resolve_read(requested)


def test_denies_out_of_scope_write(tmp_path: Path) -> None:
    with pytest.raises(PolicyViolation, match="outside task scope"):
        make_policy(tmp_path).resolve_write("tests/test_example.py")


def test_validation_command_requires_exact_match(tmp_path: Path) -> None:
    policy = make_policy(tmp_path)

    assert policy.validate_command(["python", "-m", "unittest"]) == (
        "python",
        "-m",
        "unittest",
    )
    with pytest.raises(PolicyViolation, match="allowlist"):
        policy.validate_command(["python", "-c", "print('unexpected')"])

