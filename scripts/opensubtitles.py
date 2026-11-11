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
script reads that file, and it never prints any of it. Searching is free;
each download uses one from the daily quota (5 with a key alone, 20 when
logged in with a free account), so downloads are cached by file id.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.opensubtitles.com/api/v1"
USER_AGENT = "TurkishSubtitles v0.1"
TOKEN_MAX_AGE = 20 * 3600  # tokens last 24 h; renew a bit early


class ApiError(SystemExit):
    pass


# --- credentials -----------------------------------------------------------


def _cred_path(config: Path) -> Path:
    return config / "credentials.json"


def load_creds(config: Path) -> dict:
    p = _cred_path(config)
    if not p.exists():
        raise ApiError(
            "No OpenSubtitles credentials. Ask the user to run this in their own terminal:\n"
            f'  uv run "{Path(__file__).resolve()}" setup --config "{config}"'
        )
    return json.loads(p.read_text(encoding="utf-8"))


def save_creds(config: Path, creds: dict) -> None:
    config.mkdir(parents=True, exist_ok=True)
    p = _cred_path(config)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(creds, indent=1), encoding="utf-8")
    if os.name != "nt":
        os.chmod(tmp, 0o600)
    tmp.replace(p)


# --- http ------------------------------------------------------------------


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
    for attempt in range(3):
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            text = e.read().decode("utf-8", errors="replace")[:300]
            if e.code == 429 and attempt < 2:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise ApiError(f"OpenSubtitles {e.code} on {method} {url.split('?')[0]}: {text}") from None
        except urllib.error.URLError as e:
            if attempt < 2:
                time.sleep(2)
                continue
            raise ApiError(f"OpenSubtitles unreachable: {e.reason}") from None
    raise ApiError("OpenSubtitles: too many retries")


def _base(creds: dict) -> str:
    host = creds.get("base_url")
    return f"https://{host}/api/v1" if host else API


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
    creds = load_creds(config) if _cred_path(config).exists() else {}
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
    req = urllib.request.Request(r["link"], headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read()
    cache.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(raw)
    out.write_bytes(raw)
    return {"file": str(out), "from_cache": False, "remaining": r.get("remaining"), "reset_time": r.get("reset_time")}


def main(argv: list[str] | None = None) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("setup", "status", "search", "download", "hash"):
        s = sub.add_parser(name)
        if name != "hash":
            s.add_argument("--config", type=Path, required=True)
        if name in ("search", "hash"):
            s.add_argument("--video", type=Path, required=name == "hash")
        if name == "search":
            s.add_argument("--query")
            s.add_argument("--imdb")
            s.add_argument("--year", type=int)
            s.add_argument("--languages", required=True)
        if name == "download":
            s.add_argument("--file-id", type=int, required=True)
            s.add_argument("--out", type=Path, required=True)
            s.add_argument("--cache", type=Path, required=True)
    a = p.parse_args(argv)
    if a.cmd == "setup":
        setup(a.config)
        return
    if a.cmd == "status":
        result = status(a.config)
    elif a.cmd == "search":
        if not (a.video or a.query or a.imdb):
            raise SystemExit("give --video, --query or --imdb")
        result = search(a.config, a.video, a.query, a.imdb, a.year, a.languages)
    elif a.cmd == "hash":
        result = moviehash(a.video)
    else:
        result = download(a.config, a.file_id, a.out, a.cache)
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
