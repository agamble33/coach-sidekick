import socket

import pytest

from muse_replay.__main__ import main
from muse_replay.health import health_report


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*a, **k):
        raise AssertionError("health check must not open network connections")

    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)


def test_nothing_configured_exits_1():
    code, text = health_report({})
    assert code == 1
    assert "meta_model_api: missing" in text
    assert "no model provider configured" in text


def test_one_provider_exits_0_and_hides_key():
    code, text = health_report({"BASETEN_API_KEY": "SECRET-BT"})
    assert code == 0
    assert "baseten_muse_spark_open: configured" in text
    assert "SECRET" not in text


def test_bad_config_exits_2():
    code, text = health_report({"META_BASE_URL": "http://insecure"})
    assert code == 2
    assert "config error" in text


def test_cli_usage_error(capsys):
    assert main([]) == 64
    assert "usage" in capsys.readouterr().err


def test_cli_health(monkeypatch, capsys):
    for k in ["META_API_KEY", "META_BASE_URL", "BASETEN_API_KEY", "BASETEN_BASE_URL", "BASETEN_MODEL"]:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("BASETEN_API_KEY", "x")
    assert main(["health"]) == 0
    assert "configured" in capsys.readouterr().out
