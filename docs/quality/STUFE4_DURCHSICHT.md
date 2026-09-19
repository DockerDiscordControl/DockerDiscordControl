# Stufe 4 — Durchsicht mit nachweisbarer Abdeckung

**Stand:** 2026-09-17 · **Durchsicht durchgeführt. Der Prüfplan bleibt ein Gerüst ohne einen Haken.**

Diese Stufe verlangt fünf Dinge: einen Zuschnitt in Abschnitte von höchstens 2000 Zeilen, einen
Vertragstest über die Abdeckung, einen Prüfplan je Abschnitt, eine Abdeckungsrechnung und eine
Durchsicht mit einem anderen Modell. **Vier davon stehen, eines nicht:** Der Prüfplan ist ein Gerüst
mit 1.513 Namen und keinem einzigen Haken. Ihn zu füllen, ohne die Namen gelesen zu haben, wäre der
„Bericht, wie viel erreicht wurde", den der Programmtext ausdrücklich ablehnt.

---

## 1. Zuschnitt — steht

37 Abschnitte, 190 Stücke, **61.269 von 61.269 Zeilen** in 185 Dateien (`docs/quality/ABSCHNITTE.txt`).
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
| enthalten eine Datei, in der etwas geändert wurde | 33 | 55.790 (91 %) |
| gar nicht berührt | **4** | **5.479 (9 %)** |

Die Rechnung offen, damit sie nachprüfbar ist statt geglaubt: Die vier unberührten Abschnitte
summieren sich gemessen auf 5.479 Zeilen; 61.269 − 5.479 = 55.790.

**Diese Zahl ist inzwischen achtmal veraltet** — 12 Abschnitte mit 17.242 Zeilen, dann 11 mit
15.479, dann 10 mit 14.636, dann 9 mit 14.344, dann 8 mit 12.510, dann 7 mit 10.618, dann 6 mit 8.683, jetzt 4 mit 5.479. Jede Korrektur verschiebt sie: **Abschnitt 13**
fiel mit `config_service.py` heraus, **Abschnitt 20** mit `update_notifier.py`, **Abschnitt 37**
mit `token_security.py`, **Abschnitt 28** mit `configuration_save_service.py`, **Abschnitt 33** mit `app/bot/token.py`, **Abschnitt 22** mit `mech_evolutions.py`, **Abschnitt 07** und **21** mit der Übersetzung ins Englische (`scheduler_commands.py`, `animation_cache_service.py`). Das ist kein Mangel der Rechnung, sondern ihre Natur — und der Grund, sie
am Ende zu messen statt sie mitzuführen.

**Diese 91 % sind keine Abdeckung, und sie dürfen nicht als solche gelesen werden.** „Berührt" heißt:
In diesem Abschnitt liegt eine Datei, in der eine einzelne Zeile geändert wurde. Das ist keine
Durchsicht.

**Ehrlich ist: Kein einziger der 37 Abschnitte wurde systematisch durchgelesen.** Was stattgefunden
hat, waren gezielte Suchen nach benannten Mustern (nackte `except:`, Umgebungslesungen,
zeichengleiche Zwillinge, Aufrufstellen) und punktuelle Korrekturen. Diese Suchen waren mechanisch
und vollständig — aber sie prüfen je eine Frage, nicht den Abschnitt.

### Die vier nie berührten Abschnitte

| Abschnitt | Zeilen | Inhalt |
|---|---|---|
| 08 | 1.341 | `status_handlers.py` |
| 14 | 1.435 | `channel_cleanup_service.py`, `embed_helper_service.py`, `status_overview_service.py`, … |
| 15 | 708 | `docker_client_pool.py` |
| 26 | 1.995 | `scheduler.py` |

Auffällig darunter: **Abschnitt 26** (`scheduler.py` — die dokumentierte Z5-Ausnahme sitzt dort).
Er wurde von einem zweiten Modell gelesen (Punkt 5), aber weiterhin nicht von mir — was dort steht,
stammt aus geprüften Meldungen, nicht aus eigener Lektüre.

**Abschnitt 37** (`token_security.py` — Z9) stand hier bis zur Korrektur der Token-Anzeige
ebenfalls; er ist seitdem berührt. Gelesen habe ich ihn deshalb trotzdem nicht am Stück — berührt
heißt auch hier nur, dass in dieser Datei Zeilen geändert wurden.

**Abschnitt 28** (`configuration_page_service.py`, …) ist seit Commit 16eca1e berührt. Dort habe
ich ihn **nicht** ausgetragen: Die Datei änderte sich ohne Zeilendifferenz, keine Kopfzeile
bewegte sich — und „berührt" hatte ich an den Kopfzeilen abgelesen statt an der Dateiliste des
Diffs. Aufgefallen ist es erst im Folgecommit, als dieselbe Abschnittsnummer eine Kopfzeilenänderung
zeigte. Berichtigt in dem Commit, der `configuration_save_service.py` umstellt.

---

## 5. Durchsicht mit einem anderen Modell — **durchgeführt**

Drei Instanzen eines anderen Modells, je ein Abschnitt, ausgewählt nach „fällt es dem Nutzer auf"
und nie berührt: **13** (Konfigurationsdienst — Z2, Z9, Migration), **26** (`scheduler.py` — die
unbestätigte Z5-Ausnahme), **37** (`token_security.py` — Z9).

**Kein einziger Befund wurde ungeprüft übernommen.** Ein zweites Modell kann genauso danebenliegen
wie das erste; die Durchsicht ist der Anfang der Arbeit, nicht ihr Ende. Das war keine Vorsicht um
der Form willen: Von den gemeldeten Befunden hat **einer der Nachmessung nicht standgehalten**, und
bei zweien stimmte die Sache, aber nicht die Begründung.

### Behoben — je ein Befund, ein Commit, ein voller Lauf

| Commit | Befund |
|---|---|
| `208ae81` | **Ein Lesefehler an der Konfiguration sah aus wie eine Neuinstallation.** `_load_json_file` liefert bei `PermissionError` die Vorgabe, die `web_ui_password_hash: None` trägt — und `app/auth.py:176` öffnet daraufhin `admin`/`setup` hinter 70 Routen. Der Schreibweg war gegen genau diesen Verlust bereits verteidigt (`config_service.py:385-386`), der Leseweg nicht. |
| `9ea946c` | **Derselbe Container war für die einen Aufrufer da und für die anderen weg.** Zwei Leser derselben Dateien, entgegengesetzte Vorgabe bei fehlendem `active`. Der Schlüssel fehlt real: `config_migration_service.py:230` schreibt Alteinträge wortwörtlich, und das Wort `active` kommt dort nicht vor. |
| `4aed2cb` | **Eine Spendenmeldung konnte halb geschrieben auf der Platte landen.** `open(…, "w")` + `json.dump` auf die Datei, die der Bot alle 30 Sekunden pollt — und der Leser **löscht** sie bei ungültigem JSON. Gemessen blieb kein leeres Nichts zurück, sondern ein gültig beginnender, mitten im Schlüssel abgebrochener Datensatz. |

### Widerlegt — und das ist das wichtigste Ergebnis der Durchsicht

**Die gemeldete Sommerzeit-Lücke im Scheduler existiert nicht.** Gemeldet war, dass fünf rohe
`tz.localize(...)` gegen den hauseigenen `_localize`-Helfer stehen und ein Zeitauftrag deshalb in der
Umstellungsnacht eine Stunde daneben feuert. Ich habe den Befund übernommen, präzisiert und von
„zwei" auf fünf Stellen erweitert — und dann gemessen (pytz 2024.2, Europe/Berlin, Übergang
2027-03-28):

```
naiv=02:30   roh=02:30+01:00   norm=03:30+02:00
roh.utc=01:30+00:00            norm.utc=01:30+00:00
```

`normalize` ändert **nicht den Zeitpunkt**, nur seine Beschriftung. `scheduler.py:737` speichert den
Zeitpunkt (`.timestamp()`). Die Aufgabe feuert also korrekt; der Unterschied ist allein in
`strftime`-Ausgaben von Debug-Zeilen sichtbar. Der Helfer existiert laut eigenem Docstring gegen
`replace(...) + timedelta`, nicht gegen `localize` allein — und an den Aufrufstellen wird die
`timedelta` ohnehin auf ein **naives** Datum angewandt. Die Uneinheitlichkeit bleibt eine Stilfrage,
kein Bruch. **Es gibt hier nichts zu korrigieren.**

Hätte ich stur „Test zuerst" gemacht, wäre das Rot ausgeblieben — aber erst nach der Arbeit.

### Ebenfalls weitgehend widerlegt: die Doppelausführung nach einem Neustart

Gemeldet war: Die Docker-Aktion (`scheduler.py:1829`) läuft vor `_persist_executed_task`
(`:1877`); geht der Prozess dazwischen unter, steht der alte `next_run_ts` noch da, und nach dem
Neustart führt `should_run()` den Auftrag ein zweites Mal aus. Ich hatte den Verdacht übernommen
und als ungeprüft vermerkt.

**Der wahrscheinliche Fall ist bereits abgedeckt**, und zwar ausdrücklich:
`scheduler_service.py:392-396` überspringt eine Ausführung, deren Termin schon gelaufen ist
(*„Skip if this occurrence already ran (its reschedule could not be saved)"*), und `:453-454`
vermerkt den Termin **vor** der Ausführung (*„Remember the executed occurrence before execute_task()
moves next_run"*). Scheitert also nur das Speichern, während der Prozess weiterläuft, greift die
Sperre. Gefunden habe ich sie erst spät: Ich hatte nach `running`, `in_progress`, `lock` und
`idempot` gesucht — `_executed_runs` stand in keinem dieser Muster. Wieder nach erwarteten **Namen**
gesucht statt den Weg gelesen.

**Was übrig bleibt, ist vernachlässigbar.** `_executed_runs` ist ein Instanzfeld und nach einem
echten Prozessneustart leer. Es bräuchte also einen Neustart, der *genau* in die Spanne zwischen
Rückkehr der Docker-Aktion und dem Schreiben von `tasks.json` fällt — Millisekunden bis
Zehntelsekunden — und binnen der Nachfrist abgeschlossen ist. Die Nachfrist ist inzwischen gemessen:
`CHECK_INTERVAL = 60`, `MISSED_RUN_GRACE_SECONDS = max(180, 300)` = **300 Sekunden**
(`scheduler_service.py:47,52`); `_service_loop:278-281` fährt beim Start sofort einen Zyklus, ohne
vorher zu schlafen. Die Folge wäre ein zweiter Neustart desselben Containers — ärgerlich, kein
Datenverlust.

**Keine Zusicherung, kein Umbau.** Eine Absicherung verlangte, `_executed_runs` zu persistieren; das
wäre eine neue Zusicherung über Absturzverhalten und damit die Entscheidung des Betreibers. Auf die
Frage „warum soll der Prozess denn abstürzen?" ist die ehrliche Antwort: gar nicht — Neustarts sind
zwar alltäglich (`rebuild.sh`, Unraid-Auto-Update, siehe B7), aber das Fenster ist zu schmal, als
dass sich eine Absicherung lohnte.

### Betreiberfragen — nicht von mir zu entscheiden

1. **Die Sicherheitsanzeige setzte „sichere Quelle wird benutzt" mit „es existiert keine unsichere
   Kopie" gleich — ENTSCHIEDEN UND BEHOBEN (2026-09-18).** War `DISCORD_BOT_TOKEN` gesetzt, kehrte
   `verify_token_encryption_status` sofort zurück; `token_exists` blieb `False`. Folge:
   `security_service.py:265` vergab 40/40 und „✅ Excellent", das Panel zeigte Grün, und
   `auto_encrypt_token_on_startup` (verdrahtet in `app/bootstrap/runtime.py:194`) lief nie an —
   **während ein Klartext-Token in `bot_config.json` liegen konnte.** Das berührte Z9.
   **Entscheidung des Betreibers:** Warnung neben dem Grün, kein Punktabzug. Die Umgebungsvariable
   ist richtig und behält ihre 40/40; zusätzlich meldet die Anzeige nun die Klartext-Kopie. Dass die
   Warnung sichtbar wird, ist geprüft und nicht angenommen: `_token_security_modal.html:181-186`
   rendert die `recommendations`-Liste unter eigener Überschrift.
   **Was dabei NICHT eintrat:** Ich hatte zwei absichtlich geschriebene Tests als Opfer angekündigt
   (`test_crypto_cache.py:272-274`, `test_utils_completion.py:530-534`). Gemessen blieben beide
   grün — ihre Vorrichtungen legen ein leeres Konfigurationsverzeichnis an, dort ändert der
   entfallene Rücksprung nichts. Die Ankündigung war falsch, die Berichtigung davor richtig.
   **Ein Nebeneffekt, der nicht eingebaut wurde:** Ohne Schutz hätte der Code künftig „⚠️ No bot
   token configured" auf einer sauberen Anlage gemeldet, die den Token ausschließlich über die
   Umgebungsvariable bezieht. Diese Meldung erscheint jetzt nur noch, wenn wirklich kein Token da ist.
   *Entlastend war schon vorher:* `/encrypt-token` hängt **nicht** an diesem Status.
2. **`migrate_to_environment_variable` ist tot — und als tot festgeschrieben.** Die Methode liest
   `self.config_manager`, gesetzt wird nur `self.config_service` (`:51-59`). Der `AttributeError`
   wird bei `:247` gefangen, der Betreiber sieht den rohen Python-Text als Fehlermeldung.
   `test_crypto_cache.py:332-340` prüft genau diesen Weg als erwartetes Verhalten;
   `test_utils_completion.py:1133` setzt das fehlende Attribut von außen und prüft damit einen
   Erfolgspfad, den es produktiv nicht gibt — ein Spiegeltest.
3. **Welche `active`-Vorgabe gilt.** Korrigiert wurde auf „fehlt heißt aktiv", weil diese Regel an
   zwei Stellen als Kommentar im Code steht und von zwei Tests festgenagelt ist, während die
   Gegenseite keinen Test hat. Die Wahl selbst gehört dir.
4. **27 Dateien leiten das Konfigurationsverzeichnis eigenständig her** (gemessen, ~44 Stellen).
   `DDC_CONFIG_DIR` beachten davon **sechs** — `container_status_service.py:135` sogar mit
   abweichender Vorgabe (`/app/config`). Drei Stellen fallen auf ein **relatives** `Path("config")`
   zurück, das vom Arbeitsverzeichnis abhängt. Das ist Stufe 2 Punkt 3 in großem Maßstab, aber 27
   Dateien zusammenzulegen ist ein Umbau ohne wartenden Test — deshalb nicht angefasst.
5. **`ScheduledTask` trägt keinen Kanal** (`__slots__`, `scheduler.py:167-172`: 21 Felder, keines
   kanalbezogen). Eine erneute Kanalrechtsprüfung zur Ausführungszeit ist damit für **keinen**
   Zeitauftrag möglich — nicht nur für die dokumentierte Web-UI-Ausnahme. Selbst nachgesehen.

### Kleinbefunde, bewusst tief eingeordnet

- `update_notifier.py:63` schrieb nicht-atomar — **behoben**, siehe unten. `mech_reset_service.py:243`
  hat dieselbe Bauart und bleibt **unkorrigiert**: Die Methode baut ihre Nutzlast selbst, es gibt
  keinen Injektionspunkt von außen, und ein Fehlschlag ließe sich nur durch Attrappieren von
  `json.dump` erzwingen — dann prüfte der Test die Attrappe. Anhalten, wo sich nicht messen lässt,
  was man ändert. Ärgerlich ist der Fall trotzdem: Dieselbe Datei importiert `atomic_write_json` bei
  `:25` und benutzt es zwölf Zeilen vorher bei `:202`, mit ausgeschriebener Begründung — eine
  bewusste Umstellung, bei der eine Schwestermethode übrig blieb.
- **Nebenbei gemessen:** `reset_evolution_mode` hat genau einen Aufrufer (`mech_reset_service.py:106`),
  und dessen **Erfolgsflagge wird nicht ausgewertet** — bei `:107` wandert nur die Meldung in eine
  Liste. Ein gescheiterter Rücksetzvorgang ginge als Teil eines erfolgreichen Gesamtrücksetzens durch.
- `scheduler.py:438-448`: elf unerreichbare Zeilen hinter `return True` (`:436`), wortgleich aus
  `_validate_monthly` kopiert. Harmlos — bis jemand sie „repariert".

---

## 6. Was NICHT geprüft wurde

- **Kein Abschnitt wurde systematisch durchgelesen.** Die 91 % „berührt" sagen darüber nichts.
- **Keiner der 1.513 Namen im Prüfplan ist beurteilt.**
- **Die vier nie berührten Abschnitte** (5.479 Zeilen, 9 % des Baums) sind in diesem Programm
  ausschließlich von den mechanischen Suchen erfasst worden — nicht gelesen. Die Abschnitte 26 und
  37 hat ein zweites Modell gelesen, ich nicht.
- ~~Der Verdacht auf Doppelausführung nach einem Absturz~~ und ~~die unbekannte Poll-Frequenz~~
  standen hier bis zum 2026-09-18. **Beides ist inzwischen gemessen** — Ergebnis unter Punkt 5,
  „Widerlegt".
- ~~Ob `_impl_schedule_*` in `cogs/scheduler_commands.py` erreichbar ist~~ — **geklärt am
  2026-09-18: toter Code.** Die Erweiterungsliste (`app/bot/startup_steps/commands.py:26-30`) lädt
  nur `docker_control`, `auto_action_monitor` und `translation_monitor`; nichts referenziert den
  Mixin. Der lebende Weg für Zeitaufträge aus Discord ist der Knopf bei
  `cogs/status_info_integration.py:2331`. Festgehalten in `SPEC.md` B11.
- **Ob der Zuschnitt sinnvoll ist**, wurde nicht beurteilt. Er ist maschinell erzeugt und erfüllt die
  Grenze; ob die Abschnitte thematisch zusammenhängen, hat niemand geprüft.
