# -*- coding: utf-8 -*-
"""A container name refused by the path check is one failure, not the whole batch.

THE FINDING (stage 4 review before v3.1.0, section 13 pass 3 F2):
save_container_config and delete_container_config are documented to answer
False, but for a name the path check refuses ("bad name", "../x") they
raised ValueError. The web save's loop does not catch that, so every
container after the bad one went unsaved and the operator got a generic
data error.

THE CONTRACT: False for that name, and the rest of the batch is saved.

HOW THIS TEST CAN FAIL: the ValueError escapes again.

COUNTER-CHECK (2026-09-30): red before the change.
"""

import importlib

from app.utils.container_info_web_handler import save_container_configs_from_web


def test_the_bad_name_fails_alone(monkeypatch, tmp_path):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    save_module = importlib.import_module("services.config.container_config_save_service")
    monkeypatch.setattr(save_module, "_container_config_save_service_instance", None)
    service = save_module.get_container_config_save_service()

    assert service.save_container_config("bad name", {}) is False
    assert service.delete_container_config("../x") is False

    results = save_container_configs_from_web([{"docker_name": "bad name"}, {"docker_name": "good"}])
    assert results.get("bad name") is False
    assert (tmp_path / "containers" / "good.json").exists(), "the container after the bad name was not saved"
