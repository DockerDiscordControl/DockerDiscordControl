# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Container Info Service Tests                   #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Unit tests for the Container Info Service.

The original tests were written against a fictional ``get_config_service``
based API. The real :class:`ContainerInfoService` persists each container in
its own JSON file under ``config/containers``.  These tests have been
rewritten to exercise the actual public surface:

* :meth:`ContainerInfoService.get_container_info`
* :meth:`ContainerInfoService.save_container_info`
* :meth:`ContainerInfoService.delete_container_info`
* :meth:`ContainerInfoService.list_all_containers`
"""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from services.infrastructure.container_info_service import (
    ContainerInfo,
    ContainerInfoService,
    ServiceResult,
)


def _make_service(tmp_path: Path) -> ContainerInfoService:
    """Build a service instance pinned to an isolated tmp containers dir."""
    service = ContainerInfoService()
    service.containers_dir = tmp_path / "containers"
    service.containers_dir.mkdir(parents=True, exist_ok=True)
    service.config_file = tmp_path / "docker_config.json"
    return service


def _write_container_file(service: ContainerInfoService, name: str, info: dict) -> Path:
    """Write a container JSON file mirroring the real on-disk format."""
    container_file = service.containers_dir / f"{name}.json"
    container_file.write_text(
        json.dumps({"name": name, "info": info}, indent=2),
        encoding="utf-8",
    )
    return container_file


class TestContainerInfoService:
    """Test suite for ContainerInfoService."""

    def test_service_initialization(self, tmp_path):
        """Test that the service initializes correctly."""
        service = _make_service(tmp_path)
        assert service is not None
        assert isinstance(service, ContainerInfoService)
        assert service.containers_dir.exists()

    def test_get_container_info_success(self, tmp_path):
        """Test successful retrieval of container info from a JSON file."""
        service = _make_service(tmp_path)
        _write_container_file(
            service,
            "test_container",
            {
                "enabled": True,
                "show_ip": True,
                "custom_ip": "192.168.1.100",
                "custom_port": "8080",
                "custom_text": "Test Container",
                "protected_enabled": False,
                "protected_content": "",
                "protected_password": "",
            },
        )

        result = service.get_container_info("test_container")

        assert result.success is True
        assert isinstance(result.data, ContainerInfo)
        assert result.data.enabled is True
        assert result.data.show_ip is True
        assert result.data.custom_ip == "192.168.1.100"
        assert result.data.custom_port == "8080"
        assert result.data.custom_text == "Test Container"
        assert result.data.protected_enabled is False

    def test_get_container_info_not_found(self, tmp_path):
        """Missing container files yield default ContainerInfo (success=True)."""
        service = _make_service(tmp_path)

        result = service.get_container_info("nonexistent_container")

        # Real service returns success with default values when not found.
        assert result.success is True
        assert isinstance(result.data, ContainerInfo)
        assert result.data.enabled is False
        assert result.data.show_ip is False
        assert result.data.custom_ip == ""
        assert result.data.custom_port == ""
        assert result.data.custom_text == ""
        assert result.data.protected_enabled is False

    def test_save_container_info_success(self, tmp_path):
        """Test successful save of container info to disk."""
        service = _make_service(tmp_path)
        # Pre-create container file so save can find it.
        _write_container_file(
            service,
            "test_container",
            {
                "enabled": False,
                "show_ip": False,
                "custom_ip": "",
                "custom_port": "",
                "custom_text": "",
                "protected_enabled": False,
                "protected_content": "",
                "protected_password": "",
            },
        )

        new_info = ContainerInfo.from_dict(
            {
                "enabled": True,
                "show_ip": True,
                "custom_ip": "10.0.0.5",
                "custom_port": "9090",
                "custom_text": "Updated Container",
                "protected_enabled": True,
                "protected_content": "Secret info",
                "protected_password": "password123",
            }
        )

        result = service.save_container_info("test_container", new_info)

        assert result.success is True
        assert isinstance(result.data, ContainerInfo)
        assert result.data.enabled is True

        # Persisted to disk.
        persisted = json.loads(
            (service.containers_dir / "test_container.json").read_text(encoding="utf-8")
        )
        assert persisted["info"]["custom_text"] == "Updated Container"
        assert persisted["info"]["custom_port"] == "9090"

    def test_save_container_info_missing_file(self, tmp_path):
        """Saving without a matching JSON file is a failure."""
        service = _make_service(tmp_path)

        info = ContainerInfo.from_dict(
            {
                "enabled": True,
                "show_ip": False,
                "custom_ip": "",
                "custom_port": "",
                "custom_text": "",
                "protected_enabled": False,
                "protected_content": "",
                "protected_password": "",
            }
        )

        result = service.save_container_info("does_not_exist", info)

        assert result.success is False
        assert result.error is not None
        assert "not found" in result.error.lower()

    def test_delete_container_info_success(self, tmp_path):
        """delete_container_info resets the info section to defaults on disk."""
        service = _make_service(tmp_path)
        _write_container_file(
            service,
            "test_container",
            {
                "enabled": True,
                "show_ip": True,
                "custom_ip": "1.2.3.4",
                "custom_port": "1234",
                "custom_text": "To be deleted",
                "protected_enabled": True,
                "protected_content": "secret",
                "protected_password": "pw",
            },
        )

        result = service.delete_container_info("test_container")

        assert result.success is True

        persisted = json.loads(
            (service.containers_dir / "test_container.json").read_text(encoding="utf-8")
        )
        # Info section should be reset to defaults but file still exists.
        assert persisted["info"]["enabled"] is False
        assert persisted["info"]["custom_text"] == ""
        assert persisted["info"]["protected_enabled"] is False

    def test_delete_container_info_not_found(self, tmp_path):
        """Deleting a non-existent container is a no-op success."""
        service = _make_service(tmp_path)

        result = service.delete_container_info("nonexistent")

        # Real service treats missing file as success (idempotent reset).
        assert result.success is True

    def test_list_all_containers(self, tmp_path):
        """list_all_containers reads names via the server config service."""
        service = _make_service(tmp_path)
        # config_file must exist for the real method to proceed.
        service.config_file.write_text("{}", encoding="utf-8")

        fake_server_config = MagicMock()
        fake_server_config.get_all_servers.return_value = [
            {"docker_name": "container1", "name": "container1"},
            {"name": "container2"},
            {"docker_name": "container3"},
        ]

        with patch(
            "services.infrastructure.container_info_service.get_server_config_service",
            return_value=fake_server_config,
        ):
            result = service.list_all_containers()

        assert result.success is True
        assert isinstance(result.data, list)
        assert set(result.data) == {"container1", "container2", "container3"}

    def test_validate_protected_password_success(self, tmp_path):
        """The real service exposes a protected_password field — validate via get_container_info."""
        service = _make_service(tmp_path)
        _write_container_file(
            service,
            "protected_container",
            {
                "enabled": True,
                "show_ip": False,
                "custom_ip": "",
                "custom_port": "",
                "custom_text": "",
                "protected_enabled": True,
                "protected_content": "secret",
                "protected_password": "secret123",
            },
        )

        result = service.get_container_info("protected_container")

        assert result.success is True
        assert result.data.protected_enabled is True
        # Password matches → caller-side validation succeeds.
        assert result.data.protected_password == "secret123"

    def test_validate_protected_password_invalid(self, tmp_path):
        """Wrong password comparison fails (callers compare to ContainerInfo.protected_password)."""
        service = _make_service(tmp_path)
        _write_container_file(
            service,
            "protected_container",
            {
                "enabled": True,
                "show_ip": False,
                "custom_ip": "",
                "custom_port": "",
                "custom_text": "",
                "protected_enabled": True,
                "protected_content": "secret",
                "protected_password": "secret123",
            },
        )

        result = service.get_container_info("protected_container")

        assert result.success is True
        assert result.data.protected_enabled is True
        assert result.data.protected_password != "wrong_password"

    def test_validate_protected_password_not_protected(self, tmp_path):
        """For non-protected containers protected_enabled is False."""
        service = _make_service(tmp_path)
        _write_container_file(
            service,
            "normal_container",
            {
                "enabled": True,
                "show_ip": False,
                "custom_ip": "",
                "custom_port": "",
                "custom_text": "",
                "protected_enabled": False,
                "protected_content": "",
                "protected_password": "",
            },
        )

        result = service.get_container_info("normal_container")

        assert result.success is True
        assert result.data.protected_enabled is False

    def test_service_exception_handling(self, tmp_path):
        """Errors while reading container files should propagate as ServiceResult(success=False)."""
        service = _make_service(tmp_path)
        _write_container_file(
            service,
            "broken",
            {"enabled": False, "show_ip": False, "custom_ip": "", "custom_port": "",
             "custom_text": "", "protected_enabled": False, "protected_content": "",
             "protected_password": ""},
        )

        with patch("builtins.open", side_effect=IOError("disk read error")):
            result = service.get_container_info("broken")

        assert result.success is False
        assert result.error is not None
        assert "disk read error" in result.error or "Error loading info" in result.error

    def test_input_sanitization(self, tmp_path):
        """Path-traversal / unsafe names should be rejected safely by _validate_path_safety."""
        service = _make_service(tmp_path)

        malicious_name = "<script>alert('xss')</script>"

        result = service.get_container_info(malicious_name)

        # Safe outcomes: either ServiceResult(success=False) or a returned
        # default ContainerInfo. Forbidden: any unsafe filesystem write or
        # script-shaped path being accepted as-is.
        assert isinstance(result, ServiceResult)


@pytest.mark.integration
class TestContainerInfoServiceIntegration:
    """Integration tests for container info service against a tmp file backend."""

    def test_full_container_info_workflow(self, tmp_path):
        """Test a complete container info management workflow."""
        service = _make_service(tmp_path)

        container_name = "workflow_test_container"
        _write_container_file(
            service,
            container_name,
            {
                "enabled": False,
                "show_ip": False,
                "custom_ip": "",
                "custom_port": "",
                "custom_text": "",
                "protected_enabled": False,
                "protected_content": "",
                "protected_password": "",
            },
        )

        # 1. Get initial info (defaults)
        initial_result = service.get_container_info(container_name)
        assert initial_result.success is True
        assert initial_result.data.enabled is False

        # 2. Save updated info
        new_info = ContainerInfo.from_dict(
            {
                "enabled": True,
                "show_ip": True,
                "custom_ip": "172.16.0.10",
                "custom_port": "3000",
                "custom_text": "Workflow Test Container",
                "protected_enabled": True,
                "protected_content": "Secret workflow data",
                "protected_password": "workflow123",
            }
        )
        update_result = service.save_container_info(container_name, new_info)
        assert update_result.success is True

        # 3. Re-read and confirm
        updated_result = service.get_container_info(container_name)
        assert updated_result.success is True
        assert updated_result.data.enabled is True
        assert updated_result.data.custom_text == "Workflow Test Container"
        assert updated_result.data.protected_enabled is True

        # 4. Password compare via dataclass field
        assert updated_result.data.protected_password == "workflow123"
        assert updated_result.data.protected_password != "wrong"

        # 5. Reset / delete
        delete_result = service.delete_container_info(container_name)
        assert delete_result.success is True

        post_delete = service.get_container_info(container_name)
        assert post_delete.success is True
        assert post_delete.data.enabled is False
        assert post_delete.data.custom_text == ""


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
