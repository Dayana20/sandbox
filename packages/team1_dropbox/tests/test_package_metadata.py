"""Build metadata tests that keep the wheel standalone and focused."""

import tomllib
from pathlib import Path


def test_package_metadata_and_dependencies_are_focused() -> None:
    package_root = Path(__file__).parents[1]
    metadata = tomllib.loads((package_root / "pyproject.toml").read_text(encoding="utf-8"))
    project = metadata["project"]

    assert project["name"] == "team1-dropbox-storage"
    assert project["version"] == "0.1.0"
    assert project["requires-python"] == ">=3.12"
    assert any("@0.3.1" in dependency for dependency in project["dependencies"])
    assert any(dependency.startswith("dropbox==") for dependency in project["dependencies"])
    assert all("fastapi" not in dependency.lower() for dependency in project["dependencies"])
    assert all("redis" not in dependency.lower() for dependency in project["dependencies"])


def test_only_distinct_team1_namespace_is_packaged() -> None:
    package_root = Path(__file__).parents[1]
    source_packages = {
        entry.name
        for entry in (package_root / "src").iterdir()
        if entry.is_dir() and not entry.name.endswith(".egg-info")
    }

    assert source_packages == {"team1_dropbox"}
    assert (package_root / "src" / "team1_dropbox" / "py.typed").is_file()
