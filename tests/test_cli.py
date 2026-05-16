"""CLI 参数校验测试。"""

import json
import tempfile
import os

from click.testing import CliRunner
from wechat_fetcher.cli import main


def test_fetch_missing_biz():
    runner = CliRunner()
    result = runner.invoke(main, ["fetch", "--biz", "nonexistent"])
    assert result.exit_code == 1
    assert "No stored params" in result.stdout


def test_run_no_args():
    runner = CliRunner()
    result = runner.invoke(main, ["run"])
    assert result.exit_code == 1
    assert "--biz" in result.stdout or "--all" in result.stdout


def test_status():
    runner = CliRunner()
    result = runner.invoke(main, ["status"])
    assert result.exit_code == 0
    assert "去重索引" in result.stdout


def test_fetch_invalid_days():
    runner = CliRunner()
    result = runner.invoke(main, ["fetch", "--biz", "test", "--days", "abc"])
    assert result.exit_code != 0


def test_download_missing_file():
    runner = CliRunner()
    result = runner.invoke(main, ["download", "--input", "/nonexistent/file.json"])
    assert result.exit_code == 1
