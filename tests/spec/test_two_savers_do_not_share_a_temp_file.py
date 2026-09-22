# -*- coding: utf-8 -*-
"""Two processes saving container info do not fight over one temp file.

THE FINDING (review D7, pass 2, section 18 F6): `save_container_info` and
`delete_container_info` each wrote through a hand-rolled temp-then-rename
with a FIXED name per container, `container_file.with_suffix('.tmp')`,
instead of the shared helper in utils/atomic_io that the rest of the code
base uses.

Container info is written from BOTH processes: the web panel through
`app/utils/container_info_web_handler.py` and the bot through the Edit Info
modal in `cogs/enhanced_info_modal_simple.py`. Two savers for the same
container therefore aim at the same temp path - one renames it away while
the other is still holding it, and that other one's rename hits a file that
is no longer there. This is the shape review C29 had to fix for the game
query verdicts, where the answer was a temp name carrying the process id.

`atomic_write_json` gives every write its own `mkstemp` name, and fsyncs,
and keeps the target's permissions - none of which the hand-rolled version
did.
"""

import json
import threading

import pytest

from services.infrastructure.container_info_service import (
    ContainerInfo, ContainerInfoService)


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    containers = tmp_path / "containers"
    containers.mkdir(parents=True)
    (containers / "web.json").write_text(
        json.dumps({"docker_name": "web", "info": {}}), encoding="utf-8")
    return ContainerInfoService()


@pytest.fixture
def slow_rename(monkeypatch):
    """Widen the window between writing the temp file and renaming it.

    Both the hand-rolled version (Path.rename) and the shared helper
    (os.replace) pass through here, so the same delay applies either way.
    """
    import os
    import time
    from pathlib import Path

    real_rename = Path.rename
    real_replace = os.replace

    def _slow_rename(self, target):
        time.sleep(0.002)
        return real_rename(self, target)

    def _slow_replace(source, target):
        time.sleep(0.002)
        return real_replace(source, target)

    monkeypatch.setattr(Path, "rename", _slow_rename)
    monkeypatch.setattr(os, "replace", _slow_replace)


def _info(text):
    return ContainerInfo(enabled=True, show_ip=False, custom_ip="", custom_port="",
                         custom_text=text, protected_enabled=False,
                         protected_content="", protected_password="")


def test_two_savers_do_not_take_each_others_file(service, slow_rename):
    """Two writers, same container, at the same time - as the panel and the
    bot really do it."""
    failures = []

    def _save(tag):
        for number in range(15):
            try:
                result = service.save_container_info("web", _info(f"{tag}-{number}"))
                if not result.success:
                    failures.append(result.error)
            except Exception as e:      # noqa: BLE001 - whatever it is, it is a failure
                failures.append(f"{type(e).__name__}: {e}")

    threads = [threading.Thread(target=_save, args=(tag,)) for tag in ("panel", "bot")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert failures == [], f"{len(failures)} of 30 saves failed: {failures[:3]}"


def test_the_file_is_still_readable_afterwards(service, slow_rename):
    """Whatever the order, the container file must never be left torn."""
    def _save(tag):
        for number in range(15):
            try:
                service.save_container_info("web", _info(f"{tag}-{number}"))
            except Exception:           # noqa: BLE001 - the other test reports these
                pass

    threads = [threading.Thread(target=_save, args=(tag,)) for tag in ("panel", "bot")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    stored = json.loads((service.containers_dir / "web.json").read_text(encoding="utf-8"))
    assert stored["docker_name"] == "web"


def test_one_save_still_works(service):
    """Counter-check: the everyday case must be untouched."""
    result = service.save_container_info("web", _info("hello"))

    assert result.success
    stored = json.loads((service.containers_dir / "web.json").read_text(encoding="utf-8"))
    assert stored["info"]["custom_text"] == "hello"


def test_no_debris_is_left_behind(service):
    """Counter-check: a finished save leaves no temp file lying about."""
    service.save_container_info("web", _info("hello"))

    leftovers = [p.name for p in service.containers_dir.iterdir()
                 if "tmp" in p.name.lower()]
    assert leftovers == [], leftovers


def test_a_save_and_a_reset_do_not_take_each_others_file(service, slow_rename):
    """`delete_container_info` writes the same file through the same route.

    The panel resets a container's info while the bot saves it - two writers,
    one target, and the reset path had its own copy of the hand-rolled write
    (found by mutation M2 of review D7).
    """
    failures = []

    def _both(tag):
        # Each thread alternates, so two of them can be inside the reset path
        # at the same time - one writer alone never collides with itself.
        for number in range(15):
            try:
                if number % 2:
                    result = service.delete_container_info("web")
                else:
                    result = service.save_container_info("web", _info(f"{tag}-{number}"))
                if not result.success:
                    failures.append(result.error)
            except Exception as e:      # noqa: BLE001
                failures.append(f"{type(e).__name__}: {e}")

    threads = [threading.Thread(target=_both, args=(tag,)) for tag in ("panel", "bot")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert failures == [], f"{len(failures)} of 30 writes failed: {failures[:3]}"
