# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""OpenSubtitles REST API: log in, search and download source subtitles.

    uv run opensubtitles.py setup    --config CONFIG_DIR     (run by the user, in a terminal)
    uv run opensubtitles.py status   --config CONFIG_DIR
    uv run opensubtitles.py search   --config CONFIG_DIR [--video V] [--query NAME] [--imdb ID] [--year Y] --languages en,fr
    uv run opensubtitles.py download --config CONFIG_DIR --file-id N --out FILE --cache DIR

The key, login and token live in CONFIG_DIR/credentials.json. Only this
script and speakers.py (which keeps its Hugging Face token there) read that
file, and neither ever prints any of it. Searching is free;
each download uses one from the daily quota (5 with a key alone, 20 when
logged in with a free account), so downloads are cached by file id.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import result  # noqa: E402
import settings  # noqa: E402

API = "https://api.opensubtitles.com/api/v1"
USER_AGENT = "SubtitleIt v0.7.3"
TOKEN_MAX_AGE = 20 * 3600  # tokens last 24 h; renew a bit early


# A subtitle file is a few hundred KB at most; anything far bigger is not one.
MAX_SUBTITLE_BYTES = 5_000_000


class ApiError(SystemExit):
    pass


# --- credentials -----------------------------------------------------------


def _cred_path(config: Path) -> Path:
    return config / "credentials.json"


def _setup_hint(config: Path) -> str:
    return f'  uv run "{Path(__file__).resolve()}" setup --config "{config}"'


def load_creds(config: Path, need_key: bool = True) -> dict:
    p = _cred_path(config)
    if not p.exists():
        raise ApiError("No OpenSubtitles credentials. Ask the user to run this in their own terminal:\n" + _setup_hint(config))
    # The message names the file and never shows what is in it.
    try:
        creds = json.loads(p.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        creds = None
    if not isinstance(creds, dict):
        raise ApiError(
            f"{p} is not a valid credentials file. Ask the user to delete it and run this in their own terminal:\n"
            + _setup_hint(config)
        )
    if need_key and not creds.get("api_key"):
        raise ApiError(
            f"{p} has no OpenSubtitles API key. Ask the user to run this in their own terminal:\n" + _setup_hint(config)
        )
    return creds


def save_creds(config: Path, creds: dict) -> None:
    config.mkdir(parents=True, exist_ok=True)
    p = _cred_path(config)
    result.write_private(p, json.dumps(creds, indent=1))


# --- http ------------------------------------------------------------------


def _ours(host: str | None) -> bool:
    host = (host or "").lower()
    return host == "opensubtitles.com" or host.endswith(".opensubtitles.com")


class _ApiRedirect(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only to https on opensubtitles.com. API requests
    carry the key and the login token, and urllib would resend both to any
    host a redirect names."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        u = urllib.parse.urlsplit(newurl)
        if u.scheme != "https" or not _ours(u.hostname):
            raise ApiError(
                f"OpenSubtitles redirected {req.get_method()} {req.full_url.split('?')[0]} to "
                f"{u.scheme}://{u.hostname}, which is not opensubtitles.com over https. "
                "The request was stopped, so the key and login token were not sent there."
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _HttpsRedirect(urllib.request.HTTPRedirectHandler):
    """Follow a redirect of the subtitle file download only over https."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme != "https":
            raise ApiError(f"The subtitle download redirected to a link that is not https: {newurl[:80]}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open(req: urllib.request.Request, timeout: int, api: bool):
    """Open a request; `api` requests follow redirects only within opensubtitles.com."""
    return urllib.request.build_opener(_ApiRedirect if api else _HttpsRedirect).open(req, timeout=timeout)


def _request(method: str, url: str, creds: dict, body: dict | None = None, auth: bool = False) -> dict:
    headers = {
        "Api-Key": creds["api_key"],
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if auth and creds.get("token"):
        headers["Authorization"] = f"Bearer {creds['token']}"
    where = f"{method} {url.split('?')[0]}"
    for attempt in range(3):
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with _open(req, 30, api=True) as r:
                raw = r.read()
        except urllib.error.HTTPError as e:
            text = e.read().decode("utf-8", errors="replace")[:300]
            if e.code == 429 and attempt < 2:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise ApiError(f"OpenSubtitles {e.code} on {where}: {text}") from None
        except OSError as e:  # no connection, a refused one or a timeout
            if attempt < 2:
                time.sleep(2)
                continue
            raise ApiError(f"OpenSubtitles unreachable: {getattr(e, 'reason', None) or e}") from None
        try:
            reply = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            reply = None
        if not isinstance(reply, dict):
            raise ApiError(f"OpenSubtitles sent a reply that is not a JSON object on {where}: {raw[:80]!r}")
        return reply
    raise ApiError("OpenSubtitles: too many retries")


def _base(creds: dict) -> str:
    """The API root on the host the login named, always over https. Only
    opensubtitles.com or one of its subdomains is used, since the key and
    login token go to that host; any other falls back to the default API."""
    host = (creds.get("base_url") or "").lower()
    plain = re.fullmatch(r"[a-z0-9.-]+", host)
    return f"https://{host}/api/v1" if plain and _ours(host) else API


def _https(url: str) -> str:
    if urllib.parse.urlsplit(url).scheme != "https":
        raise ApiError(f"OpenSubtitles sent a download link that is not https: {url[:80]}")
    return url


def login(config: Path, creds: dict, force: bool = False) -> dict:
    """Log in when there is a username and the token is missing or old."""
    if not creds.get("username"):
        return creds
    if not force and creds.get("token") and time.time() - creds.get("token_time", 0) < TOKEN_MAX_AGE:
        return creds
    r = _request("POST", f"{API}/login", creds, {"username": creds["username"], "password": creds["password"]})
    creds.update(token=r["token"], token_time=time.time(), base_url=r.get("base_url") or "api.opensubtitles.com")
    save_creds(config, creds)
    return creds


# --- movie hash ------------------------------------------------------------


def moviehash(path: Path) -> str:
    """OpenSubtitles hash: file size plus the 64-bit sums of the first and
    last 64 KiB."""
    size = path.stat().st_size
    if size < 65536 * 2:
        raise ValueError("file too small for a movie hash")
    h = size
    with open(path, "rb") as f:
        for pos in (0, size - 65536):
            f.seek(pos)
            for (x,) in struct.iter_unpack("<Q", f.read(65536)):
                h = (h + x) & 0xFFFFFFFFFFFFFFFF
    return f"{h:016x}"


# --- commands --------------------------------------------------------------


def setup(config: Path) -> None:
    print("OpenSubtitles setup. Nothing you type is shown or printed back.")
    print("Create a free key at https://www.opensubtitles.com/consumers and a free account to get 20 downloads a day.")
    creds = load_creds(config, need_key=False) if _cred_path(config).exists() else {}
    key = getpass.getpass("API key (Enter to keep the current one): ").strip()
    if key:
        creds["api_key"] = key
    if not creds.get("api_key"):
        raise SystemExit("An API key is required.")
    user = getpass.getpass("OpenSubtitles username (Enter to skip login): ").strip()
    if user:
        creds["username"] = user
        creds["password"] = getpass.getpass("Password: ")
        creds.pop("token", None)
    save_creds(config, creds)
    print(json.dumps(status(config), indent=1))


def status(config: Path) -> dict:
    creds = login(config, load_creds(config))
    if not creds.get("token"):
        return {"logged_in": False, "daily_downloads": 5, "note": "key only; add a free account login for 20 a day"}
    r = _request("GET", f"{_base(creds)}/infos/user", creds, auth=True)["data"]
    return {
        "logged_in": True,
        "level": r.get("level"),
        "allowed_downloads": r.get("allowed_downloads"),
        "remaining_downloads": r.get("remaining_downloads"),
        "warning": None
        if (r.get("allowed_downloads") or 0) > 5
        else "login not recognised: limit is 5, check username and password",
    }


def search(config: Path, video: Path | None, query: str | None, imdb: str | None, year: int | None, languages: str) -> list[dict]:
    creds = login(config, load_creds(config))
    params: dict[str, str] = {"languages": ",".join(sorted(x.strip().lower() for x in languages.split(",")))}
    if video:
        params["moviehash"] = moviehash(video)
    if imdb:
        params["imdb_id"] = str(int(imdb.lower().lstrip("t")))
    elif query:
        params["query"] = query.lower()
    if year and not imdb:
        params["year"] = str(year)
    # The API wants parameters sorted and lower case, or it redirects.
    url = f"{_base(creds)}/subtitles?" + urllib.parse.urlencode(sorted(params.items()))
    r = _request("GET", url, creds, auth=True)
    out = []
    for item in r.get("data", []):
        a = item["attributes"]
        fd = a.get("feature_details") or {}
        files = a.get("files") or []
        out.append(
            {
                "file_id": files[0]["file_id"] if files else None,
                "parts": len(files),
                "language": a.get("language"),
                "release": a.get("release"),
                "moviehash_match": bool(a.get("moviehash_match")),
                "hearing_impaired": bool(a.get("hearing_impaired")),
                "machine_or_ai": bool(a.get("machine_translated")) or bool(a.get("ai_translated")),
                "foreign_parts_only": bool(a.get("foreign_parts_only")),
                "from_trusted": bool(a.get("from_trusted")),
                "downloads": a.get("download_count"),
                "fps": a.get("fps"),
                "title": fd.get("title") or fd.get("movie_name"),
                "year": fd.get("year"),
                "imdb_id": fd.get("imdb_id"),
            }
        )
    usable = [x for x in out if x["file_id"] and x["parts"] == 1 and not x["machine_or_ai"] and not x["foreign_parts_only"]]
    usable.sort(key=lambda x: (not x["moviehash_match"], not x["from_trusted"], -(x["downloads"] or 0)))
    return usable


def download(config: Path, file_id: int, out: Path, cache: Path) -> dict:
    cached = cache / f"os_{file_id}.srt"
    out.parent.mkdir(parents=True, exist_ok=True)
    if cached.exists():
        out.write_bytes(cached.read_bytes())
        return {"file": str(out), "from_cache": True}
    creds = login(config, load_creds(config))
    try:
        r = _request("POST", f"{_base(creds)}/download", creds, {"file_id": file_id}, auth=True)
    except ApiError as e:
        if " 401 " in str(e) and creds.get("username"):
            creds = login(config, creds, force=True)
            r = _request("POST", f"{_base(creds)}/download", creds, {"file_id": file_id}, auth=True)
        else:
            raise
    if not isinstance(r.get("link"), str):
        raise ApiError(f"OpenSubtitles gave no download link for file {file_id}")
    # The file sits on whatever https host the link names, so it gets no key or token.
    req = urllib.request.Request(_https(r["link"]), headers={"User-Agent": USER_AGENT})
    try:
        with _open(req, 60, api=False) as resp:
            raw = resp.read(MAX_SUBTITLE_BYTES + 1)
    except urllib.error.HTTPError as e:
        raise ApiError(f"the subtitle file download failed with HTTP {e.code}, so nothing was saved") from None
    except OSError as e:  # no connection, a refused one or a timeout
        raise ApiError(
            f"the subtitle file could not be downloaded ({getattr(e, 'reason', None) or e}), so nothing was saved"
        ) from None
    if len(raw) > MAX_SUBTITLE_BYTES:
        raise ApiError(f"the subtitle file is larger than {MAX_SUBTITLE_BYTES // 1_000_000} MB, so it was not saved")
    # The cache is trusted from then on, so a run cut off while writing it
    # must leave either the whole file or none.
    cache.mkdir(parents=True, exist_ok=True)
    tmp = cached.with_name(cached.name + ".tmp")
    tmp.write_bytes(raw)
    os.replace(tmp, cached)
    out.write_bytes(raw)
    return {"file": str(out), "from_cache": False, "remaining": r.get("remaining"), "reset_time": r.get("reset_time")}


def main(argv: list[str] | None = None) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("setup", "status", "search", "download", "hash"):
        s = sub.add_parser(name)
        if name != "hash":
            s.add_argument("--config", type=result.path, required=True)
        if name in ("search", "hash"):
            s.add_argument("--video", type=result.path, required=name == "hash")
        if name == "search":
            s.add_argument("--query")
            s.add_argument("--imdb")
            s.add_argument("--year", type=int)
            s.add_argument("--languages", required=True)
        if name == "download":
            s.add_argument("--file-id", type=int, required=True)
            s.add_argument("--out", type=result.path, required=True)
            s.add_argument("--cache", type=result.path, required=True)
    result.add_argument(p)
    a = result.parse(p, argv)
    if a.cmd != "hash":
        a.config = settings.ensure_for(a.config)
    if a.cmd == "setup":
        setup(a.config)
        return
    if a.cmd == "status":
        out = status(a.config)
    elif a.cmd == "search":
        if not (a.video or a.query or a.imdb):
            raise SystemExit("give --video, --query or --imdb")
        out = search(a.config, a.video, a.query, a.imdb, a.year, a.languages)
    elif a.cmd == "hash":
        out = moviehash(a.video)
    else:
        out = download(a.config, a.file_id, a.out, a.cache)
    result.emit(out, a.result)


if __name__ == "__main__":
    main()
