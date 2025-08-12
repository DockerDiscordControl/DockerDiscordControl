from utils.docker_utils import get_container_timeouts, DEFAULT_TIMEOUT_CONFIG


def test_timeouts_default_on_empty():
    assert get_container_timeouts("") == DEFAULT_TIMEOUT_CONFIG


def test_timeouts_builtin_patterns():
    cfg = get_container_timeouts("minecraft-server")
    assert cfg["stats_timeout"] <= cfg["info_timeout"]

    cfg2 = get_container_timeouts("postgres-db")
    assert "stats_timeout" in cfg2 and "info_timeout" in cfg2


