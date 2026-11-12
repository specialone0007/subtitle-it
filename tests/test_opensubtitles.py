import http.server
import io
import json
import os
import stat
import threading
import urllib.request
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
        ("opensubtitles.com", "https://opensubtitles.com/api/v1"),
        (None, opensubtitles.API),
        ("", opensubtitles.API),
        ("other.example", opensubtitles.API),
        ("opensubtitles.com.evil.example", opensubtitles.API),
        ("evilopensubtitles.com", opensubtitles.API),
        ("http://other.example", opensubtitles.API),
        ("other.example/x?y=", opensubtitles.API),
        ("user@other.example", opensubtitles.API),
    ],
)
def test_the_login_host_is_used_only_when_it_is_opensubtitles_over_https(host, base):
    assert opensubtitles._base({"base_url": host}) == base


def test_download_refuses_a_link_that_is_not_https(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(opensubtitles, "load_creds", lambda config: {"api_key": "k"})
    monkeypatch.setattr(opensubtitles, "login", lambda config, creds, force=False: creds)
    monkeypatch.setattr(opensubtitles, "_request", lambda *a, **k: {"link": "http://dl.example/x.srt"})

    def no_fetch(*a, **k):
        raise AssertionError("an http link must not be fetched")

    monkeypatch.setattr(opensubtitles, "_open", no_fetch)
    with pytest.raises(opensubtitles.ApiError, match="not https"):
        opensubtitles.download(tmp_path, 42, tmp_path / "x.srt", tmp_path / "cache")


def _server(code: int, location: str | None, seen: list):
    """A local server that records each request's headers and answers with `code`."""

    class Handler(http.server.BaseHTTPRequestHandler):
        def _answer(self):
            seen.append(dict(self.headers))
            self.send_response(code)
            if location:
                self.send_header("Location", location)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b"{}")

        do_GET = do_POST = _answer

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_an_api_redirect_to_another_host_is_refused_and_gets_no_credentials():
    foreign_seen, api_seen = [], []
    foreign = _server(200, None, foreign_seen)
    api = _server(302, f"http://127.0.0.1:{foreign.server_port}/steal", api_seen)
    try:
        with pytest.raises(opensubtitles.ApiError, match="not opensubtitles.com over https"):
            opensubtitles._request(
                "GET", f"http://127.0.0.1:{api.server_port}/api/v1/infos/user", {"api_key": "k", "token": "t"}, auth=True
            )
    finally:
        api.shutdown()
        foreign.shutdown()
    assert api_seen and api_seen[0]["Api-Key"] == "k"
    assert foreign_seen == []


@pytest.mark.parametrize(
    "target",
    ["https://other.example/x", "http://api.opensubtitles.com/x", "https://opensubtitles.com.evil.example/x"],
)
def test_an_api_redirect_off_opensubtitles_over_https_is_refused(target):
    req = urllib.request.Request("https://api.opensubtitles.com/api/v1/subtitles", headers={"Api-Key": "k"})
    with pytest.raises(opensubtitles.ApiError):
        opensubtitles._ApiRedirect().redirect_request(req, io.BytesIO(), 302, "Found", {}, target)


def test_an_api_redirect_within_opensubtitles_is_followed_with_the_key():
    req = urllib.request.Request("https://api.opensubtitles.com/api/v1/subtitles?Query=x", headers={"Api-Key": "k"})
    new = opensubtitles._ApiRedirect().redirect_request(
        req, io.BytesIO(), 301, "Moved", {}, "https://api.opensubtitles.com/api/v1/subtitles?query=x"
    )
    assert new.full_url == "https://api.opensubtitles.com/api/v1/subtitles?query=x"
    assert new.get_header("Api-key") == "k"


def test_the_file_download_sends_no_key_or_token(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(opensubtitles, "load_creds", lambda config: {"api_key": "k", "token": "t"})
    monkeypatch.setattr(opensubtitles, "login", lambda config, creds, force=False: creds)
    monkeypatch.setattr(opensubtitles, "_request", lambda *a, **k: {"link": "https://dl.example/x.srt"})
    sent = []

    def fetch(req, timeout, api):
        sent.append((req, api))
        return io.BytesIO(b"1\n00:00:01,000 --> 00:00:02,000\nHi\n")

    monkeypatch.setattr(opensubtitles, "_open", fetch)
    opensubtitles.download(tmp_path, 42, tmp_path / "x.srt", tmp_path / "cache")
    [(req, api)] = sent
    headers = {k.lower() for k, _ in req.header_items()}
    assert api is False and "api-key" not in headers and "authorization" not in headers


def test_the_file_download_follows_only_https_redirects():
    req = urllib.request.Request("https://dl.example/x.srt")
    with pytest.raises(opensubtitles.ApiError, match="not https"):
        opensubtitles._HttpsRedirect().redirect_request(req, io.BytesIO(), 302, "Found", {}, "http://cdn.example/x.srt")
    new = opensubtitles._HttpsRedirect().redirect_request(req, io.BytesIO(), 302, "Found", {}, "https://cdn.example/x.srt")
    assert new.full_url == "https://cdn.example/x.srt"
