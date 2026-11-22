"""Tests for application configuration."""

from __future__ import annotations

import pytest

from tests.helpers import bare_settings


def test_settings_defaults() -> None:
    """Settings use documented defaults."""
    s = bare_settings()
    assert s.host == "0.0.0.0"
    assert s.port == 2909
    assert s.debug is False
    assert s.log_level == "INFO"
    assert s.database_url == "sqlite+aiosqlite:////data/openartifact.db"
    assert str(s.data_dir) == "/data"
    assert s.is_production is True


def test_settings_is_production_false() -> None:
    """Debug mode makes settings report non-production."""
    s = bare_settings(debug=True)
    assert s.is_production is False


def test_settings_env_prefix() -> None:
    """Settings can be overridden via OPENARTIFACT_ prefixed env vars."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("OPENARTIFACT_HOST", "127.0.0.1")
        mp.setenv("OPENARTIFACT_PORT", "9999")
        mp.setenv("OPENARTIFACT_DEBUG", "true")
        s = bare_settings()
        assert s.host == "127.0.0.1"
        assert s.port == 9999
        assert s.debug is True


def test_settings_env_override_int() -> None:
    """Integer settings are parsed correctly from env."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("OPENARTIFACT_PORT", "8080")
        s = bare_settings()
        assert s.port == 8080


def test_settings_env_override_bool() -> None:
    """Boolean settings are parsed correctly from env."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("OPENARTIFACT_DEBUG", "true")
        s = bare_settings()
        assert s.debug is True


def test_settings_secret_key_default() -> None:
    """Default secret key is a placeholder."""
    s = bare_settings()
    assert s.secret_key == "change-me-in-production"


def test_settings_invalid_env_value() -> None:
    """Invalid port value raises validation error."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("OPENARTIFACT_PORT", "not-a-number")
        with pytest.raises(ValueError):
            bare_settings()


def test_the_security_and_limit_defaults_are_the_safe_ones() -> None:
    s = bare_settings()
    assert s.api_token == "" and s.allowed_hosts == "" and s.cookie_secure == "auto"
    assert s.csp_script_unsafe_inline is False  # inline scripts are an opt-out only
    assert (s.max_request_bytes, s.max_concurrent_runs, s.max_sse_subscribers) == (1048576, 8, 50)


def test_the_security_settings_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENARTIFACT_COOKIE_SECURE", "true")
    monkeypatch.setenv("OPENARTIFACT_MAX_CONCURRENT_RUNS", "2")
    monkeypatch.setenv("OPENARTIFACT_CSP_SCRIPT_UNSAFE_INLINE", "true")
    s = bare_settings()
    assert (s.cookie_secure, s.max_concurrent_runs, s.csp_script_unsafe_inline) == ("true", 2, True)
    monkeypatch.setenv("OPENARTIFACT_COOKIE_SECURE", "sometimes")
    with pytest.raises(ValueError, match="cookie_secure"):
        bare_settings()


def test_the_allowed_hosts_are_trimmed_lower_case_patterns() -> None:
    s = bare_settings(allowed_hosts=" Example.COM, *.Example.org ,,")
    assert s.allowed_host_list == ["example.com", "*.example.org"]
    assert bare_settings().allowed_host_list == []


@pytest.mark.parametrize(
    ("token", "secret", "problems"),
    [
        ("", "change-me-in-production", []),  # open mode needs neither
        ("x" * 32, "k" * 40, []),
        ("x" * 31, "k" * 40, ["at least 32 characters"]),
        ("x" * 32, "change-me-in-production", ["OPENARTIFACT_SECRET_KEY must be set"]),
        ("x" * 32, "", ["OPENARTIFACT_SECRET_KEY must be set"]),
        ("short", "", ["at least 32 characters", "OPENARTIFACT_SECRET_KEY must be set"]),
    ],
)
def test_security_problems_name_what_is_wrong(token: str, secret: str, problems: list[str]) -> None:
    found = bare_settings(api_token=token, secret_key=secret).security_problems()
    assert len(found) == len(problems)
    for message, expected in zip(found, problems, strict=True):
        assert expected in message
