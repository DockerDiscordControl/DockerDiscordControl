# -*- coding: utf-8 -*-
"""
THE FINDING (review E54, found by the v2.3.1 -> v2.4 upgrade test on
2026-09-22): every save in the web panel reset the order of every container to
999.

`ConfigFormParserService.parse_servers_from_form` read each container's order
from a form field `order_<name>`. No template has ever rendered such a field -
not in v2.4, not in v2.3.1 - so the browser never sends one, and the parser
fell back to 999 for every container, every time. The save then wrote
`"order": 999` into every container file.

What the browser DOES send is `server_order`: the containers in the order the
operator arranged them, joined with "__,__". The save stored that in
server_order.json, which the status messages read - so those stayed in order
and nothing looked wrong at first. But the admin overview, the info dropdown
and the admin dropdown sort by the `order` field in the container files, and
after the first save all of them fell back to whatever order the files were
listed in.

Measured on the upgrade test's data: orders 1/2/3 before a save, 999/999/999
after. The maintainer's own installation carries orders 0-10 from an earlier
version - exactly each container's position in server_order.json - and would
have lost them at the next save.

The form below is what the page's save handler builds (app/templates/
_scripts.html): the fields a real browser posts, and not one more.
"""

from werkzeug.datastructures import MultiDict

from services.config.config_form_parser_service import ConfigFormParserService


def _browser_form(order, *, extra=()):
    """The save handler's fields for active containers in `order`."""
    fields = [("server_order", "__,__".join(order))]
    for name in order:
        for action in ("status", "start", "stop", "restart"):
            fields.append((f"allow_{action}_{name}", "1"))
        fields.append((f"display_name_{name}", name))
    fields += [("selected_servers", name) for name in order]
    fields.append(("config_split_enabled", "1"))
    fields += list(extra)
    return MultiDict(fields)


def _orders(form):
    return {s["docker_name"]: s["order"] for s in ConfigFormParserService.parse_servers_from_form(form)}


def test_the_order_the_operator_arranged_is_saved():
    """THE FINDING: the browser sends the order, and it must arrive."""
    orders = _orders(_browser_form(["Icarus2", "Icarus", "ProjectZomboid", "Valheim"]))

    assert orders == {"Icarus2": 0, "Icarus": 1, "ProjectZomboid": 2, "Valheim": 3}, (
        f"the save wrote {orders} - the arranged order was dropped"
    )


def test_rearranging_changes_the_saved_order():
    """Not merely 'something other than 999': moving a container moves it."""
    first = _orders(_browser_form(["Valheim", "Icarus"]))
    second = _orders(_browser_form(["Icarus", "Valheim"]))

    # Strict comparisons, not sorted(): with every value at 999, sorted() keeps
    # the insertion order - which is the expected order - and a first version of
    # this test passed against the bug it was written for.
    assert first["Valheim"] < first["Icarus"], first
    assert second["Icarus"] < second["Valheim"], second


def test_an_explicit_order_field_still_wins():
    """COUNTER-CHECK: a client that does send order_<name> keeps its value -
    the parser's existing tests rely on that."""
    orders = _orders(_browser_form(["Valheim", "Icarus"], extra=[("order_Icarus", "7")]))

    assert orders == {"Valheim": 0, "Icarus": 7}


def test_without_any_order_information_it_is_still_999():
    """COUNTER-CHECK: a form with neither server_order nor order_<name> keeps
    the old default, so nothing is invented."""
    form = MultiDict([("selected_servers", "Valheim"), ("allow_status_Valheim", "1")])

    assert _orders(form) == {"Valheim": 999}
