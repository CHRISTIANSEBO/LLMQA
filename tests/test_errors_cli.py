"""Typed errors + friendly CLI behavior (--version, graceful error exit)."""
from __future__ import annotations

import pytest

import cli
from llmqa import __version__
from llmqa.exceptions import ConfigError, DatasetError, LLMQAError, MissingAPIKeyError
from llmqa.runner import load_dataset


def test_missing_dataset_raises_dataset_error():
    with pytest.raises(DatasetError, match="not found"):
        load_dataset("/no/such/dataset.yaml")


def test_non_list_dataset_raises_dataset_error(tmp_path):
    f = tmp_path / "bad.yaml"
    f.write_text("just: a mapping\nnot: a list\n")
    with pytest.raises(DatasetError, match="must be a list"):
        load_dataset(str(f))


def test_invalid_case_raises_dataset_error(tmp_path):
    f = tmp_path / "bad.yaml"
    f.write_text("- id: x\n  input: q\n")  # missing required `expected`
    with pytest.raises(DatasetError, match="invalid"):
        load_dataset(str(f))


def test_empty_dataset_raises_dataset_error(tmp_path):
    f = tmp_path / "empty.yaml"
    f.write_text("[]\n")
    with pytest.raises(DatasetError, match="empty"):
        load_dataset(str(f))


def test_bad_yaml_raises_dataset_error(tmp_path):
    f = tmp_path / "bad.yaml"
    f.write_text("- id: x\n  input: [unterminated\n")
    with pytest.raises(DatasetError, match="not valid YAML"):
        load_dataset(str(f))


def test_exception_hierarchy():
    assert issubclass(DatasetError, LLMQAError)
    assert issubclass(ConfigError, LLMQAError)
    # Kept as RuntimeError too for backwards compatibility.
    assert issubclass(MissingAPIKeyError, ConfigError)
    assert issubclass(MissingAPIKeyError, RuntimeError)


def test_cli_version_flag(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_cli_reports_dataset_error_cleanly(capsys):
    # A bad dataset should exit 2 with a one-line error, not a traceback.
    code = cli.main(["run", "--provider", "mock", "--dataset", "/no/such.yaml", "--no-store"])
    assert code == 2
    err = capsys.readouterr().err
    assert err.startswith("error: ")
    assert "Traceback" not in err
