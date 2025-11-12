import logging
from pathlib import Path

from app.bootstrap.runtime import (
    configure_environment,
    ensure_log_files,
    resolve_timezone,
)


def test_configure_environment_sets_default():
    env = {}

    value = configure_environment(env)

    assert value == "true"
    assert env["DDC_DISCORD_SKIP_TOKEN_LOCK"] == "true"


def test_resolve_timezone_falls_back_to_utc():
    logger = logging.getLogger("ddc.bootstrap.test")
    logger.setLevel(logging.INFO)

    tz = resolve_timezone({"timezone": "Invalid/Zone"}, logger=logger)

    assert tz.zone == "UTC"


def test_ensure_log_files_creates_handlers(tmp_path: Path):
    logger = logging.getLogger("ddc.bootstrap.logfiles")
    logger.setLevel(logging.INFO)

    # Remove existing handlers to keep the test isolated
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    ensure_log_files(logger, tmp_path)

    created_files = {
        Path(getattr(handler, "baseFilename", ""))
        for handler in logger.handlers
        if isinstance(handler, logging.FileHandler)
    }

    expected = {tmp_path / "discord.log", tmp_path / "bot_error.log"}
    assert expected.issubset(created_files)

    # Cleanup handlers to avoid interference with other tests
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
