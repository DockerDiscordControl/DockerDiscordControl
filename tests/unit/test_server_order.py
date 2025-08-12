import os
import json

from utils import server_order


def test_save_and_load_server_order(tmp_path, monkeypatch):
    # Redirect ORDER_FILE into tmp dir
    order_file = tmp_path / "server_order.json"
    monkeypatch.setattr(server_order, "ORDER_FILE", str(order_file))

    order = ["a", "b", "c"]
    assert server_order.save_server_order(order) is True

    loaded = server_order.load_server_order()
    assert loaded == order

    # File exists and content is valid
    assert order_file.exists()
    data = json.loads(order_file.read_text())
    assert data["server_order"] == order


def test_update_server_order_from_config_direct_list(tmp_path, monkeypatch):
    order_file = tmp_path / "server_order.json"
    monkeypatch.setattr(server_order, "ORDER_FILE", str(order_file))

    cfg = {"server_order": ["x", "y"]}
    assert server_order.update_server_order_from_config(cfg) is True
    assert server_order.load_server_order() == ["x", "y"]


def test_update_server_order_from_config_from_servers(tmp_path, monkeypatch):
    order_file = tmp_path / "server_order.json"
    monkeypatch.setattr(server_order, "ORDER_FILE", str(order_file))

    cfg = {"servers": [{"docker_name": "one"}, {"docker_name": "two"}, {"docker_name": None}]}
    assert server_order.update_server_order_from_config(cfg) is True
    assert server_order.load_server_order() == ["one", "two"]


