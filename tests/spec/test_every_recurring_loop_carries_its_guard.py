# -*- coding: utf-8 -*-
"""Every loop that repeats carries the guard that lets it repeat.

THE FINDING (independent review of the cog modules, 2026-09-23):
`performance_cache_clear_loop` is the only recurring loop without
`@survives_one_bad_cycle`:

    @tasks.loop(minutes=5)                  # and nothing else
    async def performance_cache_clear_loop(self):
        try:
            from .control_ui import _clear_caches
            _clear_caches()
            if hasattr(self, '_embed_cache'):
                if len(self._embed_cache.get('translated_terms', {})) > 100:
        except (discord.errors.DiscordException, RuntimeError, ValueError):

and its except tuple omits ImportError, TypeError and AttributeError - the
three the body can actually produce: a deferred import, and len() on an
_embed_cache entry that is not a mapping. A tasks.loop whose body raises
something it does not catch stops FOR GOOD until a restart.

What that costs is not loud: the seven module-level caches in
control_ui._clear_caches - including the translation cache - are never cleared
again, so a language change stops taking effect on rendered panels and memory
grows for the life of the process.

HONEST ABOUT THE TRIGGER: the reviewer could not construct an input that makes
_clear_caches() raise, and neither could I - all seven targets are plain
.clear() calls. This is reported as the one structural gap in an otherwise
complete set, not as something anybody has seen fail. The death IS already
reported (test_every_loop_says_so_when_it_dies covers it); what is missing is
surviving it.

WHY A RATCHET AND NOT A TEST OF THAT ONE LOOP: the loops are read off the
class, the way the neighbouring file already does it, so a loop added tomorrow
is covered today. A hard-coded list would be a snapshot that passes for ever
while a new loop goes unguarded.

COUNTER-CHECK (2026-09-23): red before - it named performance_cache_clear_loop.
The second test proves the scan sees loops at all, so a passing first test is
not an empty search.
"""

import pytest

from discord.ext import tasks

from cogs.docker_control import DockerControlCog

# A loop that runs ONCE is not "recurring": there is no next cycle to survive
# into. These start other things and end.
ONE_SHOT = {"start_mech_cache_loop", "initial_animation_cache_warmup"}


def _recurring_loops():
    """{name: Loop} for every loop on the cog that repeats."""
    found = {}
    for name in dir(DockerControlCog):
        candidate = getattr(DockerControlCog, name, None)
        if isinstance(candidate, tasks.Loop) and name not in ONE_SHOT:
            found[name] = candidate
    return found


def _is_guarded(loop) -> bool:
    """True when survives_one_bad_cycle wrapped this loop's coroutine."""
    return getattr(loop.coro, "_ddc_survives_one_bad_cycle", False)


def test_every_recurring_loop_is_guarded():
    """THE FINDING: one of them was not."""
    unguarded = sorted(name for name, loop in _recurring_loops().items()
                       if not _is_guarded(loop))

    assert unguarded == [], (
        f"these loops stop for good on the first exception their body does not "
        f"catch, and nothing restarts them until DDC does: {unguarded}")


def test_the_scan_sees_the_loops_at_all():
    """Counter-check: a search that finds nothing would pass the test above."""
    loops = _recurring_loops()

    assert len(loops) >= 3, f"only {len(loops)} recurring loops found: {sorted(loops)}"
    assert "status_update_loop" in loops


def test_a_one_shot_loop_is_not_demanded_to_be_guarded():
    """Counter-check: the exemption is named, not silent."""
    for name in ONE_SHOT:
        assert isinstance(getattr(DockerControlCog, name, None), tasks.Loop), (
            f"{name} is exempted from the guard but is not a loop any more - "
            "the exemption would then hide a real one")
