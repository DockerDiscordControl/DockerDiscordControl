from pathlib import Path
import json

from services.infrastructure.container_info_service import ContainerInfoService, ContainerInfo


def test_container_info_service_crud(tmp_path):
    cfg_dir = tmp_path / "container_info"
    service = ContainerInfoService(config_dir=str(cfg_dir))

    # Defaults when missing
    result = service.get_container_info("Test-Container")
    assert result.success is True
    assert result.data.enabled is False
    assert result.data.custom_text == ""

    # Save container info
    container_info = ContainerInfo(
        enabled=True,
        show_ip=False,
        custom_ip="",
        custom_port="",
        custom_text="Hello"
    )
    
    save_result = service.save_container_info("Test-Container", container_info)
    assert save_result.success is True

    # Read back
    back_result = service.get_container_info("Test-Container")
    assert back_result.success is True
    assert back_result.data.enabled is True
    assert back_result.data.custom_text == "Hello"

    # List containers with info
    list_result = service.list_all_containers()
    assert list_result.success is True
    assert "test-container" in list_result.data  # filename uses sanitized/lowercase

    # Delete
    delete_result = service.delete_container_info("Test-Container")
    assert delete_result.success is True
    
    list_after_delete = service.list_all_containers()
    assert list_after_delete.success is True
    assert list_after_delete.data == []


def test_container_info_service_validation(tmp_path):
    cfg_dir = tmp_path / "container_info"
    service = ContainerInfoService(config_dir=str(cfg_dir))

    # Test with extreme values
    container_info = ContainerInfo(
        enabled=True,
        show_ip=True,
        custom_text="x" * 500,  # Will be truncated
        custom_ip="1" * 300,    # Will be truncated  
        custom_port="9" * 50    # Will be truncated
    )

    save_result = service.save_container_info("Weird Name!!", container_info)
    assert save_result.success is True

    # File path should be sanitized
    info_files = list(Path(cfg_dir).glob("*_info.json"))
    assert len(info_files) == 1
    assert info_files[0].name.startswith("weirdname_")

    # Verify truncation worked
    back_result = service.get_container_info("Weird Name!!")
    assert back_result.success is True
    assert back_result.data.enabled is True
    assert back_result.data.show_ip is True
    assert len(back_result.data.custom_text) <= 250
    assert len(back_result.data.custom_ip) <= 255
    assert len(back_result.data.custom_port) <= 5


def test_container_info_immutable_dataclass():
    # Test that ContainerInfo is immutable
    info = ContainerInfo(
        enabled=True,
        show_ip=False,
        custom_ip="test.com",
        custom_port="8080",
        custom_text="Test text"
    )
    
    # Should not be able to modify
    try:
        info.enabled = False
        assert False, "Should not be able to modify frozen dataclass"
    except (AttributeError, TypeError):
        pass  # Expected

    # Test from_dict and to_dict
    data = {"enabled": True, "show_ip": True, "custom_text": "Test"}
    info_from_dict = ContainerInfo.from_dict(data)
    assert info_from_dict.enabled is True
    assert info_from_dict.show_ip is True
    assert info_from_dict.custom_text == "Test"
    
    back_to_dict = info_from_dict.to_dict()
    assert back_to_dict["enabled"] is True
    assert back_to_dict["show_ip"] is True
    assert back_to_dict["custom_text"] == "Test"