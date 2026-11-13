import http.server
import io
import json
import os
import stat
import threading
import urllib.error
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


def test_a_download_larger_than_the_cap_is_refused_and_not_cached(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(opensubtitles, "load_creds", lambda config: {"api_key": "k"})
    monkeypatch.setattr(opensubtitles, "login", lambda config, creds, force=False: creds)
    monkeypatch.setattr(opensubtitles, "_request", lambda *a, **k: {"link": "https://dl.example/x.srt"})
    big = b"x" * (opensubtitles.MAX_SUBTITLE_BYTES + 1)
    monkeypatch.setattr(opensubtitles, "_open", lambda req, timeout, api: io.BytesIO(big))
    with pytest.raises(opensubtitles.ApiError, match="larger than 5 MB"):
        opensubtitles.download(tmp_path, 42, tmp_path / "x.srt", tmp_path / "cache")
    assert not (tmp_path / "x.srt").exists() and not (tmp_path / "cache").exists()


def test_the_file_download_follows_only_https_redirects():
    req = urllib.request.Request("https://dl.example/x.srt")
    with pytest.raises(opensubtitles.ApiError, match="not https"):
        opensubtitles._HttpsRedirect().redirect_request(req, io.BytesIO(), 302, "Found", {}, "http://cdn.example/x.srt")
    new = opensubtitles._HttpsRedirect().redirect_request(req, io.BytesIO(), 302, "Found", {}, "https://cdn.example/x.srt")
    assert new.full_url == "https://cdn.example/x.srt"


# --- errors, retries and the cache ------------------------------------------


def _http_error(code: int, body: bytes = b"{}") -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://api.opensubtitles.com/x", code, "error", {}, io.BytesIO(body))


def _replies(monkeypatch, *answers) -> list[urllib.request.Request]:
    """Fake the network: each call to _open takes the next answer, raising it
    when it is an exception. Returns the requests made."""
    seen: list[urllib.request.Request] = []
    queue = list(answers)

    def fake_open(req, timeout, api):
        seen.append(req)
        answer = queue.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return io.BytesIO(answer)

    monkeypatch.setattr(opensubtitles, "_open", fake_open)
    monkeypatch.setattr(opensubtitles.time, "sleep", lambda s: None)
    return seen


def _creds(tmp_path: Path, **extra) -> Path:
    config = tmp_path / "cfg"
    opensubtitles.save_creds(config, {"api_key": "k", **extra})
    return config


def _download_main(tmp_path: Path, capsys) -> tuple[str, str]:
    """Run the download command as the skill does. Returns the exit message
    and what was printed."""
    argv = ["--result", str(tmp_path / "result.json"), "download", "--config", str(tmp_path / "cfg")]
    argv += ["--file-id", "42", "--out", str(tmp_path / "out" / "x.srt"), "--cache", str(tmp_path / "cache")]
    with pytest.raises(SystemExit) as e:
        opensubtitles.main(argv)
    return str(e.value.code), capsys.readouterr().out


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        (_http_error(404), "failed with HTTP 404"),
        (urllib.error.URLError("no route to host"), "could not be downloaded (no route to host)"),
        (TimeoutError("timed out"), "could not be downloaded (timed out)"),
    ],
)
def test_a_failed_file_download_is_a_short_error_and_writes_nothing(tmp_path: Path, monkeypatch, capsys, failure, message):
    _creds(tmp_path)
    seen = _replies(monkeypatch, b'{"link": "https://dl.example/x.srt"}', failure)
    code, printed = _download_main(tmp_path, capsys)
    assert message in code and "so nothing was saved" in code
    assert len(seen) == 2 and printed == ""
    assert not (tmp_path / "out" / "x.srt").exists() and not (tmp_path / "cache").exists()
    assert not (tmp_path / "result.json").exists()


@pytest.mark.parametrize("reply", [b"{}", b'{"link": null}', b'{"link": 42}'])
def test_a_download_reply_without_a_link_is_a_short_error(tmp_path: Path, monkeypatch, capsys, reply):
    _creds(tmp_path)
    seen = _replies(monkeypatch, reply)
    code, printed = _download_main(tmp_path, capsys)
    assert "gave no download link for file 42" in code and printed == ""
    assert len(seen) == 1
    assert not (tmp_path / "out" / "x.srt").exists() and not (tmp_path / "cache").exists()
    assert not (tmp_path / "result.json").exists()


def test_a_reply_that_is_not_json_is_a_short_error(tmp_path: Path, monkeypatch, capsys):
    _creds(tmp_path)
    _replies(monkeypatch, b"<html>Service Unavailable</html>")
    code, printed = _download_main(tmp_path, capsys)
    assert "not a JSON object on POST" in code and printed == ""
    assert not (tmp_path / "out" / "x.srt").exists() and not (tmp_path / "result.json").exists()


@pytest.mark.parametrize(
    ("answers", "calls", "outcome"),
    [
        ((_http_error(429), _http_error(429), b'{"ok": 1}'), 3, {"ok": 1}),
        ((urllib.error.URLError("down"), b'{"ok": 1}'), 2, {"ok": 1}),
        ((TimeoutError("timed out"), TimeoutError("timed out"), b'{"ok": 1}'), 3, {"ok": 1}),
        ((_http_error(429), _http_error(429), _http_error(429, b"slow down")), 3, "OpenSubtitles 429 on GET"),
        ((urllib.error.URLError("down"),) * 3, 3, "OpenSubtitles unreachable: down"),
        ((_http_error(500, b"oops"),), 1, "OpenSubtitles 500 on GET"),
    ],
)
def test_requests_retry_429_and_network_errors_but_not_other_errors(monkeypatch, answers, calls, outcome):
    seen = _replies(monkeypatch, *answers)
    url = "https://api.opensubtitles.com/api/v1/infos/user"
    if isinstance(outcome, dict):
        assert opensubtitles._request("GET", url, {"api_key": "k"}) == outcome
    else:
        with pytest.raises(opensubtitles.ApiError, match=outcome):
            opensubtitles._request("GET", url, {"api_key": "k"})
    assert len(seen) == calls


def test_a_401_on_download_logs_in_again_once_and_retries_with_the_new_token(tmp_path: Path, monkeypatch):
    config = _creds(tmp_path, username="someone", password="pw", token="old", token_time=opensubtitles.time.time())
    seen = _replies(
        monkeypatch,
        _http_error(401, b'{"message": "invalid token"}'),
        b'{"token": "new", "base_url": "api.opensubtitles.com"}',
        b'{"link": "https://dl.example/x.srt", "remaining": 19}',
        b"1\n00:00:01,000 --> 00:00:02,000\nHi\n",
    )
    info = opensubtitles.download(config, 42, tmp_path / "x.srt", tmp_path / "cache")
    assert info["remaining"] == 19 and info["from_cache"] is False
    assert [r.full_url.rsplit("/", 1)[-1] for r in seen] == ["download", "login", "download", "x.srt"]
    assert seen[0].get_header("Authorization") == "Bearer old"
    assert seen[2].get_header("Authorization") == "Bearer new"
    assert json.loads((config / "credentials.json").read_text(encoding="utf-8"))["token"] == "new"


def test_a_second_401_after_logging_in_again_is_a_short_error(tmp_path: Path, monkeypatch):
    config = _creds(tmp_path, username="someone", password="pw", token="old", token_time=opensubtitles.time.time())
    seen = _replies(monkeypatch, _http_error(401), b'{"token": "new"}', _http_error(401, b"still no"))
    with pytest.raises(opensubtitles.ApiError, match="OpenSubtitles 401 on POST"):
        opensubtitles.download(config, 42, tmp_path / "x.srt", tmp_path / "cache")
    assert len(seen) == 3 and not (tmp_path / "x.srt").exists()


def test_the_cache_is_written_whole_or_not_at_all(tmp_path: Path, monkeypatch):
    config = _creds(tmp_path)
    body = b"1\n00:00:01,000 --> 00:00:02,000\nHi\n"
    _replies(monkeypatch, b'{"link": "https://dl.example/x.srt"}', body)

    def cut_off(src, dst):
        raise OSError("the run was stopped")

    monkeypatch.setattr(opensubtitles.os, "replace", cut_off)
    with pytest.raises(OSError):
        opensubtitles.download(config, 42, tmp_path / "x.srt", tmp_path / "cache")
    # Only the temporary file is there, so the next run downloads again.
    assert not (tmp_path / "cache" / "os_42.srt").exists()
    monkeypatch.undo()
    _replies(monkeypatch, b'{"link": "https://dl.example/x.srt"}', body)
    assert opensubtitles.download(config, 42, tmp_path / "x.srt", tmp_path / "cache")["from_cache"] is False
    assert (tmp_path / "cache" / "os_42.srt").read_bytes() == body
    assert opensubtitles.download(config, 42, tmp_path / "y.srt", tmp_path / "cache")["from_cache"] is True
    assert (tmp_path / "y.srt").read_bytes() == body


# --- credentials -------------------------------------------------------------


@pytest.mark.parametrize("content", [b"{not json", b"\xff\xfe\x00broken", b"[1, 2]", b'"text"'])
def test_a_broken_credentials_file_is_a_short_error(tmp_path: Path, monkeypatch, content):
    config = tmp_path / "cfg"
    config.mkdir()
    (config / "credentials.json").write_bytes(content)
    monkeypatch.setattr(opensubtitles, "_open", lambda *a, **k: pytest.fail("no request without credentials"))
    with pytest.raises(SystemExit) as e:
        opensubtitles.main(["--result", str(tmp_path / "r.json"), "status", "--config", str(config)])
    assert "is not a valid credentials file" in str(e.value.code) and "setup" in str(e.value.code)
    assert not (tmp_path / "r.json").exists()


def test_credentials_without_a_key_ask_for_setup(tmp_path: Path):
    config = tmp_path / "cfg"
    opensubtitles.save_creds(config, {"hf_token": "h"})
    with pytest.raises(opensubtitles.ApiError, match="no OpenSubtitles API key"):
        opensubtitles.load_creds(config)
    assert opensubtitles.load_creds(config, need_key=False) == {"hf_token": "h"}


def _setup(tmp_path: Path, monkeypatch, capsys, typed: list[str]) -> tuple[dict, str]:
    config = tmp_path / "cfg"

    def getpass(prompt=""):
        return typed.pop(0)

    monkeypatch.setattr(opensubtitles.getpass, "getpass", getpass)
    monkeypatch.setattr(opensubtitles, "status", lambda config: {"logged_in": "checked"})
    opensubtitles.setup(config)
    assert typed == []
    saved = json.loads((config / "credentials.json").read_text(encoding="utf-8"))
    return saved, capsys.readouterr().out


def test_setup_enter_keeps_the_stored_key_and_login(tmp_path: Path, monkeypatch, capsys):
    stored = {"api_key": "stored-key", "username": "someone", "password": "pw-1", "token": "t", "hf_token": "h"}
    opensubtitles.save_creds(tmp_path / "cfg", stored)
    saved, out = _setup(tmp_path, monkeypatch, capsys, ["", ""])
    assert saved == stored
    assert "stored-key" not in out and "pw-1" not in out and '"logged_in": "checked"' in out


def test_setup_with_a_new_username_clears_the_token_and_never_prints_the_password(tmp_path: Path, monkeypatch, capsys):
    stored = {"api_key": "stored-key", "username": "someone", "password": "old", "token": "t"}
    opensubtitles.save_creds(tmp_path / "cfg", stored)
    saved, out = _setup(tmp_path, monkeypatch, capsys, ["new-key-123", "another", "s3cret-pass"])
    assert saved == {"api_key": "new-key-123", "username": "another", "password": "s3cret-pass"}
    assert "s3cret-pass" not in out and "new-key-123" not in out


def test_setup_needs_a_key_the_first_time(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(opensubtitles.getpass, "getpass", lambda prompt="": "")
    with pytest.raises(SystemExit, match="An API key is required"):
        opensubtitles.setup(tmp_path / "cfg")
    assert not (tmp_path / "cfg" / "credentials.json").exists()
