# -*- coding: utf-8 -*-
# @deckt Z10
"""Z10 - Kein Image wird ausgeliefert, dessen Tests nicht gruen gelaufen sind.

Ein veroeffentlichtes Image hat einen vollstaendigen, bestandenen Testlauf hinter
sich.

Warum das eine Zusicherung an den NUTZER ist und nicht bloss Hausordnung: Wer
DDC aus Unraid Community Apps installiert, bekommt genau dieses Image. Laeuft die
Suite nicht, oder laeuft sie rot durch, merkt das niemand - bis es auf dem Server
des Nutzers auffaellt. Das ist der Lehrsatz "unbemerkt schlaegt selten" in seiner
teuersten Form.

Befund aus der Bestandsaufnahme: ``docker-publish.yml`` fuehrt ueberhaupt keine
Tests aus (Checkout, QEMU, Buildx, Login, Metadata, Build-and-push - fertig), und
in ``tests.yml`` enden die Testschritte auf ``|| true``, sodass der Schritt nicht
fehlschlagen KANN. Ein rot laufender Test hat damit keine Wirkung auf nichts.

Dieser Test ist bei seiner Entstehung ROT. Die Korrektur beruehrt den
Auslieferungsweg des Projekts und ist deshalb eine Entscheidung des Betreibers,
keine technische - sie wird bewusst NICHT mit diesem Test zusammen vorgenommen.

Geprueft wird der Quelltext der Workflow-Dateien. Das ist ein statischer Test,
kein ausgefuehrtes CI: Er belegt, was in der Datei steht, nicht was GitHub daraus
macht. Dasselbe Mittel benutzt das Projekt bereits in ``test_pkg_f_scripts.py``
fuer Dockerfile und Healthcheck.

GEGENPROBE (durchgefuehrt 2026-09-16) - mit einer Schaerfung dazwischen:

Erster Lauf: beide Tests rot. Der zweite meldete aber nur ``tests.yml:127``
(Integrationstests) - und das doppelt, weil Zeilensuche und Blocksuche denselben
Treffer lieferten. Den **wichtigeren** Fall verfehlte er: Im Unit-Test-Schritt
steht ``python -m pytest`` bei :73 und das zugehoerige ``|| true`` erst bei :80,
getrennt durch Zeilenfortsetzungen. Eine zeilenweise Suche findet das nie.

Geschaerft durch Zerlegung in ``- name:``-Schritte, und um ``continue-on-error:
true`` erweitert - ein zweiter Weg, einen Testschritt folgenlos zu machen, den
die erste Fassung ueberhaupt nicht kannte.

Danach vier Befunde statt einem, und der vierte war vorher unbekannt::

    code-quality.yml:295 'Run tests with coverage': continue-on-error: true
    tests.yml:67 'Run unit tests with coverage':    '|| true'
    tests.yml:122 'Run integration tests':          '|| true'
    tests.yml:122 'Run integration tests':          continue-on-error: true

Also **drei** Testlaeufe in der CI, von denen keiner rot werden kann. Die
Berichtswerkzeuge in code-quality.yml (radon, pylint, flake8, mypy) hat der Test
korrekt in Ruhe gelassen - keine Fehlalarme.

KORREKTUR DURCHGEFUEHRT (2026-09-17), nach Entscheidung des Betreibers fuer das
volle Gatter in gruppenweiser Form:

``docker-publish.yml`` bekam einen eigenen ``test``-Job, an dem ``build_and_push``
per ``needs:`` haengt. Die vier Schutzschalter sind weg.

Dabei kam heraus, dass "Schutzschalter entfernen" nicht genuegte: Die drei
Testaufrufe der CI (``pytest tests/unit/``, ``pytest tests/``) brechen beim
EINSAMMELN ab - 79 bzw. 18 Fehler, kein einziger Test lief je. Die Schalter
verbargen also nicht rote Tests, sondern dass gar nicht getestet wurde. Ohne
Umstellung waere das Gatter ab sofort dauerhaft rot gewesen und damit so wertlos
wie vorher dauerhaft gruen. Alle drei Aufrufe laufen jetzt gruppenweise ueber
``tests/GROUPS.txt``; ``--import-mode=importlib`` half nicht, drei nachgeruestete
``__init__.py`` verschlechterten es von 18 auf 54 Fehler (zurueckgenommen).

GEGENPROBE: Vor der Korrektur waren beide Tests oben rot. Danach schlug
``test_kein_testschritt_kann_nicht_fehlschlagen`` erneut an - vier Mal, und alle
vier Male auf **Kommentare**, die gerade erst geschrieben worden waren ("Kein
'|| true' mehr ..."). Der ausfuehrbare Code war sauber. Statt die Begruendungen
zu loeschen wurde der Melder geschaerft (``_nur_ausfuehrbares``) und mit einem
eigenen Wirkungsnachweis versehen. Danach ``tests/spec``: 50 gruen, 0 rot.

WAS DAMIT NICHT BELEGT IST: Geprueft sind der Text und die YAML-Struktur der
Workflow-Dateien, nicht ein echter GitHub-Lauf. Dass der ``test``-Job dort
tatsaechlich anlaeuft und ``build_and_push`` blockiert, zeigt erst der erste
Push. Diese Tests koennen belegen, dass das Gatter *dasteht* - nicht, dass
GitHub es so ausfuehrt.
"""

import re
from pathlib import Path

import pytest

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
PUBLISH = WORKFLOWS / "docker-publish.yml"
TESTS = WORKFLOWS / "tests.yml"


def test_workflow_dateien_sind_vorhanden():
    """Sicherung gegen ein stumpfes Werkzeug.

    Werden die Dateien umbenannt, liefen die Tests unten ins Leere und waeren
    gruen, ohne irgendetwas zu belegen.
    """
    assert PUBLISH.is_file(), f"{PUBLISH} fehlt - der Test unten prueft dann nichts"
    assert TESTS.is_file(), f"{TESTS} fehlt - der Test unten prueft dann nichts"


def test_veroeffentlichung_haengt_an_einem_testlauf():
    """Der Workflow, der das Image veroeffentlicht, darf Tests nicht uebergehen.

    Akzeptiert werden beide ueblichen Formen: ein eigener Testschritt im selben
    Workflow, oder ein ``needs:`` auf einen Job, der Tests ausfuehrt.
    """
    inhalt = PUBLISH.read_text(encoding="utf-8")

    hat_eigenen_testlauf = bool(re.search(r"pytest|python -m pytest", inhalt))
    haengt_an_job = bool(re.search(r"^\s*needs:", inhalt, re.MULTILINE))

    assert hat_eigenen_testlauf or haengt_an_job, (
        "docker-publish.yml fuehrt weder Tests aus noch haengt es an einem Job, "
        "der welche ausfuehrt - Images gehen ungeprueft an die Nutzer"
    )


def test_die_workflow_dateien_sind_gueltiges_yaml():
    """Sicherung gegen ein stumpfes Werkzeug - und gegen mich selbst.

    Die Tests hier lesen den **Text** der Workflow-Dateien. Eine Datei kann
    dabei jede Zusicherung erfuellen und trotzdem kaputt sein: Faellt beim
    Bearbeiten die Einrueckung durcheinander, laedt GitHub sie gar nicht erst,
    der Job laeuft nie, und das Gatter gattert nichts - waehrend die Tests
    unten weiter gruen melden.

    Aufgefallen beim Bau des Gatters selbst: Ich hatte drei Workflow-Dateien von
    Hand geaendert und wollte sie lokal pruefen, aber auf dem Entwicklungsrechner
    fehlt PyYAML. Eine nicht durchgefuehrte Pruefung ist keine bestandene - also
    gehoert sie hierher, wo sie bei jedem Lauf mitlaeuft.
    """
    yaml = pytest.importorskip(
        "yaml", reason="ohne PyYAML kann diese Pruefung nichts belegen"
    )
    for datei in sorted(WORKFLOWS.glob("*.yml")):
        try:
            geladen = yaml.safe_load(datei.read_text(encoding="utf-8"))
        except yaml.YAMLError as fehler:
            pytest.fail(f"{datei.name} ist kein gueltiges YAML: {fehler}")
        assert isinstance(geladen, dict) and geladen.get("jobs"), (
            f"{datei.name} enthaelt keinen jobs-Block - GitHub fuehrt daraus nichts aus"
        )


def test_das_gatter_haengt_wirklich_am_testjob():
    """``needs:`` muss auf einen Job zeigen, der es auch gibt.

    Der Test weiter oben akzeptiert jedes ``needs:``. Ein Verweis auf einen Job,
    den es nicht gibt, waere aber genau die Sorte Gatter, die niemand bemerkt -
    GitHub lehnt den Lauf ab, und im Zweifel merkt man es erst, wenn eine
    Veroeffentlichung ausbleibt oder durchrutscht.
    """
    yaml = pytest.importorskip(
        "yaml", reason="ohne PyYAML kann diese Pruefung nichts belegen"
    )
    inhalt = yaml.safe_load(PUBLISH.read_text(encoding="utf-8"))
    jobs = inhalt["jobs"]
    bauen = jobs.get("build_and_push")
    assert bauen is not None, "docker-publish.yml hat keinen build_and_push-Job mehr"

    haengt_an = bauen.get("needs")
    assert haengt_an, "build_and_push haengt an keinem Job - Images gehen ungeprueft hinaus"
    haengt_an = [haengt_an] if isinstance(haengt_an, str) else list(haengt_an)

    for name in haengt_an:
        assert name in jobs, f"build_and_push braucht Job '{name}', den es nicht gibt"

    laeuft_pytest = any(
        "pytest" in str(schritt.get("run", ""))
        for name in haengt_an
        for schritt in jobs[name].get("steps", [])
    )
    assert laeuft_pytest, (
        "Die Jobs, an denen build_and_push haengt, fuehren selbst kein pytest aus - "
        f"geprueft: {haengt_an}"
    )


def _schritte(inhalt: str):
    """Zerlege einen Workflow in seine ``- name:``-Schritte.

    Noetig, weil ein Testaufruf ueber viele Zeilen gehen kann: in tests.yml steht
    ``python -m pytest`` bei :73 und das zugehoerige ``|| true`` erst bei :80,
    getrennt durch Zeilenfortsetzungen. Eine zeilenweise Suche findet das nicht -
    die erste Fassung dieses Tests uebersah deshalb ausgerechnet den
    Unit-Test-Schritt und meldete nur den Integrationstest.
    """
    schritte, aktuell, start = [], [], 1
    for nr, zeile in enumerate(inhalt.splitlines(), 1):
        if re.match(r"\s*- name:", zeile):
            if aktuell:
                schritte.append((start, "\n".join(aktuell)))
            aktuell, start = [zeile], nr
        else:
            aktuell.append(zeile)
    if aktuell:
        schritte.append((start, "\n".join(aktuell)))
    return schritte


def _nur_ausfuehrbares(block: str) -> str:
    """Wirft GANZE Kommentarzeilen weg - und sonst nichts.

    Warum es das gibt (2026-09-17): Beim Bau des Gatters schlug der Test unten
    vier Mal an, und alle vier Male auf **Kommentare**, die ich selbst gerade
    geschrieben hatte - Saetze wie "Kein '|| true' und kein continue-on-error
    mehr: dieser Schritt IST das Gatter". Der ausfuehrbare Code war sauber.

    Die naheliegende Abhilfe waere gewesen, diese Kommentare zu loeschen. Das
    haette ausgerechnet die Begruendung entfernt, warum die Schutzschalter weg
    sind - ein schlechter Tausch. Der Melder sucht stattdessen jetzt nach
    Bedeutung statt nach Text: Eine Zeile, die mit ``#`` beginnt, wird von der
    Shell nie ausgefuehrt und kann folglich nichts unterdruecken.

    Bewusst NUR ganze Kommentarzeilen: Wuerde ab dem ersten ``#`` abgeschnitten,
    liesse sich ein echter Schalter dahinter verstecken
    (``pytest x || true  # harmlos``). Genau dieser Fall ist unten festgenagelt.
    """
    return "\n".join(z for z in block.splitlines() if not z.lstrip().startswith("#"))


def _schutzschalter(block: str) -> list:
    """Welche Schalter ein Schritt traegt. Leere Liste heisst: kann rot werden."""
    ausfuehrbar = _nur_ausfuehrbares(block)
    gefunden = []
    if "|| true" in ausfuehrbar:
        gefunden.append("'|| true'")
    if re.search(r"continue-on-error:\s*true", ausfuehrbar):
        gefunden.append("continue-on-error: true")
    return gefunden


def test_kein_testschritt_kann_nicht_fehlschlagen():
    """Ein Testschritt, der nicht rot werden kann, ist kein Gatter.

    Zwei Wege fuehren dorthin, und beide zaehlen: ``|| true`` am Aufruf und
    ``continue-on-error: true`` am Schritt. Der zweite fehlte in der ersten
    Fassung dieses Tests vollstaendig.

    Bewusst NICHT angeschlagen wird bei ``|| true`` an Berichtswerkzeugen
    (radon, pylint, flake8, mypy in code-quality.yml). Dort ist es legitim: die
    Werkzeuge liefern einen Bericht, kein Urteil. Ein Test, der auch die meldet,
    erzeugt Fehlalarme und wird deshalb ignoriert - und ein ignorierter Test ist
    so wertlos wie ein gruener. Aus demselben Grund zaehlen seit 2026-09-17
    reine Kommentarzeilen nicht mehr mit; siehe ``_nur_ausfuehrbares``.
    """
    befunde = []
    for datei in sorted(WORKFLOWS.glob("*.yml")):
        for startzeile, block in _schritte(datei.read_text(encoding="utf-8")):
            if "pytest" not in _nur_ausfuehrbares(block):
                continue
            kopf = block.splitlines()[0].strip().removeprefix("- name:").strip()
            for schalter in _schutzschalter(block):
                befunde.append(f"{datei.name}:{startzeile} '{kopf}': pytest mit {schalter}")

    assert not befunde, (
        "Testschritte, die nicht fehlschlagen koennen:\n" + "\n".join(befunde)
    )


def test_der_melder_beisst_nach_der_schaerfung_noch():
    """Wirkungsnachweis fuer ``_nur_ausfuehrbares`` - Pflicht, weil hier ein
    Waechter gelockert aussieht.

    Wer einen Melder entschaerft, damit der eigene Code durchkommt, muss
    belegen, dass er den echten Fall weiterhin faengt. Vier Faelle, und der
    letzte ist der wichtigste: Er verhindert, dass sich die Schaerfung
    missbrauchen laesst.
    """
    echt_true = (
        "      - name: Run tests\n"
        "        run: |\n"
        "          python -m pytest tests/ -q || true\n"
    )
    assert _schutzschalter(echt_true) == ["'|| true'"], "echtes '|| true' nicht erkannt"

    echt_coe = (
        "      - name: Run tests\n"
        "        run: python -m pytest tests/ -q\n"
        "        continue-on-error: true\n"
    )
    assert _schutzschalter(echt_coe) == ["continue-on-error: true"], (
        "echtes continue-on-error nicht erkannt"
    )

    nur_prosa = (
        "      - name: Run tests\n"
        "        run: |\n"
        '          # Kein "|| true" mehr und kein continue-on-error: true hier.\n'
        "          python -m pytest tests/ -q\n"
    )
    assert _schutzschalter(nur_prosa) == [], (
        "Kommentar faelschlich als Schutzschalter gemeldet - genau der Fehlalarm, "
        "wegen dem die Schaerfung noetig war"
    )

    getarnt = (
        "      - name: Run tests\n"
        "        run: |\n"
        "          python -m pytest tests/ -q || true  # sieht harmlos aus\n"
    )
    assert _schutzschalter(getarnt) == ["'|| true'"], (
        "Ein Schalter mit Kommentar dahinter wurde uebersehen - die Schaerfung "
        "waere damit ein Schlupfloch statt einer Praezisierung"
    )


def test_die_schritt_zerlegung_findet_mehrzeilige_aufrufe():
    """Sicherung gegen ein stumpfes Werkzeug.

    Belegt, dass ein ueber Zeilenfortsetzungen verteilter Aufruf als EIN Schritt
    erkannt wird - genau der Fall, den die erste Fassung verfehlt hat.
    """
    beispiel = (
        "      - name: Run unit tests\n"
        "        run: |\n"
        "          python -m pytest tests/unit/ \\\n"
        "            --cov=services \\\n"
        "            -v || true\n"
        "      - name: Upload\n"
        "        run: echo hi\n"
    )
    schritte = _schritte(beispiel)
    assert len(schritte) == 2, f"Zerlegung ergab {len(schritte)} Schritte statt 2"
    erster = schritte[0][1]
    assert "pytest" in erster and "|| true" in erster, (
        "Aufruf und '|| true' landeten nicht im selben Schritt - die Zerlegung "
        "wuerde den Unit-Test-Schritt wieder uebersehen"
    )
