# Stufe 0 — Bestandsaufnahme DDC

**Stand:** 2026-09-16 · **Geltung:** Commit `bfbda50` auf `develop` · **Am Code wurde nichts geändert.**

Dies ist die Bestandsaufnahme aus Stufe 0 des Qualitätsprogramms. Sie beschreibt, was DDC tut,
wo ein Fehler nicht zurückzunehmen ist, was die 3.962 Tests tatsächlich beweisen — und vor allem,
**was nicht geprüft wurde**. Der letzte Abschnitt ist der wichtigste.

Zwei Grundsätze bestimmen die Einstufung:
**„Unbemerkt schlägt selten"** — eingestuft wird danach, ob der Nutzer es merkt, nicht danach, wie
technisch schwer es klingt. Und: **ein Test, der nicht fehlschlagen kann, ist kein Test.**

---

## 0. Methode und Nachprüfbarkeit

| Erkenntnisquelle | Umfang | Verlässlichkeit |
|---|---|---|
| AST-Zensus der Testsuite | alle 113 Dateien, 3.962 Testfunktionen | **mechanisch**, wiederholbar, kein Modellurteil |
| Testlauf im echten Laufzeitumfeld | 24 Gruppen + 18 einzeln, Wegwerf-Container | **empirisch** |
| Isolationsexperiment | 4 Läufe in beiden Reihenfolgen | **empirisch** |
| Fünf Lesedurchgänge (Cogs, Frontend, Testsemantik, Laufzeit, unwiderrufliche Stellen) | s. Abschnitt 12 | Lesebefunde, stichprobenhaft gegengeprüft |
| Eigene Nachprüfung | ~20 Behauptungen im Quelltext nachgeschlagen | direkt belegt |

Befunde mit **[belegt]** habe ich selbst im Quelltext gesehen. Befunde mit **[gelesen]** stammen aus
einem Lesedurchgang und sind nicht einzeln gegengeprüft.

### Zwei Beobachtungen zur Methode selbst

**Ein Durchgang ist eine Stichprobe, keine Prüfung.** Zwei unabhängige Durchgänge über dieselbe
Frage („wo ist etwas unwiderruflich?") lieferten **deutlich verschiedene Listen**. Der zweite fand
`scheduler.py:1139` (schreibt `"[]"` über eine fehlende Aufgabendatei), `member_count/service.py:174`,
`progress/runtime.py:112` (schreibt die Konfiguration nach einem Lesefehler ohne Sicherung neu) und
die `subprocess`-Aufrufe in `port_diagnostics.py` — der erste keines davon. Umgekehrt hatte der erste
Befunde, die der zweite nicht nannte. Das deckt sich mit der Erwartung aus dem Programm: *paarweise
Schnittmenge nahe null*.

**Auch das mechanische Werkzeug irrt — und das ließ sich zeigen.** Der erste Lauf meldete 92 Tests
ganz ohne Prüfung, darunter sieben in `tests/security/test_security_sast.py`. Die Gegenprobe im
Quelltext zeigte: diese Tests prüfen per `pytest.fail()` innerhalb eines `if`, nicht per `assert`.
Nach der Korrektur des Zählers: 85. Ein zweiter Fehlalarm betraf „Mock-Tautologien": von 12
gemeldeten blieben nach der Korrektur **3**, weil ein einzelner hohler `assert` neben einer echten
Prüfung harmlos ist. Werkzeug und Werkzeugkorrektur liegen im Anhang.

---

## 1. Was DDC ist, und was im schlimmsten Fall passiert

DDC steuert Docker-Container auf einem Unraid-Server aus Discord heraus und bringt dafür ein
Flask-Web-Panel mit. Ein Prozess, zwei Hälften: Web-UI im Daemon-Thread, Bot im Hauptthread
(`run.py:113`). Rund 129.000 Zeilen Python, davon ~63.000 Testcode. Der Container hängt am
Docker-Socket und hat damit faktisch Kontrolle über alle Container des Hosts.

Die vier Schadensarten, sortiert nach „merkt der Nutzer es?":

### A. Falsche Auskunft über Geld — lautlos

Das Spenden-Hauptbuch (`services/mech/progress_service.py`, ein Append-only-Ereignislog) ist die
Aufzeichnung **echter** Ko-fi-Spenden, die von Hand eingetragen werden.

- **Jeder Discord-Nutzer kann beliebige Beträge gutschreiben.** `cogs/docker_control.py:4731`
  (`DonationBroadcastModal.callback`) hat **keine** Prüfung: kein Admin-Check, keine Kanalprüfung,
  keine Sperrzeit. Der Betrag wird nur auf Format und Vorzeichen geprüft (`:4757-4773`), dann bei
  `:4822` ins Hauptbuch geschrieben. **[gelesen]**
- **Schlägt die Buchung fehl, geht die Dankesmeldung trotzdem raus.** `:4885-4887` fängt den Fehler,
  setzt `evolution_occurred = False` — und bei `:4939` wird „X donated Y — thank you so much"
  an jeden konfigurierten Kanal gesendet. **[belegt]**
- **Dieser Weg missachtet die Opt-out-Einstellung.** Der Broadcast bei `:4939` läuft über *alle*
  Einträge in `channel_permissions`. Der parallele Weg im Benachrichtigungs-Task prüft dagegen
  sehr wohl `channel_info.get('donation_broadcasts', True)` (`:5165`). Zwei Wege, dieselbe Aufgabe,
  eine Regel nur an einer Stelle. **[belegt]**

### B. Datenverlust, unwiederbringlich

- `POST /api/donation/reset-power` trunciert das Ereignislog auf leer:
  `event_log.write_text("")` (`services/donation/unified/reset.py:96`). Kein Backup, kein
  Trockenlauf, keine serverseitige Rückfrage — während die Konfigurationsspeicherung daneben brav
  ein `.bak` anlegt. **[belegt]**
- **Die Testsuite selbst kann echte Daten zerstören.** `MechResetService.__init__`
  (`services/mech/mech_reset_service.py:42-45`) löst `config_dir="config"` gegen die Projektwurzel
  auf und **ignoriert `DDC_CONFIG_DIR`**. `tests/unit/services/mech/test_mech_data_services.py:944`
  ruft `quick_mech_reset()` und ersetzt dabei *nur* `reset_all_donations`; `reset_mech_state()`,
  `reset_evolution_mode()` und `cleanup_deprecated_files()` laufen scharf gegen das echte
  `config/`. Dass in unseren Läufen nichts passiert ist, liegt allein daran, dass `ddc_test.sh`
  ein leeres Verzeichnis über `/app/config` mountet. Wer `scripts/run_tests_unraid.sh` oder
  `run_tests.sh` benutzt, hat diesen Schutz nicht. **[belegt]**

### C. Fremdzugriff auf die Container

Die Autorisierung auf der Discord-Seite ist **kanal-, nicht nutzergebunden** — siehe Abschnitt 4.

### D. Kosten

Kein Zahlungsdienstleister, kein SMTP; Ko-fi/PayPal sind reine Links. Echte Außenkosten entstehen
nur über die Übersetzungs-APIs (DeepL/Google/Microsoft). Dort gilt: der Bot-Pfad
(`services/translation/translation_service.py:474`, ausgelöst von jeder passenden Discord-Nachricht)
hat **keine Ausgabenobergrenze und kein Ratenlimit** — jede Nachricht kostet. **[gelesen]**

---

## 2. Wo Logik liegt und wo nur Verdrahtung

| Bereich | Zeilen | Einordnung |
|---|---|---|
| `services/` | ~60.800 | **Die Logik.** Konfiguration, Scheduler, Spenden/Mech, Docker, Übersetzung. |
| `cogs/` | ~15.500 | **Gemischt — das Kernproblem.** `docker_control.py` 5.216 Zeilen/97 Funktionen; `control_ui.py` 3.316; `status_info_integration.py` 2.633. **Berechtigungsentscheidungen liegen hier, nicht in `services/`.** |
| `app/blueprints/` | ~3.200 | Überwiegend Verdrahtung (81 Routen), aber `main_routes.py` trägt Logik in den Routen (u.a. einen nackten Daemon-Thread ab `:806`). |
| `app/web/`, `app/bot/` | ~1.400 | Saubere Verdrahtung in kleinen Dateien. Der am besten geschnittene Teil des Projekts. |
| `utils/` | ~3.300 | Logik-Helfer (Zeit, Krypto, Konfig-Cache, Observability). |
| `scripts/` | 51 Dateien | Betreiber-Werkzeuge, ungetestet, schreiben Konfiguration überwiegend **nicht-atomar**. |

---

## 3. Die Testsuite in Zahlen

**Empirisch, im echten Laufzeitumfeld** (Wegwerf-Container aus dem Produktionsimage,
`scripts/ddc_test.sh`, 24 Gruppen + 18 einzeln):

> **4.492 Tests grün. Null Fehlschläge. Zwei übersprungen.**

Das ist ein echtes Ergebnis und ein gutes. Es sagt allerdings nichts darüber, was diese Tests
beweisen. Dafür der Zensus:

| Kategorie | Anzahl | Anteil |
|---|---:|---:|
| prüft etwas | 3.563 | 89,3 % |
| **nur hohle Prüfungen** (`is not None`, `isinstance`, `len`, `x == x`) | **265** | 6,6 % |
| **gar keine Prüfung** | **85** | 2,1 % |
| nur über `mock.assert_*` | 65 | 1,6 % |
| Mock-Tautologie | 3 | 0,1 % |
| übersprungen | 6 | 0,2 % |
| `pytest.raises(Exception)` — fängt alles | 3 | 0,1 % |

**Hohl insgesamt: 362 von 3.962 (9,1 %).** Davon **134 allein in `tests/unit/extended/`** — dem
Verzeichnis, das sich in `test_app_utils_extended.py:10` selbst als Arbeit am Abdeckungsgrad
beschreibt. Nur 10 der 362 liegen in `tests/unit/audit_2026_09/`.

> **Korrektur, nachgetragen 2026-09-16.** Hier standen bis eben 356 von 3.990 (8,9 %) und „nur 6".
> Diese Zahlen waren falsch, und der Weg dorthin gehört in diesen Bericht: Ich habe den Zensus laufen
> lassen, die Zahlen vom Schirm in dieses Dokument geschrieben (21:41), danach das Zählwerkzeug noch
> **zweimal repariert** — `pytest.fail()` wurde nicht als Prüfung erkannt (92→85), und ein hohler
> `assert` neben einem echten stufte den ganzen Test als Tautologie ein (12→3) — und die endgültige
> Messung um 21:46 abgelegt, ohne das Dokument nachzuziehen. Gemessen waren die alten Zahlen also,
> aber nicht von dem Werkzeug, das am Ende dasteht. Maßgeblich ist allein `test_audit.json` (21:46);
> dessen Kategoriesumme geht exakt auf 3.962 auf. Dieselbe Form von Fehler — einmal messen, danach
> zitieren, obwohl sich das Gemessene geändert hat — ist mir heute ein zweites Mal unterlaufen.

**Eine eigene Gattung unter den hohlen Tests: „soll nicht werfen" (2026-09-16).**
Von den 362 Befunden sitzen 45 in Geld-, Lösch- oder Rechte-Nähe; 7 davon sind `no_verification`,
enthalten also **keine einzige Zusicherung**. Fast alle heißen `*_swallows_*`, `*_handles_bad_*`
oder `*_is_caught`. Drei sind vollständig gelesen:
`test_handle_donation_event_swallows_bad_payload`, `test_log_security_action_swallows_runtime_error`,
`test_rotation_swallows_oserror`. Ihr gesamter Rumpf ist: Funktion aufrufen, sie soll nicht werfen.

Sie sind **nicht** „Tests, die nicht fehlschlagen können" im strengen Sinn — wirft der Code, gibt es
einen Fehler. Sie nageln aber ausschließlich fest, dass nichts fliegt, und nie, ob das Wegräumen das
**Richtige** getan hat: ob die Warnung wirklich geschrieben wurde, ob der Zustand danach heil ist.
Bei `test_rotation_swallows_oserror` steht im Kommentar „the helper logs the error and returns" —
das Loggen wird nicht geprüft. Ein Kommentar, der mehr behauptet als sein Code.

*Der lehrreiche Teil geht gegen mich:* Ich habe diese drei zweimal nach Schwere geordnet und lag
**beide Male falsch**, weil ich aus dem Namen schloss statt die Stelle zu lesen. Erst galt mir
`_log_security_action` als die teuerste („die Sicherheitsspur hört still auf mitzuschreiben") —
tatsächlich fängt sie nur `RuntimeError` und schreibt eine Warnung (`security_service.py:326`).
Dann galt die Logdrehung als der eigentliche Fall („Sicherungen halb verschoben") — tatsächlich
hängt der Aufrufer nicht daran, es gehen keine Einträge verloren, es kann höchstens eine Sicherung
überschrieben werden (`action_log_service.py:271`, `:280`).

**Ergebnis: keine der drei Code-Stellen rechtfertigt einen Eingriff.** Der Befund sind die Tests,
nicht der Code — und er gehört damit nach Stufe 3 (berichten, nichts ohne Einverständnis löschen),
nicht nach Stufe 2. Die Ordnung nach „fällt es dem Nutzer auf" lässt sich aus Bezeichnern nicht
gewinnen; ich habe es an einem Tag zweimal trotzdem versucht.

Die Gründe der 265 hohlen Prüfungen: 203× `is (not) None`, 46× nur `isinstance()`, 19× nur `len()`,
5× `x == x`, 3× nur `callable()`, 2× nur `hasattr()`, 1× Konstante.

### Die Kategorie „nur `mock.assert_*`" ist ein *Vorzug*

Die 65 Tests dieser Kategorie prüfen `assert_not_called()`, `assert_awaited_once_with(...)`,
`defer` vor der Antwort. Das ist **Prüfung der Aufrufstelle** — genau das, was am häufigsten fehlt.
Beispiele: `test_pkg_b_control_ui.py:126` (`interaction.response.defer.assert_awaited_once_with`),
`test_pkg_b_docker_control.py:72` (`bulk_fetch_container_status.assert_not_awaited`). **[belegt]**

### Einzelbefunde mit Zeile

- **Sechs Tests, die `run.py` spiegeln.** `tests/unit/performance/test_bundle4_7_performance.py:388-437`
  baut die Thread-Berechnung aus `run.py:57-62` im Test nach; der Docstring bei `:391` gibt es zu
  („We replicate the logic exactly"). **`run.py` könnte gelöscht werden und alle sechs blieben grün.**
- **`test_services_gaps.py:3328`** — `state = svc.tick_decay(); assert state is not None`. Der
  Verfall des Guthabens ist der ganze Zweck der Funktion und wird nicht geprüft.
- **`test_container_info_service.py:329`** — heißt `test_input_sanitization`, schickt
  `<script>alert('xss')</script>` hinein und prüft, dass *irgendein* Ergebnisobjekt zurückkam.
- **`test_utils_completion.py:638,644,650`** — `assert ok in (True, False)`. Reine Tautologie.
- **`test_utils_completion.py:670`** — `assert any(...) or True`.
- **`test_docker_pool_fetch.py:900`** — vergleicht zwei Ausnahme-Instanzen, die nie gleich sein
  können; der Test kann nicht fehlschlagen.
- **`test_query_failure_demotion.py`** (12 Stellen) — schleift `range(QUERY_FAILURE_DEMOTE_THRESHOLD)`,
  ohne den Schwellwert je festzunageln. Ändert man ihn auf 99, bleibt alles grün.
- **`test_r2_g4_status.py:248-275`** — baut Einträge bei `STATUS_CACHE_MAX_RENDER_AGE_SECONDS ± 30`,
  aber **kein Test hält die 60 Sekunden fest**. Ein Wechsel auf 3600 fällt niemandem auf.

### 306 Tests hängen an einer einzigen Konfigurationszeile

`pytest.ini:65` setzt `asyncio_mode = auto`. **562 asynchrone Testfunktionen existieren, 306 davon
tragen keinen `@pytest.mark.asyncio`.** Ohne diese Zeile würden sie zu nie erwarteten Koroutinen —
und eine nie erwartete Koroutine lässt den Test **bestehen**, nicht scheitern. Der Verlust wäre
also unsichtbar: 306 Tests würden weiterhin grün melden, ohne je etwas auszuführen. **[belegt]**

### Weitere Nachträge

- **Ein fehlendes bandit überspringt den Sicherheitsscan lautlos.**
  `tests/security/test_security_sast.py:57-70` fängt `TimeoutExpired`, `FileNotFoundError` und
  fremde Rückgabewerte jeweils mit `pytest.skip`. Die Wächter sind für sich legitim, und
  `returncode == 0` heißt korrekt „nichts gefunden" — aber ist das Werkzeug nicht installiert,
  meldet der Lauf „übersprungen" statt „ungeprüft". **[belegt]**
- **`tests/unit/extended/test_docker_infra_gaps.py:466` und `:591`** prüfen auf
  `status == "error_processing"` — und die Kommentare daneben bezeichnen genau das als
  Produktionsfehler. Der Test **friert den Fehler als Sollverhalten ein**. **[gelesen]**
- **Toter Ballast:** `tests/load/locustfile.py` zielt auf `/login`, `/dashboard`, `/containers`,
  `/api/status` — **keine davon ist eine registrierte Route**; gesammelt wird die Datei ohnehin nie.
  Von `tests/security/security_test_helpers.py` wird nur `scan_for_patterns` benutzt; neun weitere
  Funktionen sind im ganzen Baum ungenutzt. **[gelesen]**

### Reihenfolge-Abhängigkeit: Verdacht empirisch entkräftet, Struktur bleibt riskant

`tests/unit/services/scheduler/test_scheduler_service.py:26` löscht beim Import *jeden*
`docker*`-Eintrag aus `sys.modules` und baut das Modul neu. Zwei andere Dateien haben deshalb
Umwege eingebaut und schreiben den Grund hin (`test_docker_pool_fetch.py:58-63`).

**Experiment:** 45 Tests allein · 9 allein · **54 gemeinsam in beiden Reihenfolgen.**
Kein Unterschied. Der Verdacht ist für dieses Paar **nicht reproduzierbar** — die Umgehungen wirken.
Die strukturelle Gefahr bleibt bestehen, der konkrete Vorwurf nicht.

### Was dagegen wirklich prozessweit wirkt

- **`dataclasses.dataclass` wird beim Import dauerhaft ersetzt**, in sechs Dateien
  (`test_blueprint_gaps.py:30-42` und gleichlautend in `test_main_automation_security_routes.py`,
  `test_services_gaps.py`, `test_coverage_push_v3.py`, `test_utils_gaps.py`,
  `test_app_utils_extended.py`). Der Ersatz entfernt `slots=` und wird **nie zurückgenommen**; eine
  Versionsprüfung findet nicht statt, nur ein Einmal-Wächter. Sobald eine dieser Dateien gesammelt
  wird, entstehen die acht produktiven `slots=True`-Dataclasses für den Rest des Laufs **ohne
  Slots**. Ironie am Rande: der Docstring derselben Datei mahnt bei `:25` „NEVER manipulate
  `sys.modules` here". **[belegt]**
- **`tests/conftest.py:168-173`** — die autouse-Fixture `cleanup_after_test` hat einen **leeren
  Rumpf**. Mehrere Dateien verlassen sich darauf, dass „automatisch aufgeräumt" wird. Es wird nicht.
- **`tests/conftest.py:26-56`** setzt `TESTING`, `DDC_LOG_LEVEL` und drei Temp-Verzeichnisse
  prozessweit beim Import, ohne Fixture und ohne Aufräumen. Diese Umleitung ist das Einzige, was
  Tests mit echten Singletons von der Live-Installation fernhält — und `MechResetService` umgeht
  sie (Abschnitt 1.B).

### Übersprungene Tests, die niemand vermisst

- `tests/unit/utils/test_utils_completion.py:381` — überspringt **immer**: OpenTelemetry ist in
  `requirements-test.txt:70-74` auskommentiert.
- Vier Tests mit `skipif(geteuid() == 0)` (`test_pkg_c2_services.py:110`, `test_pkg_c2_config.py:218`,
  `test_r2_g3_startup.py:352`, `test_pkg_f_utils.py:136`) verschwinden lautlos, sobald die Suite als
  root läuft. Dass `ddc_test.sh` mit `-u ddc` startet, ist das, was sie am Leben hält.
- `test_bundle5_8_infra.py` nutzt viermal `importorskip("flask_wtf")` ohne Begründung — fehlt
  Flask-WTF, verschwinden genau die vier CSRF-Tests, also unter exakt der Bedingung, unter der
  CSRF projektweit ausfällt.
- Der Modul-Skip in `tests/unit/extended/test_bot_startup.py:59` (74 Tests) greift **nur unter
  Python 3.10**; die Laufzeit ist 3.14. **Harmlos — Verdacht zurückgezogen.** **[belegt]**

---

## 4. Die Berechtigungslandkarte

Auf der Discord-Seite gibt es keine nutzerbezogene Autorisierung — geprüft wird der *Kanal*, über
`_channel_has_permission` (`cogs/control_helpers.py:95`).

> **Vom Betreiber bestätigt (2026-09-16): Das ist so gewollt.** Ein Control-Kanal erteilt allen
> Mitgliedern dieses Kanals die Steuerung; wer im Control-Kanal ist, *ist* Admin. Die
> Zugangskontrolle liegt damit bei Discord (wer den Kanal sehen darf), nicht bei DDC. Das gehört
> als bewusste Entscheidung in die SPEC, sonst „repariert" es der nächste Umbau.
>
> **Auch die globale Admin-Liste ist gewollt — und ihr Zweck ist der *Status*-Kanal.** Vom
> Betreiber bestätigt (2026-09-16): `/addadmin` existiert vor allem, damit Admins dort etwas
> dürfen, wo die Kanalmitgliedschaft allein nichts erlaubt. Dass das Recht die Mitgliedschaft
> überdauert, ist akzeptiert. Geprüft wird die Liste an genau vier Stellen:
> `docker_control.py:2034` (Admins aus einem Status-Kanal ernennen), `control_ui.py:995-998`
> (umgeht die Kanalprüfung für Container-Infos), `control_ui.py:1769` (AdminButton) und
> `admin_overview.py:190,264` (Stop-All / Restart-All).
>
> **Neu offen:** `/donate` und sein Modal haben **gar keine Kanalprüfung**
> (`docker_control.py:2137-2162` — nur `defer`, Spenden-abgeschaltet-Prüfung, Spam-Schutz). Das
> Gutschreiben im Spendenbuch ist damit **nicht** auf Control-Kanäle beschränkt, sondern überall
> möglich, wo der Bot Slash-Befehle anbietet. Das ist eine eigene Frage, unabhängig vom Kanalmodell.

| Stelle | Wirkung | Prüfung |
|---|---|---|
| `cogs/control_ui.py:263` `ActionButton` | **Container start/stop/restart** | Sperrzeit, Kanalrecht `control` (`:304`), `allowed_actions` (`:310`). **Kein Nutzer-Check.** **[belegt]** |
| `cogs/docker_control.py:1931` `/control` | öffnet das Admin-Panel | nur Kanalrecht. **Kein Admin-Check.** |
| `cogs/docker_control.py:2014` `/addadmin` | trägt einen Admin ein (`:5053`) | im Control-Kanal ein wörtliches `pass` mit dem Kommentar „any user in control channel can add admins" (`:2026-2029`). **[belegt]** |
| `cogs/docker_control.py:4731` Spenden-Modal | Hauptbuch + Broadcast | **gar nichts** |
| `cogs/status_info_integration.py:2567` | **löscht eine geplante Aufgabe** (`:2585`) | **gar nichts** — während derselbe Vorgang in `control_ui.py:1236` das Kanalrecht `schedule` prüft (`:1269`). **[belegt]** |
| `cogs/control_ui.py:1932` `AdminContainerDropdown` | baut ein Steuerpanel und setzt `channel_has_control_permission=True` fest (`:2014`) | **keine erneute Admin-Prüfung** |
| `cogs/auto_action_monitor.py:66` | reicht **jede Nachricht in jedem Kanal** an die Regel-Engine | nur was die Regel selbst einschränkt |
| `cogs/scheduler_commands.py:166-181` | legt eine geplante Aufgabe an | prüft nur, ob der *Container* die Aktion erlaubt — nicht, wer plant |

Verschärfend: **das Kanalrecht wird viermal per Textvergleich am Einbettungstitel umgangen**
(`"Admin Control" in embed_title`, `control_ui.py:298-301, 424-429, 1019-1022, 1071-1075`) — eine
autorisierungsrelevante Heuristik auf einer Anzeigezeichenkette. Und es gibt **zwei verschiedene
Definitionen** von „Control-Kanal": `_channel_has_permission(..., 'control')` überall, aber
`control_ui.py:1572` prüft stattdessen `allow_start or allow_stop` — Schlüssel, die die erste
Funktion nie liest. Beide können einander widersprechen.

Nur **eine** Komponente prüft echte Admin-Rechte: `control_ui.py:1749` `AdminButton` (`:1769`).

**Auf der Web-Seite** ist das Bild deutlich besser: 81 Routen, CSRF projektweit ohne Ausnahme,
Ratenlimit. Ohne Anmeldung erreichbar sind nur `POST /setup` (verweigert korrekt, wenn schon ein
Hash existiert; eigener 5/min-Deckel), `POST /api/donation/click` (schreibt mit
angreiferkontrolliertem `X-Forwarded-For` ins Protokoll), `GET /api/donation/status` (ausdrücklich
vom Ratenlimit ausgenommen, `app/auth.py:146`) und fünf lesende Mech-Endpunkte. **[belegt]**

---

## 5. Unwiderrufliche Stellen

**Container anfassen** — erfreulich eng: nur `start`/`stop`/`restart`, zwei Implementierungen
(`docker_action_service.py:168`, `docker_utils.py:629`). **Kein `kill`, kein `remove`, kein `prune`.**
Das ist eine echte Eigenschaft, die festgehalten gehört, bevor sie jemand aufweicht.

Beim Scheduler gilt: die Nachprüfung der erlaubten Aktion läuft **nur für in Discord angelegte
Aufgaben** (`scheduler.py:1796`). Web-UI-Aufgaben laufen ungeprüft. Die Begründung steht im Code
(`:1665-1671`) und ist nachvollziehbar; die Folge steht nirgends. **[belegt]**

**Daten löschen/überschreiben:** Spenden-Reset (oben), Mech-Reset
(`mech_reset_service.py:176` — als einzige Stelle **nicht atomar**), Aktionsprotokoll leeren
(`action_log_routes.py:95` — löscht ausgerechnet die Aufzeichnung darüber, wer die anderen
unwiderruflichen Dinge getan hat), Passwortwechsel (`config_service.py:563-579` — schlägt die
Entschlüsselung vorher fehl, ist der Bot-Token dauerhaft unlesbar), Flask-Schlüssel
(`app/web/config.py:108` — entwertet alle Sitzungen). Nicht-atomar schreiben außerdem:
`server_order.py:45`, `member_count/service.py:174`, `progress_service.py:264`,
`container_status_service.py:153`.

**Nach außen:** Discord-Nachrichten löschen (nicht rückholbar; `channel_cleanup_service.py:318`,
mit 50er-Sicherheitsdeckel), ~411 Sende-/Editierstellen, Spenden-Broadcasts, Heartbeat-GET an eine
frei konfigurierbare URL (HTTPS erzwungen, `docker_control.py:3596`), Übersetzungs-APIs mit
SSRF-Erlaubnisliste, opengsq-Anfragen an beliebige Spielserver.

---

## 6. Wo etwas lautlos verschwindet

Das ist der Vorrat für Stufe 2.

- **25 nackte `except:`** in `cogs/docker_control.py` (17) und `cogs/status_info_integration.py` (8);
  **33 im ganzen Projekt** (dazu 7 in `services/`, 1 in `utils/`, 0 in `app/`).
  *Korrektur 2026-09-16:* Hier stand 18. Die Zahl war nie ausgezählt. Beim Berichtigen habe ich sie
  zuerst als 26 angegeben und dabei meine eigene frisch erzeugte Liste falsch gezählt — maßgeblich
  ist die Auszählung, nicht der Überschlag.
  *Nach Wirkung sortiert, nicht nach Datei* (2026-09-16 alle 25 gesichtet):
  **23 sind Breite, kein Verhalten.** Sie sitzen um Discord-Interaktionen (`followup`, `edit`,
  `delete`) und enden auf `pass` oder `return`; die Kommentare sagen durchweg dasselbe —
  „Interaction already expired". Das ist gewollte Bauart: Discord-Interaktionen verfallen nach drei
  Sekunden, daran ist nichts zu retten. Falsch ist allein, dass `except:` auch `KeyboardInterrupt`
  und `SystemExit` fängt. Billig zu beheben, kein Verhaltensrisiko.
  **2 sind inhaltlich** — und beide fallen nach der Regel „unbemerkt schlägt selten" ausdrücklich
  **nach hinten**, weil man sie sieht:
  `docker_control.py:2198` umschließt neben dem Senden auch `view.message = …` und
  `asyncio.create_task(…)`, also Zeilen **nach** dem erfolgreichen Versand. Wirft eine davon
  (`create_task` wirft `RuntimeError` ohne laufende Schleife), ist die Spendennachricht bereits
  draußen und der Ersatzpfad schickt eine **zweite** hinterher; das nackte `except:` fängt zudem
  `CancelledError`, also auch beim Herunterfahren. `:2252` hat dieselbe Form, aber ein enger
  gefasstes `try` — dort scheitert der Ersatz mit, und der Fehler läuft sichtbar ins Protokoll.
  Zwei davon löschen Discord-Nachrichten (`docker_control.py:4966`, `:4976`) — ein
  unwiderruflicher Vorgang in einem Sammelfang. **[gelesen]**
- **`docker_control.py:3289-3290`** — `except: donations_disabled = False`. **Fällt offen auf.**
  Zusätzlich existiert `_handle_donate_interaction` **zweimal** (`:2204` und `:3268`); die zweite
  überschreibt die erste. Die tote Fassung prüfte den Schlüssel über `is_donations_disabled()`
  (mit Validierung), die lebende prüft bei `:3288` nur, ob überhaupt etwas gesetzt ist. **[belegt]**
- **`docker_control.py:331-334`** — bei einem Fehler des ConfigService wird stillschweigend die
  Konfiguration vom Prozessstart weitergereicht, samt veralteter Kanalrechte und Admin-Liste.
- **`docker_control.py:1490-1492`** — `finally: self.initial_messages_sent = True`. Auch ein
  vollständig fehlgeschlagener Startlauf setzt die Erledigt-Markierung.
- **`control_ui.py:281-283`** — schlägt der Spam-Schutz fehl, wird die Aktion **trotzdem
  ausgeführt**, nur ohne Sperrzeiteintrag.
- **`control_ui.py:604-608`** — die gesamte Docker-Aktion in einem Sammelfang: der Nutzer sieht
  „Pending", dann „Processing…" und erfährt nie, dass Start/Stop fehlgeschlagen ist.
- **`status_info_integration.py:616-644`** — Validierungs- und Docker-Fehler werden **als
  Logtext zurückgegeben** und im Protokoll-Embed angezeigt; ein Fehler ist von Inhalt nicht zu
  unterscheiden.
- **`status_info_integration.py:2461-2480`** — `should_show_info_in_status_channel` berechnet
  `has_control` und gibt dann bedingungslos `True` zurück. Die Prüfung ist tot.
- **`control_ui.py:932-941`** — `_channel_has_info_permission` gibt **immer** `True` zurück.
- **Die Klick-Sperre funktioniert weitgehend nicht:** `getattr(self, f'_last_click_{user_id}', 0)`
  speichert auf der *Button-Instanz* (`control_ui.py:1416, 2093, 2292, 2390, 2520`), und diese
  Objekte werden bei jedem Rendern neu erzeugt.
- **`event_manager.py:78`** fängt **nur `RuntimeError`**. Jede andere Ausnahme eines Handlers
  reißt `emit_event` ab und **alle danach registrierten Handler laufen nicht mehr**. Der Versand
  ist synchron auf dem Thread des Aufrufers, ohne Sperren, ohne Reihenfolgenschutz — und
  `mech_status_cache_service.py:365` sendet aus einem Handler heraus ein weiteres Ereignis. **[belegt]**

---

## 7. Dieselbe Regel an zwei Stellen

27 Fälle wurden benannt; die folgenschwersten:

1. **Spenden-Broadcast zweimal** (`docker_control.py:4889-4946` und `:5131-5181`) — nur der zweite
   beachtet `donation_broadcasts`.
2. **Aufgaben-Löschbutton zweimal** — `control_ui.py:1236` (prüft `schedule`) und
   `status_info_integration.py:2567` (prüft nichts).
3. **Zwei widersprüchliche Frischeregeln:** `STATUS_CACHE_MAX_RENDER_AGE_SECONDS = 60`
   (`docker_control.py:72`) gegen `DDC_DOCKER_MAX_CACHE_AGE = 300` (`:2476`, `:2865`, `:3057`).
   Ein 90 Sekunden alter Eintrag ist „alt genug zum Nachladen", aber „frisch genug zum Anzeigen".
4. **Serverreihenfolge auf vier Arten** implementiert; **Mech-Geschwindigkeit dreimal**;
   **Ablauf der Wartemarkierung (120 s) dreimal** (`:2510`, `:2899`, `:3091`).
5. `_validate_custom_address` ist in `control_ui.py:1173` und `status_info_integration.py:1016`
   **identisch**; `_get_container_logs` in `status_info_integration.py:608` und `:777` ebenfalls.

Zum Gegenbeispiel: die Spielerzahl-Formatierung *ist* zentralisiert
(`services/discord/embed_helper_service.py:21,34`) und wird an drei Stellen benutzt. Es geht also.

---

## 8. Laufzeit, Auslieferung, CI

- **Das Image hat kein `USER`.** Der Prozess startet als **root** und gibt die Rechte erst im
  Entrypoint per `su-exec` an `ddc` ab (`scripts/entrypoint.sh:624`). `PUID=0` ist erlaubt und
  erzeugt nur eine Warnung. **[belegt]**
- **Der Docker-Socket wird widersprüchlich dokumentiert:** `docker-compose.yml:14` sagt `:ro`, die
  Unraid-Vorlage `Mode="rw"`, `docs/UNRAID.md` „READ/WRITE required", `scripts/rebuild.sh:127`
  (der tatsächliche Auslieferungsweg) mountet rw. Anmerkung: `:ro` auf einem Unix-Socket ist
  ohnehin keine Schutzgrenze für die Docker-API — `docs/SECURITY_WIKI.md:137` überzeichnet das.
- **Die CI hat kein Testgatter.** Nirgends in `.github/` steht `--cov-fail-under`.
  `tests.yml:80` und `:127` enden auf `|| true`, `:131` und `:190` setzen `continue-on-error: true`.
  **`docker-publish.yml` führt überhaupt keine Tests aus** — Images werden ohne jede Testprüfung
  veröffentlicht. `pytest.ini:47-50` schreibt vor, dass Vollläufe `--cov-fail-under=50` anhängen
  „sollten"; nichts tut es. **[belegt]**
- **Nur `scripts/ddc_test.sh` ist sicher.** Wegwerf-Container, leere Temp-Verzeichnisse über
  `config/` und `logs/`, Speicher-/PID-/CPU-Grenzen, Zeitlimit, `-u ddc`. **Alle anderen Runner
  fassen die Produktion an:** `run_tests_docker.sh` und `test_in_docker.sh` führen `docker exec` in
  den **laufenden Produktionscontainer** aus und installieren dort pip-Pakete;
  `install_pytest_docker.sh:47` fällt dabei auf `--user root` zurück; `run_tests_unraid.sh` läuft
  direkt auf dem Host gegen das echte `./config`; `test_container_save.sh` macht `git pull` +
  `rebuild.sh`. **[gelesen]**
- **`scripts/` schreibt Konfiguration durchweg nicht-atomar**, ohne Sicherung. Besonders:
  `scripts/test_order_change.py` trägt einen **fest verdrahteten Mac-Pfad**
  (`/Volumes/appdata/dockerdiscordcontrol/config/containers`) und schreibt dort echte Daten
  (`:45-48`). `encrypt_mech_images.py:96` löscht Original-Grafiken, bevor der abhängige Schreibvorgang
  bei `:251` als gelungen feststeht. **[belegt für `test_order_change.py`]**

---

## 9. Das Frontend

34 eigene Dateien (5 JS + 28 Templates + 1 Fremdbibliothek), alle gelesen.

- **Fünf zerstörende Endpunkte haben keinen einzigen Aufrufer im Frontend:**
  `POST /api/donation/reset-power`, `POST /api/mech/reset`, `POST /api/donation/add-power`,
  `POST /clear-action-log`, `POST /clear_logs`. Sie sind nur per direktem HTTP erreichbar.
- **Die Oberfläche meldet einen Erfolg, den es nicht gibt.** Der rote „Clear"-Knopf ruft
  `window.clearLogs` (`_scripts.html:1836-1862`): fragt nach, leert **nur das DOM** und zeigt
  „`${logType} logs cleared successfully`". Es wird **nie** eine Anfrage gesendet. Der Kommentar bei
  `:1844` gibt es zu — „can be updated when backend endpoint is available". Der Endpunkt existiert.
  Das ist „ein Erfolg ist geraten" in Reinform. **[belegt]**
- **Admin-Rechte ändern sich ohne Rückfrage** (`config-ui.js:707`/`:728`): ein Klick entzieht
  einem Nutzer die Adminrolle, Speichern schreibt es fest.
- **Der Schwierigkeitsgrad speichert beim Schieben** (`_advanced_settings_modal.html:749`,
  `:785-803`) — ohne Speicherschritt, ohne Rückfrage.
- **`GET /api/migration-help`** schreibt den **entschlüsselten Bot-Token** ins DOM
  (`security_service.py:175`). Das ist **beabsichtigt** und hinter Anmeldung — Zweck ist der Umzug
  auf eine Umgebungsvariable. Gehört in die bewussten Entscheidungen, mit Risikohinweis. **[belegt]**
- **CSRF ist sauber gelöst** (`_base.html:44-103` überschreibt `window.fetch`), mit einer Lücke:
  `tasks/form.html` als eigenständige Seite erbt `_base.html` nicht, sendet daher keinen Token und
  wird vom Server abgewiesen.
- `app/static/js/main.js` ist ein **Fragment ohne Funktionsanfang** und wird von keinem Template
  geladen.

---

## 10. Bewusste Entscheidungen

Davon gibt es mehr als erwartet, und viele sind gut begründet — die angenehme Überraschung dieser
Aufnahme. Sie gehören in Stufe 1 in die SPEC, sonst kassiert sie der nächste Umbau.

- **`SESSION_COOKIE_SECURE` bleibt `False`** (`app/web/config.py:36`): „most installs are plain HTTP
  on the LAN". `SameSite=Lax` statt `Strict` (`:39`), damit ein Link aus Discord die Sitzung im
  anderen Tab nicht zerschießt.
- **Der Anmelde-Cache** (`app/auth.py:23-42`): 85,6 ms je Anfrage gemessen; gespeichert werden nur
  *bereits verifizierte* Zugangsdaten, der Schlüssel enthält den Passwort-Hash, damit ein
  Passwortwechsel alle Einträge sofort unerreichbar macht. Sauber durchdacht und aufgeschrieben.
- **CSRF darf nicht leise ausfallen** (`app/web/csrf.py:112`).
- **Ein einzelnes `NotFound` verbirgt keinen Container dauerhaft**
  (`container_status_service.py:504`) — während eines Unraid-Auto-Updates wird er entfernt und neu
  erstellt.
- **Spenden werden nie hart gelöscht**, sondern per Kompensationsereignis
  (`progress_service.py:1525`), mit Sperre gegen den veralteten Doppelklick
  (`donation_management_service.py:299`). Die am besten gebaute Stelle des Projekts — ausgerechnet
  der Reset daneben kennt diese Sorgfalt nicht.
- **Stop/Restart werden nach einem Timeout nie ein zweites Mal geschickt** (`scheduler.py:1812`).
- **Leeres Token-Feld heißt „behalten", nie „löschen"** (`config_form_parser_service.py:439`).
- **Verdikte zur Spielabfrage** werden einzeln per Read-Modify-Write geschrieben
  (`game_query_support_service.py:226,246`), ein langsam startender Server bekommt ein frisches
  15-Minuten-Fenster (`:177`).
- **Zeitzone im Logger bewusst nicht über `utils.time_utils`** (`logging_utils.py:165`), weil jene
  Funktion schreibt.
- **Der Control-Kanal *ist* die Admin-Grenze** (vom Betreiber bestätigt, 2026-09-16). Wer in einem
  Control-Kanal schreiben darf, darf steuern. Die Zugangskontrolle liegt bei Discord, nicht bei DDC.
  Der Kommentar in `docker_control.py:2028` („Control channels are already restricted to admins by
  design") beschreibt also korrekt die Absicht — er war bisher nur nirgends festgehalten.
- **Ohne Begründung:** Spam-Schutz am Toggle-Button „intentionally removed" (`control_ui.py:655`).

---

## 11. Die schwersten Befunde, nach „merkt der Nutzer es?"

| # | Befund | Warum oben |
|---|---|---|
| 1 | Testsuite kann echtes `config/` zerstören (`mech_reset_service.py:42-45` + `test_mech_data_services.py:944`) | Datenverlust beim Testen; nur der Mount in `ddc_test.sh` verhindert ihn |
| 2 | Jeder Discord-Nutzer bucht beliebige Beträge ins Hauptbuch (`docker_control.py:4731`) | falsche Auskunft über echtes Geld, völlig lautlos |
| 3 | Fehlgeschlagene Buchung → Dankesmeldung geht trotzdem raus (`:4885-4887` → `:4939`) | „ein Erfolg ist geraten", öffentlich |
| 4 | UI meldet gelöschte Protokolle, ohne den Server zu fragen (`_scripts.html:1836-1862`) | der Nutzer glaubt, Daten seien weg |
| 5 | ~~Container-Steuerung ist kanal-, nicht nutzergebunden~~ | **Zurückgezogen 2026-09-16** — vom Betreiber als gewollt bestätigt, siehe Abschnitt 4. Gehört in die SPEC, nicht in die Fehlerliste. |
| 6 | `/addadmin` erzeugt ein Recht, das den Kanal überdauert (`:2026-2029` → `admins.json`) | kein Widerspruch zum Kanalmodell, aber `control_ui.py:998` umgeht damit die Kanalprüfung. **Entwurfsfrage an den Betreiber, siehe Frage 1.** |
| 7 | Spenden-Reset trunciert das Ereignislog ohne Sicherung (`reset.py:96`) | **bestätigt: echter Datenverlust** — das Hauptbuch ist laut Betreiber die einzige Wahrheit der lokalen Instanz |
| 8 | CI veröffentlicht Images ohne jede Testprüfung (`docker-publish.yml`) | der Testlauf ist folgenlos |
| 9 | `dataclasses.dataclass` prozessweit ersetzt (6 Testdateien) | die Tests prüfen nicht die Klassen, die ausgeliefert werden |
| 10 | Aufgabenlöschung ungeprüft (`status_info_integration.py:2567`) | dieselbe Regel, an einer Stelle vergessen |

---

## 12. Was NICHT geprüft wurde

Dieser Abschnitt ist der wichtigste, und er ist bewusst unbequem.

**Nicht ausgeführt, nur gelesen:**
- Die Gegenprobe aus Stufe 3 — *Fehler zurückbauen und sehen, ob der Test rot wird* — wurde für
  **keinen einzigen** Test gemacht. Stufe 0 verbietet Codeänderungen. **Alle Aussagen über
  „würde fehlschlagen" sind aus dem Prüftext gelesen, nicht gemessen.**
- Das Isolationsexperiment umfasste **ein** Dateipaar. 111 weitere Dateien wurden nicht einzeln
  gegen den Gruppenlauf geprüft.

**Gar nicht angesehen:**
- `app/static/vendor/bootstrap/js/bootstrap.bundle.min.js` (minifiziert, Fremdcode).
- `docker/entrypoint.sh` (wird nicht benutzt, aber der Inhalt ist ungelesen).
- Die Workflows `dependency-checks.yml` und `dockerhub-readme-sync.yml`.
- Sieben Diagnoseskripte wurden nur per Grep als schreibfrei eingestuft, nicht gelesen.
- `config/` selbst — über SMB nicht lesbar (Modus 700); auf dem Host nur auf Dateinamen geprüft.

**Nur teilweise angesehen:**
- `services/` wurde **nicht systematisch gelesen** — 60.800 Zeilen, der größte Logikblock des
  Projekts. Befunde daraus stammen aus gezielten Suchen, nicht aus einem Durchgang.
- `cogs/scheduler_commands.py`, `cogs/admin_overview.py`, `cogs/enhanced_info_modal_simple.py`
  wurden nicht vollständig gelesen (die drei großen Cogs dagegen schon).
- Von ~411 Sende-/Editierstellen in Discord wurden nur die Löschungen und Spendenpfade vollständig
  erfasst.

**Methodisch offen:**
- Die Kategorie „Mock-Tautologie" fand das Werkzeug nur dort, wo ein Literal direkt als
  `return_value` gesetzt wurde. Tautologien über Variablen oder Fixtures bleiben unentdeckt.
- **Das Messmittel selbst hatte eine Lücke — gefunden, weil eine Vorhersage nicht aufging.**
  Im vollständigen Lauf vom 2026-09-16 (`b0hu3ug8w`) hinterließ `tests/unit/services/mech` einen
  **leeren** Eintrag: `rc=0`, aber keine Zusammenfassungszeile. Meine Auswertung summierte die
  fehlende Zeile als **null Tests**; aus 4.506 grün wurden lautlos 4.059, und nichts schlug an.
  Aufgefallen ist es einzig deshalb, weil die Zahl **vor** dem Lauf angesagt war und die Abweichung
  444 betrug statt der erwarteten 3. Ohne diese Vorhersage wäre es durchgegangen.
  *Geprüft, woran es lag — nicht am Läufer:* `scripts/ddc_test.sh` reicht den Rückgabewert von
  pytest durch (`:90`, `:97`, `:101`), und zwei Proben belegen es: ein Pfad, den es nicht gibt,
  liefert `rc=4`, ein Filter, der nichts trifft, `rc=5`. **Das Werkzeug kann keinen Erfolg melden,
  ohne getestet zu haben** — die grünen Ergebnisse dieser Sitzung stehen. Die Lücke lag in meiner
  Auswertungsschleife, die „keine Ausgabe" nicht von „keine Tests" unterscheiden konnte.
  *Behoben* in `lauf_mit_waechter.sh`: `rc=0` ohne Ergebniszeile gilt jetzt als **FEHLENDE MESSUNG**
  und wird samt Rohausgabe protokolliert, statt still als Null zu zählen.
  *Offen und nicht mehr klärbar:* Die Rohausgabe jenes Durchgangs ist fort. Ob damals die
  Übertragung oder die Erfassung die Zeile verlor, lässt sich nachträglich nicht feststellen.
- Dass in einem vollständigen Lauf 4.506 Einzeltests grün sind, sagt nichts über die 362 hohlen
  Testfunktionen — und nichts darüber, ob die restlichen 3.600 die *richtigen* Dinge prüfen.
  *Korrektur 2026-09-16:* Hier standen 4.492, 356 und 3.563. Die 3.563 war obendrein ein
  Kategorienfehler: Ein Lauf zählt Test**ausführungen** einschließlich Parametrisierung, der Zensus
  zählt Test**funktionen** im Quelltext. Die eine Zahl von der anderen abzuziehen ergibt nichts.

---

## 13. Fragen an den Betreiber

Diese sind nicht technisch und dürfen nicht vom Entwickler entschieden werden.

1. ~~Sind Control-Kanäle auf Admins beschränkt?~~ **Beantwortet 2026-09-16:** Ja — ein Control-Kanal
   macht alle seine Mitglieder zu Admins; das ist das gewollte Modell. **Anschlussfrage, noch offen:**
   Soll das per `/addadmin` erteilte Recht den Kanal *überdauern* (heute tut es das, inklusive der
   Umgehung der Kanalprüfung in `control_ui.py:998`), oder soll Autorisierung ausschließlich aus der
   aktuellen Kanalmitgliedschaft folgen? — **Beantwortet 2026-09-16: soll so sein.** `/addadmin`
   zielt primär auf den Status-Kanal. **Neue offene Frage an ihrer Stelle:** `/donate` hat gar keine
   Kanalprüfung, das Spendenbuch ist also von überall beschreibbar (Abschnitt 4).
2. ~~Ist das Hauptbuch die einzige Aufzeichnung der Spenden?~~ **Beantwortet 2026-09-16:** Ja, für
   die lokale Instanz ist es die einzige Wahrheit. Befund 7 ist damit echter Datenverlust.
3. **Fünf Web-Adressen tun etwas, aber kein Knopf im Panel ruft sie auf** (Abschnitt 9). Sie sind
   nur erreichbar, wenn jemand die Anfrage von Hand stellt (angemeldet, z.B. per `curl`) — oder
   wenn ein Skript sie versehentlich trifft. Zwei davon sind die zerstörendsten Vorgänge des
   Programms überhaupt:

   | Adresse | Wirkung |
   |---|---|
   | `POST /api/donation/reset-power` | **löscht das gesamte Spendenbuch** |
   | `POST /api/mech/reset` | setzt den Mech auf Stufe 1 zurück (löscht dabei ebenfalls das Buch) |
   | `POST /api/donation/add-power` | schreibt eine Spende gut |
   | `POST /clear-action-log` | leert das Aktionsprotokoll |
   | `POST /clear_logs` | tut nichts (die Attrappe aus Abschnitt 9) |

   **Entschieden 2026-09-16: entfernen.** Umfang und Zeitpunkt werden beim Übergang in Stufe 2
   festgelegt; der Kommandozeilenweg (`scripts/reset_mech.py`) bleibt unberührt.
4. ~~Darf ein eingeladener Nutzer im Control-Kanal Container stoppen?~~ **Beantwortet 2026-09-16:**
   Ja — jeder Nutzer im Control-Kanal darf alles.

---

## 14. Erste Korrektur — sechs Endpunkte ohne Aufrufer entfernt (2026-09-16)

Auf Entscheidung des Betreibers, **vor** Stufe 1 ausgeführt. Noch nicht committet.

**Entfernt**, weil kein Knopf und kein JavaScript sie je aufrief, sie aber teils das Spendenbuch
vernichten konnten:

| Endpunkt | Datei |
|---|---|
| `POST /api/donation/reset-power` | `app/blueprints/main_routes.py` |
| `POST /api/mech/reset` | `app/blueprints/main_routes.py` |
| `POST /api/donation/add-power` | `app/blueprints/main_routes.py` |
| `POST /api/donation/consume-power` | `app/blueprints/main_routes.py` |
| `POST /clear-action-log` | `app/blueprints/action_log_routes.py` |
| `POST /clear_logs` | `app/blueprints/log_routes.py` |

Mit entfernt: die Attrappe `ContainerLogService.clear_logs` samt `ClearLogRequest`, der
„Clear"-Knopf und seine **falsche Erfolgsmeldung** (`_scripts.html`, `window.clearLogs` meldete
„logs cleared successfully", ohne je den Server zu fragen), der tote `clearActionLogBtn` und die
tote `consumePower`-Funktion in `config.html`.

**Nachgemessen, nicht behauptet:**
- Routen: `main_routes.py` 38 → 34, `log_routes.py` 8 → 7, `action_log_routes.py` 3 → 2.
- Kein entferntes Symbol überlebt irgendwo (AST-Prüfung + ungekürzte Volltextsuche).
- Suite: **4.464 grün, 0 Fehlschläge**, keine Gruppe mit Fehlercode (vorher 4.492).
- Die Differenz von 28 entspricht genau den bewusst entfernten Testfunktionen — es ist kein Test
  unbemerkt verschwunden.
- 918 Zeilen entfernt, 3 hinzugefügt, 12 Dateien.

**Bewusst NICHT angefasst** (Folgebefunde für Stufe 2, sonst wächst eine überprüfbare Änderung zu
einer unüberprüfbaren):
- `show_clear_logs_button` (`configuration_page_service.py:539`) — Konfigurationsschlüssel ohne
  Wirkung, Entfernung berührt Schema und fünf Tests.
- `ConsumePowerLogFilter` (`app/web/logging.py:34,58`) — filtert Log-Rauschen einer Route, die es
  nicht mehr gibt.
- `_get_cached_mech_state` (`main_routes.py:27`) — hat eigene Tests, aber seit diesem Schnitt
  **keinen Aufrufer mehr** in der Produktion.
- Zwei veraltete Kommentare (`_scripts.html:567`, `test_other_routes.py:1379`).
- Der Import `log_user_action` in `action_log_routes.py` bleibt ungenutzt stehen: eine Testvorrichtung
  (`test_other_routes.py:1380`) setzt ihn per `monkeypatch`, ein „Aufräumen" hätte sie zerstört.

### Was dabei schiefging, und warum es hierher gehört

Die Liste der betroffenen Tests habe ich zunächst mit einer auf `head -40` gekürzten Suche
ermittelt — und danach gehandelt. Drei Testblöcke fehlten darin (`test_blueprint_gaps.py` kam
überhaupt nicht vor). Die ungekürzte Suche fand danach noch zwei weitere. **Zweimal an einem Tag
derselbe Fehler: Was nicht in der Liste stand, wurde nicht geprüft** — einmal bei den 18 vergessenen
Testdateien, einmal hier. Das ist genau der Befund, für den Stufe 4 den Vertragstest über den
Zuschnitt vorsieht, und der beste vorliegende Beleg dafür, dass er gebraucht wird.

---

## Anhang: Werkzeuge und Wiederholbarkeit

**AST-Zensus:** `audit_tests.py` (derzeit im Arbeitsverzeichnis der Sitzung, nicht im Repository).
Stuft jede Testfunktion mechanisch ein. Als Prüfung gelten `assert`, `pytest.raises`,
`mock.assert_*`, `pytest.fail()`/`self.fail()`, `raise AssertionError` und Hilfsfunktionen, deren
Name mit `assert`/`verify`/`expect`/`check_` beginnt. Ein Test gilt erst als hohl, wenn **alle**
seine Prüfungen hohl sind.

**Suitenlauf:** `DDC_TEST_HOST=unraid scripts/ddc_test.sh <gruppe>` — eine Gruppe je Aufruf
(mehrere Gruppen lassen `tests/unit/services/` das echte Paket verdecken, siehe Kommentar im Skript).
Gelaufen: 24 Gruppen + 18 Einzeldateien.

**Achtung, selbst erlebt:** Meine erste Gruppenliste hat **18 Testdateien nicht erfasst** — die vier
direkt in `tests/unit/services/` und die 14 in `tests/`. Sie standen in keiner Liste und wären
ungeprüft geblieben. Genau der Effekt, den Stufe 4 mit dem Vertragstest über den Zuschnitt
verhindern soll. Diese Erfahrung ist der beste Beleg dafür, dass dieser Vertragstest gebraucht wird.
