import json
import os
import stat
from pathlib import Path

import pytest

import opensubtitles


def fake_account(monkeypatch, token: str | None, allowed: int | None = None) -> list[tuple[str, bool]]:
    calls: list[tuple[str, bool]] = []
    monkeypatch.setattr(opensubtitles, "load_creds", lambda config: {"api_key": "k"})
    monkeypatch.setattr(opensubtitles, "login", lambda config, creds: {**creds, "token": token} if token else creds)

    def request(method, url, creds, body=None, auth=False):
        calls.append((url, auth))
        return {"data": {"level": "Sub leecher", "allowed_downloads": allowed, "remaining_downloads": allowed}}

    monkeypatch.setattr(opensubtitles, "_request", request)
    return calls


def test_status_with_a_free_login_reports_20_downloads_and_no_warning(monkeypatch):
    calls = fake_account(monkeypatch, token="t", allowed=20)
    s = opensubtitles.status(Path("cfg"))
    assert s["logged_in"] is True
    assert s["allowed_downloads"] == 20
    assert s["warning"] is None
    url, auth = calls[0]
    assert url.endswith("/infos/user")
    assert auth is True  # the lookup must send the login token, or the API reports the key-only 5


def test_status_warns_when_the_login_still_gets_the_key_only_limit(monkeypatch):
    fake_account(monkeypatch, token="t", allowed=5)
    assert "limit is 5" in opensubtitles.status(Path("cfg"))["warning"]


def test_status_without_a_login_reports_5_downloads(monkeypatch):
    calls = fake_account(monkeypatch, token=None)
    s = opensubtitles.status(Path("cfg"))
    assert s == {"logged_in": False, "daily_downloads": 5, "note": "key only; add a free account login for 20 a day"}
    assert calls == []


def test_config_with_a_tilde_means_the_home_folder(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    seen = []
    monkeypatch.setattr(opensubtitles, "status", lambda config: seen.append(config) or {})
    opensubtitles.main(["status", "--config", "~/cfg"])
    assert seen == [tmp_path / "cfg"]


def test_saved_credentials_are_readable_only_by_the_owner(tmp_path: Path):
    opensubtitles.save_creds(tmp_path / "cfg", {"api_key": "k"})
    p = tmp_path / "cfg" / "credentials.json"
    assert json.loads(p.read_text(encoding="utf-8")) == {"api_key": "k"}
    assert not (tmp_path / "cfg" / "credentials.tmp").exists()
    assert b"\r" not in p.read_bytes()
    if os.name != "nt":
        assert stat.S_IMODE(p.stat().st_mode) == 0o600


@pytest.mark.parametrize(
    ("host", "base"),
    [
        ("vip-api.opensubtitles.com", "https://vip-api.opensubtitles.com/api/v1"),
        (None, opensubtitles.API),
        ("http://other.example", opensubtitles.API),
        ("other.example/x?y=", opensubtitles.API),
        ("user@other.example", opensubtitles.API),
    ],
)
def test_the_login_host_is_used_only_as_a_plain_host_over_https(host, base):
    assert opensubtitles._base({"base_url": host}) == base


def test_download_refuses_a_link_that_is_not_https(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(opensubtitles, "load_creds", lambda config: {"api_key": "k"})
    monkeypatch.setattr(opensubtitles, "login", lambda config, creds, force=False: creds)
    monkeypatch.setattr(opensubtitles, "_request", lambda *a, **k: {"link": "http://dl.example/x.srt"})

    def no_fetch(*a, **k):
        raise AssertionError("an http link must not be fetched")

    monkeypatch.setattr(opensubtitles.urllib.request, "urlopen", no_fetch)
    with pytest.raises(opensubtitles.ApiError, match="not https"):
        opensubtitles.download(tmp_path, 42, tmp_path / "x.srt", tmp_path / "cache")
