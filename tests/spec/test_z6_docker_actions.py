# -*- coding: utf-8 -*-
# @deckt Z6
"""Z6 - DDC entfernt oder zerstoert niemals einen Container.

Es gibt genau drei Aktionen: ``start``, ``stop``, ``restart``. Kein ``kill``,
kein ``remove``, kein ``prune``.

Diese Zusicherung ist die einzige, die heute schon **haelt**. Sie wird hier
festgenagelt, BEVOR sie jemand aufweicht - genau darum geht es: Ein Container
zu entfernen ist nicht zurueckzunehmen, und ein spaeterer "waere praktisch,
wenn DDC auch aufraeumen koennte"-Umbau soll an einem Test scheitern und nicht
an der Aufmerksamkeit des Naechsten.

Es gibt zwei Implementierungen, und beide muessen die Zusicherung erfuellen:

* ``DockerActionService._valid_actions`` (``docker_action_service.py:90-94``) -
  der Weg, den Knopf, Zeitplan und Web-Panel nehmen.
* ``docker_action()`` (``docker_utils.py:626-631``) - der aeltere Weg, den nur
  noch die Automatikregeln benutzen.

Der Test liest die Aktionsnamen aus beiden Stellen und vergleicht sie mit einer
hier ausgeschriebenen Liste. Bewusst NICHT geprueft wird, was die Lambda-Ausdruecke
tun - das waere ein Spiegeltest der Implementierung. Geprueft wird die Zusage:
diese drei Namen, keine weiteren.

GEGENPROBE (durchgefuehrt 2026-09-16) - hier anders gelagert als sonst:

Diese Zusicherung haelt heute, also gibt es keinen Fehler, den man rueckgaengig
machen koennte. Alle vier Tests waren beim ersten Lauf gruen. Genau das macht sie
verdaechtig - ein Test, der nie rot war, koennte auch einer sein, der nicht rot
werden KANN. Dagegen zwei Vorkehrungen:

1. ``test_die_pruefung_oben_kann_ueberhaupt_anschlagen`` belegt am Suchmuster
   selbst, dass es ``container.remove()``, ``containers.prune()`` und
   ``client.kill()`` erkennt und harmlose Zeilen in Ruhe laesst.
2. Die erste Fassung der Quelltext-Pruefung hatte einen echten Fehler:
   ``if ".remove(" in zeile and "containers" not in zeile: continue`` uebersprang
   ausgerechnet ``container.remove()``, weil darin "containers" nicht vorkommt.
   Sie war gruen und konnte fuer den wichtigsten Fall nicht fehlschlagen.
   Gefunden beim Gegenlesen, nicht im Lauf.

Ebenfalls beim Gegenlesen gefunden und entfernt: eine Zusicherung der Form
``assert ... is None or True`` - immer wahr, ausgerechnet in der Absicherung
gegen wertlose Tests.

Vorhergesagt hatte ich fuer die beiden mittleren Tests nur mittlere Sicherheit
(der AST-Auszug sammelt jedes Dict-Literal der Funktion; das Suchmuster koennte
anderswo harmlos anschlagen). Beide haben gehalten.
"""

import ast
import inspect
import re
from pathlib import Path

import pytest

ERLAUBT = {"start", "stop", "restart"}

# Namen, deren Auftauchen die Zusicherung bricht. Nicht erschoepfend - eine
# unbekannte vierte Aktion faellt schon ueber den Mengenvergleich auf.
VERBOTEN = {"kill", "remove", "rm", "prune", "delete", "destroy"}


def test_action_service_kennt_genau_drei_aktionen():
    """Der Hauptweg: Knopf, Zeitplan, Web-Panel."""
    from services.docker_service.docker_action_service import DockerActionService

    dienst = DockerActionService()
    assert set(dienst._valid_actions) == ERLAUBT, (
        f"Die Aktionsliste hat sich geaendert: {sorted(dienst._valid_actions)}. "
        f"DDC soll Container starten, stoppen und neu starten - nicht entfernen."
    )


def test_legacy_weg_kennt_genau_dieselben_drei():
    """Der aeltere Weg der Automatikregeln.

    Wird per AST aus dem Quelltext gelesen: ``valid_actions`` ist eine lokale
    Variable in ``docker_action()`` und von aussen nicht erreichbar, ohne die
    Funktion auszufuehren - was einen echten Docker-Aufruf bedeuten wuerde.
    """
    from services.docker_service import docker_utils

    quelle = inspect.getsource(docker_utils.docker_action)
    baum = ast.parse(quelle.strip())

    schluessel = set()
    for knoten in ast.walk(baum):
        if isinstance(knoten, ast.Assign) and isinstance(knoten.value, ast.Dict):
            for k in knoten.value.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    schluessel.add(k.value)

    assert schluessel == ERLAUBT, (
        f"Der Legacy-Weg kennt andere Aktionen als der Hauptweg: "
        f"{sorted(schluessel)} statt {sorted(ERLAUBT)}. Zwei Wege, dieselbe "
        f"Regel - sie duerfen nicht auseinanderlaufen."
    )


def test_keine_zerstoerende_docker_aktion_im_quelltext():
    """Kein Aufruf, der einen Container entfernt - projektweit.

    Prueft die Aufrufstelle, nicht die Funktion: Die beiden Listen oben koennen
    korrekt sein, waehrend anderswo direkt ``container.remove()`` steht. Genau
    diese Sorte Luecke ("die Funktion ist geprueft, der Aufruf daneben nicht")
    war ein Befund aus Stufe 0.
    """
    wurzel = Path(__file__).resolve().parents[2]
    verdaechtig = []

    # Nur Aufrufe auf einem Empfaenger, der nach Docker aussieht. Ohne diese
    # Eingrenzung schluegen harmlose Zeilen wie ``liste.remove(x)`` an.
    #
    # Die erste Fassung dieser Pruefung hatte hier ``if ".remove(" in zeile and
    # "containers" not in zeile: continue`` - und uebersprang damit ausgerechnet
    # ``container.remove()``, weil darin "containers" nicht vorkommt. Sie konnte
    # fuer den wichtigsten Fall nicht fehlschlagen. Gefunden beim Gegenlesen,
    # nicht im Lauf: gruen waere sie gewesen.
    empfaenger = re.compile(
        r"\b(?:container|containers|client|docker_client)\.(" + "|".join(VERBOTEN) + r")\s*\("
    )

    for ordner in ("services", "cogs", "app", "utils"):
        for datei in (wurzel / ordner).rglob("*.py"):
            for nr, zeile in enumerate(
                datei.read_text(encoding="utf-8", errors="replace").splitlines(), 1
            ):
                nackt = zeile.strip()
                if nackt.startswith("#"):
                    continue
                if empfaenger.search(nackt):
                    verdaechtig.append(f"{datei.relative_to(wurzel)}:{nr}: {nackt}")

    assert not verdaechtig, (
        "Zerstoerende Docker-Aufrufe gefunden:\n" + "\n".join(verdaechtig)
    )


def test_die_pruefung_oben_kann_ueberhaupt_anschlagen():
    """Sicherung gegen ein stumpfes Werkzeug.

    Ein Suchmuster, das nichts findet, ist von einem, das nichts zu finden gibt,
    nicht zu unterscheiden. Hier wird belegt, dass es den Fall erkennt, den es
    erkennen soll - und dass es harmlose Zeilen in Ruhe laesst.
    """
    muster = re.compile(
        r"\b(?:container|containers|client|docker_client)\.(" + "|".join(VERBOTEN) + r")\s*\("
    )

    assert muster.search("container.remove()"), "erkennt container.remove() nicht"
    assert muster.search("containers.prune()"), "erkennt containers.prune() nicht"
    assert muster.search("self.client.kill(c)"), "erkennt client.kill() nicht"
    assert not muster.search("self.pending_actions.remove(name)"), "falscher Alarm"
    assert not muster.search("liste.delete(x)"), "falscher Alarm"
