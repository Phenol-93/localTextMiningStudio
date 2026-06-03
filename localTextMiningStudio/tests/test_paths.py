from pathlib import Path

from app.utils import paths


def test_runtime_directories_are_created_under_app_root(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(paths, "get_app_root", lambda: tmp_path)

    paths.ensure_app_directories()

    assert paths.get_user_data_dir() == tmp_path / "user_data"
    assert paths.get_projects_dir() == tmp_path / "user_data" / "projects"
    assert paths.get_logs_dir() == tmp_path / "logs"
    assert (tmp_path / "exports").is_dir()
    assert (tmp_path / "resources").is_dir()


def test_frozen_app_root_uses_executable_directory(monkeypatch, tmp_path) -> None:
    executable = tmp_path / "local-text-mining-studio.exe"

    monkeypatch.setattr(paths.sys, "frozen", True, raising=False)
    monkeypatch.setattr(paths.sys, "executable", str(executable))

    assert paths.get_app_root() == Path(executable).parent
