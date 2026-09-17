# Stufe 4 — Durchsicht mit nachweisbarer Abdeckung

**Stand:** 2026-09-17 · **Gerüst steht, Durchsicht steht aus.**

Diese Stufe verlangt fünf Dinge: einen Zuschnitt in Abschnitte von höchstens 2000 Zeilen, einen
Vertragstest über die Abdeckung, einen Prüfplan je Abschnitt, eine Abdeckungsrechnung und eine
Durchsicht mit einem anderen Modell. **Drei davon stehen, zwei nicht.**

---

## 1. Zuschnitt — steht

37 Abschnitte, 188 Stücke, **60.724 von 60.724 Zeilen** in 183 Dateien (`docs/quality/ABSCHNITTE.txt`).
Geschnitten wird an Klassen- und Funktionsgrenzen, nicht willkürlich bei Zeile 2000: Ein Abschnitt
soll am Stück lesbar sein.

Vier Dateien liegen über der Grenze und mussten geteilt werden — `docker_control.py` (5.255),
`control_ui.py` (3.293), `status_info_integration.py` (2.590), `scheduler.py` (2.165).

### Der strukturelle Befund dabei

**`DockerControlCog` ist eine einzige Klasse mit 4.485 Zeilen** — 8,5 % des gesamten
Anwendungscodes. Sie lässt sich nicht an Klassengrenzen teilen, weil sie selbst die Grenze ist; der
Zuschnitt musste **innerhalb** der Klasse an Methodengrenzen schneiden.

Das ist kein Formfehler, sondern die Erklärung für eine Lücke der Stufe 0: Die Bestandsaufnahme hat
diese Datei nur gezielt durchsucht und **nie durchgelesen**. Ein Abschnitt, der aus Methodenrümpfen
einer Klasse besteht, ist nicht dasselbe wie eine lesbare Einheit.

*Nicht behoben.* Eine Klasse dieser Größe zu zerlegen ist ein Umbau am Produktivcode ohne wartenden
Test — genau das, was der Programmtext ausschließt. Es ist eine Entscheidung des Betreibers.

---

## 2. Vertragstest — steht und beißt

`tests/spec/test_stufe4_zuschnitt.py` prüft: jede Quelldatei liegt in **genau einem** Abschnitt,
lückenlos und überschneidungsfrei, kein Abschnitt über 2000 Zeilen.

**Behauptung und Erwartung kommen aus verschiedenen Quellen** — die Behauptung aus `ABSCHNITTE.txt`,
die Erwartung aus dem Dateisystem. Zöge man beides aus der Abschnittsdatei, wäre es ein Spiegeltest;
genau so einer ist beim Verdrahtungstest der Stufe 3 unterlaufen und blieb bei entferntem CSRF-Schutz
grün.

*Wirkungsnachweis*, bei einem von Anfang an grünen Test unverzichtbar — vier Mutationen, jede einzeln:

| Mutation | Ergebnis |
|---|---|
| Datei aus der Liste entfernt | 1 failed |
| Lücke gerissen | 1 failed |
| Abdeckung endet vor dem Dateiende | 1 failed |
| Abschnitt künstlich über 2000 Zeilen | 2 failed |

Wiederhergestellt: 3 grün, Datei bitgleich zur Sicherung.

---

## 3. Prüfplan — Gerüst steht, kein einziger Haken

`docs/quality/PRUEFPLAN.txt` listet je Abschnitt die öffentlichen Namen, die bei einer Durchsicht
einzeln zu beurteilen wären.

Es sind **1.513 Namen** auf 37 Abschnitte, im Schnitt 41 je Abschnitt.

**Der Plan ist eine Aufgabenliste, kein Nachweis.** Kein Haken bedeutet: nicht beurteilt. Ihn mit
1.513 Häkchen zu füllen, ohne die Namen tatsächlich gelesen zu haben, wäre genau der „Bericht, wie
viel erreicht wurde", den der Programmtext ablehnt.

> *Zahl berichtigt noch beim Schreiben:* Hier stand zunächst 840. Das war eine frühere Erhebung, die
> nur Namen **oberster Ebene** zählte; der Prüfplan erfasst zusätzlich die Methoden öffentlicher
> Klassen. Beide Zahlen sind für sich richtig — der Bericht behauptete aber die kleinere über einen
> Plan, der die größere enthält. Achte Zahl dieses Programms aus einer überholten Quelle.

---

## 4. Abdeckungsrechnung — und warum die freundliche Zahl die falsche ist

| | Abschnitte | Zeilen |
|---|---|---|
| enthalten eine Datei, in der etwas geändert wurde | 25 | 43.395 (72 %) |
| gar nicht berührt | **12** | **17.242 (28 %)** |

**Diese 72 % sind keine Abdeckung, und sie dürfen nicht als solche gelesen werden.** „Berührt" heißt:
In diesem Abschnitt liegt eine Datei, in der eine einzelne Zeile geändert wurde. Das ist keine
Durchsicht.

**Ehrlich ist: Kein einziger der 37 Abschnitte wurde systematisch durchgelesen.** Was stattgefunden
hat, waren gezielte Suchen nach benannten Mustern (nackte `except:`, Umgebungslesungen,
zeichengleiche Zwillinge, Aufrufstellen) und punktuelle Korrekturen. Diese Suchen waren mechanisch
und vollständig — aber sie prüfen je eine Frage, nicht den Abschnitt.

### Die zwölf nie berührten Abschnitte

| Abschnitt | Zeilen | Inhalt |
|---|---|---|
| 07 | 1.391 | `enhanced_info_modal_simple.py`, `scheduler_commands.py` |
| 08 | 1.341 | `status_handlers.py` |
| 13 | 1.763 | `config_service.py`, `config_validation_service.py`, `container_config_save_service.py`, … |
| 14 | 1.435 | `channel_cleanup_service.py`, `embed_helper_service.py`, `status_overview_service.py`, … |
| 15 | 708 | `docker_client_pool.py` |
| 20 | 843 | `spam_protection_service.py`, `update_notifier.py`, … |
| 21 | 1.813 | `animation_cache_service.py` |
| 22 | 1.935 | `mech_data_store.py`, `mech_evolutions.py`, … |
| 26 | 1.995 | `scheduler.py` |
| 28 | 1.834 | `translation_service.py`, `configuration_page_service.py`, … |
| 33 | 1.892 | `translation_routes.py`, `performance.py`, `runtime.py`, +21 |
| 37 | 292 | `token_security.py` |

Auffällig darunter: **Abschnitt 13** (der Konfigurationsdienst — Z2, Z9 und der Migrationsbefund
hängen alle daran), **Abschnitt 26** (`scheduler.py` — die dokumentierte Z5-Ausnahme sitzt dort) und
**Abschnitt 37** (`token_security.py` — Z9).

---

## 5. Durchsicht mit einem anderen Modell — **nicht durchgeführt**

Der letzte Punkt der Stufe, und der einzige der fünf Stufen, den ich nicht allein abschließen kann.
Er ist ausdrücklich so gedacht: Ein zweites Modell soll sehen, was das erste übersehen hat.

**Vorschlag für den Zuschnitt des Auftrags** — die drei Abschnitte, die nach „fällt es dem Nutzer
auf" am schwersten wiegen und nie berührt wurden:

1. **Abschnitt 13** — Konfigurationsdienst. Daran hängen Z2 (Testlauf fasst Produktivdaten nicht an),
   Z9 (Token nie im Klartext) und der heute gefundene Migrationsbefund.
2. **Abschnitt 26** — `scheduler.py`. Dort sitzt die dokumentierte Z5-Ausnahme
   („Web UI tasks are admin tasks and always run"), die der Betreiber nie bestätigt hat.
3. **Abschnitt 37** — `token_security.py`, 292 Zeilen, Z9.

---

## 6. Was NICHT geprüft wurde

- **Kein Abschnitt wurde systematisch durchgelesen.** Die 72 % „berührt" sagen darüber nichts.
- **Keiner der 1.513 Namen im Prüfplan ist beurteilt.**
- **Die zwölf nie berührten Abschnitte** (17.242 Zeilen, 28 % des Baums) sind in diesem Programm
  ausschließlich von den mechanischen Suchen erfasst worden — nicht gelesen.
- **Die Durchsicht mit einem zweiten Modell** steht vollständig aus.
- **Ob der Zuschnitt sinnvoll ist**, wurde nicht beurteilt. Er ist maschinell erzeugt und erfüllt die
  Grenze; ob die Abschnitte thematisch zusammenhängen, hat niemand geprüft.
