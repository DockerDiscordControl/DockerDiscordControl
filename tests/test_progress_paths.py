"""Tests for the shared progress path resolver."""

from __future__ import annotations

import pytest

from services.mech.progress_paths import (
    ProgressPaths,
    clear_progress_paths_cache,
    get_progress_paths,
)


@pytest.fixture(autouse=True)
def reset_cache():
    """Ensure the cached resolver state is cleared between tests."""

    clear_progress_paths_cache()
    yield
    clear_progress_paths_cache()


def test_member_count_defaults_to_progress_dir(tmp_path, monkeypatch):
    base_dir = tmp_path / "progress-data"
    monkeypatch.setenv("DDC_PROGRESS_DATA_DIR", str(base_dir))

    paths = get_progress_paths()

    assert paths.data_dir == base_dir
    assert paths.member_count_file == base_dir / "member_count.json"


def test_member_count_honours_env_override(tmp_path, monkeypatch):
    base_dir = tmp_path / "progress-data"
    override = tmp_path / "override" / "members.json"

    monkeypatch.setenv("DDC_PROGRESS_DATA_DIR", str(base_dir))
    monkeypatch.setenv("DDC_PROGRESS_MEMBER_COUNT_PATH", str(override))

    paths = get_progress_paths()

    assert paths.data_dir == base_dir
    assert paths.member_count_file == override
    assert override.parent.is_dir()


def test_legacy_member_count_path_is_respected(tmp_path, monkeypatch):
    base_dir = tmp_path / "progress"
    legacy = base_dir.parent / "member_count.json"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text("{}", encoding="utf-8")

    monkeypatch.setenv("DDC_PROGRESS_DATA_DIR", str(base_dir))

    paths = ProgressPaths.from_base_dir(base_dir, create_missing=False)

    assert paths.member_count_file == legacy
