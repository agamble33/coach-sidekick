import pytest

from coach.config import (
    BASETEN_DEFAULT_MODEL,
    BASETEN_DEFAULT_URL,
    ConfigError,
    load_settings,
)


def test_empty_env_has_no_providers():
    s = load_settings({})
    assert s.providers() == {"meta_model_api": False, "baseten_muse_spark_open": False}
    assert s.baseten_base_url == BASETEN_DEFAULT_URL
    assert s.baseten_model == BASETEN_DEFAULT_MODEL


def test_meta_needs_key_and_url():
    assert not load_settings({"META_API_KEY": "k"}).meta_configured
    assert not load_settings({"META_BASE_URL": "https://x.example"}).meta_configured
    s = load_settings({"META_API_KEY": "k", "META_BASE_URL": "https://x.example/v1/"})
    assert s.meta_configured
    assert s.meta_base_url == "https://x.example/v1"  # trailing slash stripped


def test_baseten_key_alone_enables_it():
    assert load_settings({"BASETEN_API_KEY": "b"}).baseten_configured


def test_blank_values_count_as_missing():
    s = load_settings({"META_API_KEY": "  ", "META_BASE_URL": "", "BASETEN_API_KEY": "\t"})
    assert not s.meta_configured
    assert not s.baseten_configured


@pytest.mark.parametrize("bad", ["http://x.example", "x.example", "https://", "ftp://x"])
def test_non_https_urls_rejected(bad):
    with pytest.raises(ConfigError):
        load_settings({"META_BASE_URL": bad})
    with pytest.raises(ConfigError):
        load_settings({"BASETEN_BASE_URL": bad})


def test_overrides():
    s = load_settings({"BASETEN_BASE_URL": "https://alt.example/v1", "BASETEN_MODEL": "m"})
    assert s.baseten_base_url == "https://alt.example/v1"
    assert s.baseten_model == "m"


def test_keys_never_in_repr():
    s = load_settings({"META_API_KEY": "SECRET-META", "BASETEN_API_KEY": "SECRET-BT"})
    assert "SECRET" not in repr(s)
    assert "SECRET" not in str(s)


def test_defaults_to_os_environ(monkeypatch):
    monkeypatch.setenv("BASETEN_API_KEY", "from-env")
    assert load_settings().baseten_configured
