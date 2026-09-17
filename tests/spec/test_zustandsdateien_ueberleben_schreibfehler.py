# -*- coding: utf-8 -*-
"""Ein fehlgeschlagener Schreibvorgang darf eine Zustandsdatei nicht zerstoeren.

KEIN ``@deckt``-Marker: Das waere eine neue Zusicherung, und die sind die
Entscheidung des Betreibers. Der Sache nach gehoert dieser Test zu Z7.

DER BEFUND: ``services/infrastructure/update_notifier.py:63`` schreibt mit
``open(self.status_file, 'w')`` + ``json.dump``. ``open(..., "w")`` kuerzt die
Datei im Moment des Oeffnens, ``json.dump`` schreibt stroemend - scheitert die
Serialisierung, bleibt ein halber Datensatz zurueck. Z7 sagt woertlich: "Ein
Absturz mitten im Schreiben laesst die alte Datei unversehrt."

RANG: BEWUSST TIEF. Anders als bei der Spendenmeldung (Commit 4aed2cb) gibt es
hier keinen unbarmherzigen Leser. ``update_notifier.py:56-58`` faengt den Fehler
und liefert Vorgaben; die Folge ist eine bereits weggeklickte
Aktualisierungsmeldung, die erneut erscheint. **Niemand verliert Daten.** Der
Befund steht hier, weil Z7 ihn woertlich verlangt, nicht weil er schmerzt.

WAS HIER NICHT GEPRUEFT UND DESHALB AUCH NICHT KORRIGIERT WIRD:
``services/mech/mech_reset_service.py:243`` hat dieselbe Bauart - und der Fall
ist aergerlicher, weil dieselbe Datei ``atomic_write_json`` bereits bei :25
importiert und zwoelf Zeilen vorher bei :202 benutzt, mit ausgeschriebener
Begruendung ("Previously a plain open(..., 'w'), which truncates the file the
moment ..."). Eine bewusste Umstellung, bei der eine Schwestermethode uebrig
blieb.

Trotzdem bleibt sie unangetastet: ``reset_evolution_mode`` baut seine Nutzlast
selbst (``use_dynamic``, ``difficulty_multiplier``, ``datetime.now().isoformat()``),
es gibt keinen Injektionspunkt von aussen. Ein Fehlschlag liesse sich nur durch
Attrappieren von ``json.dump`` erzwingen - dann prueft der Test die Attrappe,
nicht den Code. Der Programmtext sagt dazu: anhalten, wo sich nicht messen
laesst, was man aendert.

EIN EIGENER FEHLGRIFF, der hierher gehoert, weil er die Bauart dieses Tests
erklaert: Die erste Fassung wollte den Fehlschlag ueber ein SCHREIBGESCHUETZTES
VERZEICHNIS erzwingen - ``atomic_write_json`` braucht Schreibrecht am
Verzeichnis fuer seine Temp-Datei, ``open(..., "w")`` nicht. Gemessen ergab das
etwas anderes als erwartet: Der Schreibvorgang GELANG, beide Tests wurden rot an
``assert ergebnis is False`` (``assert True is False``). Schreibrecht am
Verzeichnis braucht man zum Anlegen und Umbenennen von Eintraegen, nicht zum
Oeffnen einer bestehenden Datei - es scheiterte also gar nichts, und es gab
nichts, was haette ueberleben muessen.

Schlimmer: Die geplante Korrektur haette in genau diesem Fall das Gegenteil
bewirkt. ``atomic_write_json`` waere dort GESCHEITERT, wo der Direktschreiber
gelingt. Ich haette einen funktionierenden Schreibvorgang kaputtgemacht und es
"Z7-Korrektur" genannt. Die vorab notierten Fehlschlag-Wege ("rot an den Bytes",
"alles gruen") enthielten diesen dritten Ausgang nicht; die Liste war
unvollstaendig.

WIE JETZT GEPRUEFT WIRD: ueber einen nicht serialisierbaren Wert im Woerterbuch,
das der AUFRUFER liefert - der einzige Punkt, an dem sich hier ehrlich ein
Fehlschlag erzwingen laesst, ohne etwas zu attrappieren. In BEIDEN Welten fliegt
derselbe ``TypeError`` heraus (die Fangliste bei :66 kennt ihn nicht), der
Unterschied liegt allein im Inhalt der Datei.

ABGRENZUNG: Der Gutfall ist bereits abgedeckt
(``tests/unit/services/infrastructure/test_infrastructure_services.py:893``) und
wird hier nicht wiederholt.

GEGENPROBE (durchgefuehrt 2026-09-17) - zwei Messungen, weil zwei Tests zu
belegen waren. Genannt werden TESTNAMEN statt Zeilennummern: Zweimal habe ich
heute eine Zeilenzahl notiert, die derselbe Schreibvorgang sofort veraltet hat.

*1. Der Befundtest war VOR der Korrektur rot*, an der Byte-Behauptung - und der
gemessene Inhalt bestaetigte die Beschreibung, statt sie zu widerlegen::

    + b'{\\n  "last_notified_version": "2.0",\\n  "notifications_shown": '
    - b'{"last_notified_version": "1.0", "notifications_shown": ["1.0"]}'

Ein halber Datensatz, abgebrochen genau dort, wo der nicht serialisierbare Wert
stand - nicht leer. Diese Unterscheidung stand VOR dem Lauf auf der Liste
moeglicher Fehlgriffe (beim Spendenbefund lag ich genau andersherum daneben:
dort erwartete ich leer und mass halb). ``pytest.raises(TypeError)`` hielt, die
Fangliste bei :66 kennt den TypeError also wirklich nicht. Nach der Korrektur:
2 gruen.

*2. Der Vorrichtungs-Waechter war von Anfang an gruen* und damit unbewiesen. Er
ist derjenige, der sicherstellt, dass ueberhaupt im Wegwerf-Verzeichnis geprueft
wird - waere er blind, koennte der Befundtest eines Tages an der echten Ablage
vorbeilaufen. Mutation: ``UpdateNotifier`` ignoriert sein ``config_dir``::

    -> 1 failed, 1 passed

Rot wurde er an SEINER eigenen Pfad-Behauptung:
``PosixPath('/app/config') == PosixPath('/tmp/pytest-of-ddc/...')``. Der
Befundtest blieb gruen - ein Ausgang, zu dem ich bewusst keine Vorhersage
gemacht hatte, weil er sich nicht herleiten liess.

*Vier Wege, auf denen diese Roten wertlos gewesen waeren*, standen vor jedem Lauf
fest und traten nie ein: der Test bleibt gruen (waere hohl); er faellt an einer
anderen Behauptung als dem geprueften Zusammenhang; Fehler statt Fehlschlag;
Sammel- oder Importfehler.

BETROFFENE GRUPPEN, alle gruen gemessen: spec 84, services/infrastructure 197,
extended 731, app_modules 73.
"""

import json

import pytest

from services.infrastructure.update_notifier import UpdateNotifier

ALTER_STATUS = {"last_notified_version": "1.0", "notifications_shown": ["1.0"]}


@pytest.fixture
def melder(tmp_path):
    """UpdateNotifier auf einem Wegwerf-Verzeichnis, mit gefuellter Zustandsdatei.

    Der Konstruktor nimmt ``config_dir`` entgegen; so macht es
    ``tests/unit/services/infrastructure/test_infrastructure_services.py:887``
    bereits. Kein Umbiegen von ``__file__`` noetig.
    """
    dienst = UpdateNotifier(config_dir=str(tmp_path))
    dienst.status_file.write_text(json.dumps(ALTER_STATUS), encoding="utf-8")
    return dienst


def test_die_vorrichtung_ist_richtig_aufgebaut(melder, tmp_path):
    """Sicherung gegen ein stumpfes Werkzeug.

    Zeigt der Dienst woanders hin oder fehlt die Zustandsdatei, prueft der Test
    unten am Ziel vorbei und waere gruen, ohne etwas zu belegen. Genau diese
    Bauart hat in diesem Programm schon zweimal einen Melder wertlos gemacht.
    """
    assert melder.status_file.parent == tmp_path
    assert json.loads(melder.status_file.read_text(encoding="utf-8")) == ALTER_STATUS


def test_der_alte_stand_ueberlebt_einen_fehlgeschlagenen_schreibvorgang(melder):
    """DER BEFUND: update_notifier.py:63 kuerzt, bevor die Serialisierung scheitert.

    Der ``TypeError`` fliegt in beiden Welten heraus - ``save_update_status``
    faengt ihn nicht (:66). Geprueft wird deshalb nicht das Verhalten der
    Methode, sondern was danach auf der Platte steht.
    """
    vorher = melder.status_file.read_bytes()

    with pytest.raises(TypeError):
        melder.save_update_status({
            "last_notified_version": "2.0",
            "notifications_shown": object(),   # json kann das nicht serialisieren
        })

    assert melder.status_file.read_bytes() == vorher, (
        "Der alte Benachrichtigungsstand wurde beschaedigt. open(..., 'w') kuerzt "
        "die Datei beim Oeffnen, und json.dump schreibt stroemend - beim "
        "Fehlschlag bleibt ein halber Datensatz zurueck. Z7 verlangt, dass ein "
        "Abbruch mitten im Schreiben die alte Datei unversehrt laesst; "
        "utils/atomic_io.py serialisiert dafuer VOR dem Oeffnen "
        "(utils/atomic_io.py:66-69)."
    )
