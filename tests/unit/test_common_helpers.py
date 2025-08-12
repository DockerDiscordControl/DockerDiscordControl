from utils import common_helpers as ch


def test_safe_get_nested():
    data = {"a": {"b": {"c": 5}}}
    assert ch.safe_get_nested(data, "a.b.c") == 5
    assert ch.safe_get_nested(data, "a.x.c", default=42) == 42


def test_format_uptime():
    assert ch.format_uptime(125) == "2m"
    assert ch.format_uptime(3700).startswith("1h")
    assert ch.format_uptime(-1) == "Unknown"


def test_format_memory():
    assert ch.format_memory(500) == "500 B"
    assert ch.format_memory(2048).endswith("KB")
    assert ch.format_memory(None) == "Unknown"


def test_format_cpu_percentage():
    assert ch.format_cpu_percentage(12.345) == "12.3%"
    assert ch.format_cpu_percentage("bad") == "Unknown"


def test_truncate_string():
    text = "hello world"
    assert ch.truncate_string(text, 20) == text
    assert ch.truncate_string(text, 5) == "he..."


def test_validate_container_name():
    assert ch.validate_container_name("valid_name-1") is True
    assert ch.validate_container_name("-bad") is False
    assert ch.validate_container_name("a" * 70) is False


def test_parse_boolean():
    assert ch.parse_boolean(True) is True
    assert ch.parse_boolean("yes") is True
    assert ch.parse_boolean("no") is False
    assert ch.parse_boolean(0) is False
    assert ch.parse_boolean(2) is True


def test_sanitize_log_message():
    msg = "token=abcdef password=123 key=ABC"
    sanitized = ch.sanitize_log_message(msg)
    assert "***" in sanitized


def test_batch_process():
    items = list(range(10))
    batches = ch.batch_process(items, batch_size=3)
    assert batches[0] == [0, 1, 2]
    assert batches[-1] == [9]


def test_deep_merge_dicts():
    d1 = {"a": {"b": 1}, "x": 1}
    d2 = {"a": {"c": 2}, "y": 2}
    merged = ch.deep_merge_dicts(d1, d2)
    assert merged["a"]["b"] == 1 and merged["a"]["c"] == 2
    assert merged["y"] == 2


