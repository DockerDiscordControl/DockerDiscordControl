# -*- coding: utf-8 -*-
"""The fields the donation confirmation reads exist on the objects it gets.

No ``@covers`` marker: a finding, not a guarantee.

THE FINDING (stage 4 review, stage B, section 06 F1) is REFUTED, and this
test is what the refutation rests on. The report said ``new_state.Power``
(capital P) at the end of DonationBroadcastModal.callback must raise, because
every neighbouring line reads ``.power``. It does not: ``new_state`` is a
``MechState``, which carries ``Power`` as a backward-compatibility alias for
``power_level``, while the lowercase reads are on the SERVICE results
(``new_state_result.power``) - two different objects, each read correctly.

The fragility is real all the same: the donation is already booked in the
ledger when those lines run, and neither except clause around them catches
AttributeError. Dropping the alias - it is marked "legacy" - would take the
money and leave the donor with a "Processing..." message. So the alias is
pinned here, with the reason.
"""

import ast
from pathlib import Path

from services.mech.mech_service_adapter import MechState

PROJECT = Path(__file__).resolve().parents[2]


def _state():
    return MechState(evolution_level=3, power_level=12.5, is_offline=False,
                     total_donations=42.0, next_evolution_at=50.0,
                     evolution_progress=84, animation_type="walk",
                     speed_level=25.0, difficulty_tier="steady",
                     difficulty_bin=2, member_count=14)


def test_mech_state_keeps_the_aliases_the_donation_path_uses():
    state = _state()

    assert state.Power == state.power_level, "docker_control reads new_state.Power"
    assert state.level == state.evolution_level, "and new_state.level"
    assert state.total_donated == state.total_donations


def test_the_donation_path_still_reads_those_fields():
    """Guard against a stale test: if the code stops reading them, say so."""
    source = (PROJECT / "cogs" / "docker_control.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    read = {node.attr for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
            and node.value.id == "new_state"}

    assert {"Power", "level"} <= read, (
        f"the donation path no longer reads these fields ({sorted(read)}) - "
        "this test is pinning something nobody uses"
    )
