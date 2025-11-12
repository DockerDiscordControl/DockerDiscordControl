"""Compatibility helpers for optional runtime integrations."""

from __future__ import annotations

import logging

try:  # pragma: no cover - exercised implicitly when gevent is installed
    import gevent.monkey

    gevent.monkey.patch_all(thread=True, select=True, subprocess=True, socket=True)
    HAS_GEVENT = True
except ImportError:  # pragma: no cover - simple environment detection
    HAS_GEVENT = False


def initialize_gevent(logger: logging.Logger) -> None:
    """Log gevent runtime details and ensure required patches are applied."""
    if not HAS_GEVENT:
        return

    try:
        from gevent import get_hub, monkey

        current_hub = get_hub()
        logger.info("Initializing app in Gevent environment, hub: %s", current_hub)

        required_modules = {
            "socket": monkey.patch_socket,
            "ssl": monkey.patch_ssl,
            "threading": monkey.patch_thread,
        }

        for module_name, patcher in required_modules.items():
            if not monkey.is_module_patched(module_name):
                logger.warning("%s module not patched by Gevent, applying patch...", module_name.upper())
                patcher()
    except ImportError as exc:  # pragma: no cover - defensive logging
        logger.error("Gevent error during init: %s", exc)


def apply_gevent_fork_workaround(logger: logging.Logger) -> None:
    """Patch Gevent fork hooks to avoid strict assertions during teardown."""
    if not HAS_GEVENT:
        return

    try:  # pragma: no cover - depends on gevent availability
        import gevent.threading

        def safer_after_fork_in_child(self, thread):  # type: ignore[override]
            if hasattr(thread, "is_alive") and thread.is_alive():
                logger.warning(
                    "Thread %s is still alive after fork; skipping Gevent assertion.",
                    getattr(thread, "name", "unknown"),
                )

        gevent.threading._ForkHooks.after_fork_in_child = safer_after_fork_in_child  # type: ignore[attr-defined]
        logger.info("Applied Gevent fork hooks patch to avoid threading assertions")
    except (ImportError, AttributeError) as exc:
        logger.warning("Could not patch Gevent fork hooks: %s", exc)


def spawn_delayed(delay: float, target, *args, **kwargs):  # pragma: no cover - thin wrapper
    """Spawn a delayed callable using Gevent when available, falling back to threading."""
    if HAS_GEVENT:
        import gevent

        def runner():
            gevent.sleep(delay)
            target(*args, **kwargs)

        gevent.spawn(runner)
    else:
        import threading

        timer = threading.Timer(delay, target, args=args, kwargs=kwargs)
        timer.daemon = True
        timer.start()

    return None
