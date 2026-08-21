from typer.testing import CliRunner

from cosmya import __version__
from cosmya.cli.main import app

runner = CliRunner()


def test_version_flag_prints_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_short_version_flag():
    result = runner.invoke(app, ["-v"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_help_flag_lists_config_command():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "config" in result.stdout
    assert "audit" in result.stdout


def test_audit_without_selected_model_fails_clearly(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    result = runner.invoke(app, ["audit", str(project_dir)])
    assert result.exit_code != 0
    assert "No model selected" in result.stdout


def test_audit_rejects_nonexistent_path(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    result = runner.invoke(app, ["audit", str(tmp_path / "does-not-exist")])
    assert result.exit_code != 0
    assert "Not a directory" in result.stdout


def test_no_args_shows_help_without_error():
    result = runner.invoke(app, [])
    # Typer's no_args_is_help convention exits 2 (its standard "showed help,
    # no command given" code) while still printing the full help text.
    assert result.exit_code == 2
    assert "Usage" in result.stdout
