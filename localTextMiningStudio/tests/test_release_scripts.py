import zipfile

from scripts.make_release_zip import APP_NAME, make_zip, write_release_readme


def test_release_readme_and_zip_are_created(tmp_path) -> None:
    dist_dir = tmp_path / "dist"
    release_dir = dist_dir / APP_NAME
    release_dir.mkdir(parents=True)
    (release_dir / f"{APP_NAME}.exe").write_text("fake exe", encoding="utf-8")
    (release_dir / "examples").mkdir()
    (release_dir / "examples" / ".gitkeep").write_text("", encoding="utf-8")

    readme = write_release_readme(release_dir)
    zip_path = make_zip(release_dir, dist_dir / f"{APP_NAME}_v0.1.0_windows.zip", dist_dir)

    readme_text = readme.read_text(encoding="utf-8")
    assert "双击 LocalTextMiningStudio.exe" in readme_text
    assert "user_data" in readme_text
    assert "API Key" in readme_text

    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())

    assert f"{APP_NAME}/README.txt" in names
    assert f"{APP_NAME}/{APP_NAME}.exe" in names
    assert f"{APP_NAME}/examples/.gitkeep" in names
