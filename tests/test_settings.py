"""The settings folder: ~/.config/subtitle-it, with the folder from before the
rename moved into place once. Every test uses a temporary home folder."""

import json
import os
from pathlib import Path

import pytest

import settings


@pytest.fixture
def home(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert Path.home() == tmp_path and Path("~").expanduser() == tmp_path
    return tmp_path


def old_folder(home: Path) -> Path:
    old = home / ".config" / "turkish-subtitles"
    (old / "backups").mkdir(parents=True)
    (old / "preferences.md").write_text("# prefs\n", encoding="utf-8")
    (old / "credentials.json").write_text("{}", encoding="utf-8")
    (old / "backups" / "Film.tr.srt").write_text("1\n", encoding="utf-8")
    return old


def test_the_old_folder_moves_once_with_everything_in_it(home: Path):
    old = old_folder(home)
    out = settings.ensure(home)
    new = home / ".config" / "subtitle-it"
    assert out == {"folder": str(new), "moved_from": str(old)}
    assert not old.exists()
    assert sorted(p.relative_to(new).as_posix() for p in new.rglob("*")) == [
        "backups",
        "backups/Film.tr.srt",
        "credentials.json",
        "preferences.md",
    ]
    assert settings.ensure(home) == {"folder": str(new), "moved_from": None}


def test_the_move_never_opens_the_credentials_file(home: Path, monkeypatch):
    old_folder(home)
    opened = []
    real_open = open

    def watch(file, *args, **kwargs):
        opened.append(str(file))
        return real_open(file, *args, **kwargs)

    def watch_os(file, *args, **kwargs):
        opened.append(str(file))
        return real_os_open(file, *args, **kwargs)

    real_os_open = os.open
    monkeypatch.setattr("builtins.open", watch)
    monkeypatch.setattr(os, "open", watch_os)
    monkeypatch.setattr(Path, "read_bytes", lambda self: opened.append(str(self)) or b"")
    monkeypatch.setattr(Path, "read_text", lambda self, *a, **k: opened.append(str(self)) or "")
    settings.ensure(home)
    assert not [f for f in opened if f.endswith("credentials.json")]


def test_an_existing_new_folder_wins_and_the_old_one_stays(home: Path):
    old = old_folder(home)
    new = home / ".config" / "subtitle-it"
    new.mkdir()
    assert settings.ensure(home) == {"folder": str(new), "moved_from": None}
    assert (old / "credentials.json").exists()
    assert list(new.iterdir()) == []


def test_nothing_to_move_gives_the_new_folder_without_making_it(home: Path):
    out = settings.ensure(home)
    assert out == {"folder": str(home / ".config" / "subtitle-it"), "moved_from": None}
    assert not (home / ".config").exists()


def test_a_failed_move_keeps_using_the_old_folder(home: Path, monkeypatch):
    old = old_folder(home)

    def refuse(self, target):
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(Path, "rename", refuse)
    out = settings.ensure(home)
    assert out["folder"] == str(old)
    assert out["moved_from"] is None
    assert "Access is denied" in out["error"]


def test_folder_command_saves_its_result(home: Path, capsys):
    old_folder(home)
    res = home / "results" / "settings-folder.json"
    settings.main(["--result", str(res), "folder"])
    saved = json.loads(res.read_text(encoding="utf-8"))
    assert saved["folder"] == str(home / ".config" / "subtitle-it")
    assert saved["moved_from"] == str(home / ".config" / "turkish-subtitles")
    assert json.loads(capsys.readouterr().out) == saved


def test_setup_commands_move_the_old_folder_only_for_the_default_path(home: Path):
    old = old_folder(home)
    settings.ensure_for(home / "elsewhere")
    assert old.exists()
    settings.ensure_for(Path("~/.config/subtitle-it"))
    assert not old.exists()
    assert (home / ".config" / "subtitle-it" / "preferences.md").exists()


def test_a_failed_move_before_setup_hands_back_the_old_folder(home: Path, monkeypatch, capsys):
    old = old_folder(home)
    monkeypatch.setattr(Path, "rename", lambda self, target: (_ for _ in ()).throw(PermissionError(13, "Access is denied")))
    assert settings.ensure_for(Path("~/.config/subtitle-it")) == old
    assert "Access is denied" in capsys.readouterr().err
    assert not (home / ".config" / "subtitle-it").exists()


def test_opensubtitles_moves_the_old_folder_before_using_it(home: Path, monkeypatch):
    import opensubtitles

    old = old_folder(home)
    seen = []
    monkeypatch.setattr(opensubtitles, "status", lambda config: seen.append(config) or {})
    opensubtitles.main(["status", "--config", "~/.config/subtitle-it"])
    assert seen == [home / ".config" / "subtitle-it"]
    assert not old.exists()


def test_opensubtitles_hash_leaves_the_settings_alone(home: Path, monkeypatch):
    import opensubtitles

    old = old_folder(home)
    monkeypatch.setattr(opensubtitles, "moviehash", lambda video: {})
    opensubtitles.main(["hash", "--video", str(home / "v.mkv")])
    assert old.exists()


def test_speakers_setup_writes_into_the_folder_it_is_handed(home: Path, monkeypatch):
    import speakers

    old = old_folder(home)
    monkeypatch.setattr(Path, "rename", lambda self, target: (_ for _ in ()).throw(PermissionError(13, "Access is denied")))
    seen = []
    monkeypatch.setattr(speakers, "setup", seen.append)
    speakers.main(["setup", "--config", "~/.config/subtitle-it"])
    assert seen == [old]
    assert speakers.DEFAULT_CONFIG.parts[-2:] == (".config", "subtitle-it")
