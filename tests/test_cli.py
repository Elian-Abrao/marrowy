from __future__ import annotations

from typer.testing import CliRunner

from marrowy.cli.main import app


def test_cli_help():
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Marrowy CLI" in result.stdout
    assert "dev-web" in result.stdout
    assert "dev-console" in result.stdout
    assert "doctor" in result.stdout
