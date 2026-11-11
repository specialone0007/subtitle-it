from pathlib import Path

import opensubtitles


def fake_account(monkeypatch, token: str | None, allowed: int | None = None) -> list[str]:
    calls: list[str] = []
    monkeypatch.setattr(opensubtitles, "load_creds", lambda config: {"api_key": "k"})
    monkeypatch.setattr(opensubtitles, "login", lambda config, creds: {**creds, "token": token} if token else creds)

    def request(method, url, creds, body=None, auth=False):
        calls.append(url)
        return {"data": {"level": "Sub leecher", "allowed_downloads": allowed, "remaining_downloads": allowed}}

    monkeypatch.setattr(opensubtitles, "_request", request)
    return calls


def test_status_with_a_free_login_reports_20_downloads_and_no_warning(monkeypatch):
    calls = fake_account(monkeypatch, token="t", allowed=20)
    s = opensubtitles.status(Path("cfg"))
    assert s["logged_in"] is True
    assert s["allowed_downloads"] == 20
    assert s["warning"] is None
    assert calls[0].endswith("/infos/user")


def test_status_warns_when_the_login_still_gets_the_key_only_limit(monkeypatch):
    fake_account(monkeypatch, token="t", allowed=5)
    assert "limit is 5" in opensubtitles.status(Path("cfg"))["warning"]


def test_status_without_a_login_reports_5_downloads(monkeypatch):
    calls = fake_account(monkeypatch, token=None)
    s = opensubtitles.status(Path("cfg"))
    assert s == {"logged_in": False, "daily_downloads": 5, "note": "key only; add a free account login for 20 a day"}
    assert calls == []
