from pathlib import Path
import json

from utils.container_info_manager import ContainerInfoManager


def test_container_info_manager_crud(tmp_path):
    cfg_dir = tmp_path / "container_info"
    mgr = ContainerInfoManager(config_dir=str(cfg_dir))

    # Defaults when missing
    info = mgr.load_container_info("Test-Container")
    assert info["enabled"] is False
    assert info["custom_text"] == ""

    # Save minimal valid info
    ok = mgr.save_container_info("Test-Container", {"enabled": True, "custom_text": "Hello"})
    assert ok is True

    # Read back
    back = mgr.load_container_info("Test-Container")
    assert back["enabled"] is True
    assert back["custom_text"] == "Hello"
    assert back["created_at"] is not None
    assert back["last_updated"] is not None

    # Update specific fields
    ok2 = mgr.update_container_info("Test-Container", show_ip=True, custom_port="12345")
    assert ok2 is True
    updated = mgr.load_container_info("Test-Container")
    assert updated["show_ip"] is True
    assert updated["custom_port"] == "12345"

    # List containers with info
    lst = mgr.list_containers_with_info()
    assert "test-container" in lst  # filename uses sanitized/lowercase

    # Delete
    ok3 = mgr.delete_container_info("Test-Container")
    assert ok3 is True
    assert mgr.list_containers_with_info() == []


def test_container_info_manager_sanitizes_and_limits(tmp_path):
    cfg_dir = tmp_path / "container_info"
    mgr = ContainerInfoManager(config_dir=str(cfg_dir))

    long_text = "x" * 500
    long_ip = "1" * 300
    long_port = "9" * 50

    mgr.save_container_info(
        "Weird Name!!",
        {
            "enabled": "yes",
            "show_ip": 1,
            "custom_text": long_text,
            "custom_ip": long_ip,
            "custom_port": long_port,
        },
    )

    # File path should be sanitized
    info_files = list(Path(cfg_dir).glob("*_info.json"))
    assert len(info_files) == 1
    # Current implementation removes spaces and keeps only [a-z0-9-_]
    assert info_files[0].name.startswith("weirdname_")

    data = json.loads(info_files[0].read_text())
    assert data["enabled"] is True
    assert data["show_ip"] is True
    assert len(data["custom_text"]) == 250
    assert len(data["custom_ip"]) <= 255
    assert len(data["custom_port"]) <= 5


