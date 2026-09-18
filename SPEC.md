# SPEC — was DDC zusichert

**Stand:** 2026-09-16 · **Status: in Arbeit.**

Die Liste der zehn Zusicherungen wurde vorgelegt, aber **nicht Punkt für Punkt bestätigt** — der
Betreiber hat die Abarbeitung delegiert und zwei Einzelfragen entschieden (Z4: Browser-Token;
Z5: alte Admin-Panels werden sofort wirkungslos). Formal steht die Liste als Ganzes damit weiterhin
auf *vorgelegt*. **Z10** (Testgatter in der CI) wurde am 2026-09-17 entschieden — volles Gatter,
gruppenweise — und ist umgesetzt. Offen bleibt die Frage, ob die dokumentierte Scheduler-Ausnahme
unter Z5 eine bewusste Entscheidung werden soll.

Ohne Maßstab ist ein Review nur Meinung. Diese Datei hält fest, was DDC verspricht — damit man ein
Verhalten *widerlegen* kann, statt über Geschmack zu streiten.

Eine Zusicherung sagt in einem Satz, was **nie** passieren darf oder **immer** gelten muss, sie
lässt sich widerlegen, und sie bedeutet dem Nutzer etwas — nicht nur dem Entwickler.

Grundlage ist die Bestandsaufnahme in [`docs/quality/STUFE0_BESTANDSAUFNAHME.md`](docs/quality/STUFE0_BESTANDSAUFNAHME.md).
Die Spalte **Heute** ist bewusst unbequem: mehrere dieser Zusicherungen sind derzeit gebrochen.

---

## Zusicherungen

### Z1 — Das Spendenbuch geht nie ohne Sicherung verloren.
Kein Vorgang leert oder überschreibt das Ereignislog, ohne vorher eine wiederherstellbare Kopie
anzulegen — auch dann nicht, wenn der Betreiber den Vorgang selbst auslöst.

*Gebrochen, wenn:* nach einem Reset keine Datei mehr existiert, aus der sich der vorherige Stand
herstellen lässt.
*Warum es zählt:* das Buch ist die einzige Aufzeichnung der echten Spenden dieser Instanz.
**Heute: behoben (2026-09-16).** Vorher schrieb `reset.py:96` ersatzlos `""` in das Log. Jetzt legt
`_backup_before_reset()` vor dem Löschen und innerhalb derselben Sperre eine Kopie von Ereignislog,
Sequenzzähler und Snapshots unter `<data_dir>/backup_<Zeitstempel>/` an — dieselbe Konvention, die
`scripts/reset_donations.sh:32-44` schon benutzte. Scheitert die Sicherung, **bricht der Reset ab**,
statt nur zu warnen. Zwei Resets ergeben zwei Sicherungen, nicht eine überschriebene.
*Abgedeckt von* `tests/spec/test_z1_donation_ledger_backup.py`.
*Gegenprobe:* vorher alle 3 Tests rot, jeder an seiner eigenen Zusicherung; danach grün;
vollständiger Lauf 4.470 grün, 0 Fehlschläge.

### Z2 — Ein Testlauf fasst niemals Produktivdaten an.
Kein Test schreibt in das echte `config/`, gleich mit welchem Runner er gestartet wird und gleich,
ob `DDC_CONFIG_DIR` gesetzt ist.

*Gebrochen, wenn:* nach einem Testlauf eine Datei unter `config/` verändert oder gelöscht ist.
**Heute: behoben (2026-09-16).** Vorher löste `MechResetService` `config_dir="config"` gegen die
Projektwurzel auf und ignorierte `DDC_CONFIG_DIR`; `test_mech_data_services.py:944` ruft
`quick_mech_reset()` scharf auf, und nur der leere Mount in `scripts/ddc_test.sh` verhinderte den
Schaden. Jetzt folgt der Standardfall derselben Regel wie `config_service.py:181` und
`progress_service.py:561`. Ein ausdrücklich übergebener Pfad verhält sich unverändert.
*Abgedeckt von* `tests/spec/test_z2_config_isolation.py`.
*Gegenprobe:* vor der Korrektur 2 der 3 Tests rot, danach 3 grün; vollständiger Lauf 4.467 grün,
0 Fehlschläge.

### Z3 — Kein Erfolg wird gemeldet, der nicht stattgefunden hat.
Sagt die Oberfläche „erledigt", hat der Server den Vorgang bestätigt. Ein halb ausgeführter Vorgang
wird nie als abgeschlossen dargestellt.

*Gebrochen, wenn:* eine Erfolgsmeldung erscheint, ohne dass eine Anfrage gestellt wurde oder obwohl
die Antwort ein Scheitern meldete.
**Heute: behoben für die beiden bekannten Fälle (2026-09-16).** Der „Clear"-Knopf meldete Erfolg
ohne jede Anfrage — entfernt. Der Spenden-Broadcast sendete eine Dankesmeldung auch dann, wenn die
Buchung geworfen hatte (`:4885-4887` fing die Ausnahme, die Ausführung fiel in den Broadcast) oder
wenn mangels Buchungsdienst gar nicht gebucht wurde (`:4789`). Jetzt entscheidet ein ausdrückliches
`donation_booked`, und der Nutzer bekommt bei ausgebliebener Buchung eine ehrliche Meldung statt
„Donation broadcast sent!".
*Abgedeckt von* `tests/spec/test_z3_z8_donation_broadcast.py`.
*Gegenprobe:* zweimal Fehlstart am Testgerüst (rot aus dem falschen Grund, korrigiert wurde der
Test); dann berechtigtes Rot an allen drei Zusicherungen; die **erste Korrektur war unvollständig**
und der Test zeigte es (`{100: 1, 200: 0}`) — die Sperre hing an `donation_amount_euros`, das erst
im übersprungenen Block zugewiesen wird. Vollständiger Lauf **4.478 grün, 0 Fehlschläge**.
*Dabei gefunden und mitbehoben:* Ein unbedingter Zugriff auf ein möglicherweise unzugewiesenes
`new_state` ließ den Callback im Fall „Spende ohne Betrag" mit `UnboundLocalError` abstürzen — von
beiden `except`-Blöcken ungefangen, sodass der Nutzer dauerhaft „Processing…" sah und die
Unterstützungsmeldung nie hinausging. Drei Stellen betroffen, alle auf `new_evolution_level`
umgestellt. *Gegenprobe:* vorher 1 rot / 14 grün, danach 15 grün.

### Z4 — Geld wird nie doppelt oder unbelegt gutgeschrieben.
Jede Spende trägt einen Idempotenzschlüssel, der nicht von der Uhrzeit abhängt. Zweimal dieselbe
Spende ergibt einen Eintrag, nicht zwei.

*Gebrochen, wenn:* zwei identische Buchungen im selben Moment zwei Einträge erzeugen.
**Heute: behoben (2026-09-16).** Der Befund war ein Durchreichungsfehler, kein fehlendes Verfahren:
`ProgressService.add_donation` konnte Idempotenz längst und war dafür getestet
(`test_progress_service.py:322`) — der Schlüssel ging nur zwischen Eintrittsstelle und Dienst
verloren, worauf `progress_service.py:1024` auf `donor|amount|utcnow()` zurückfiel.

Jetzt trägt `DonationRequest` ein Feld dafür, und der Schlüssel läuft durch alle fünf Schichten
(`models` → `processors` → `mech_service_adapter` → `progress_service`). Die Eintrittsstellen
liefern ihn: Discord nimmt `interaction.id` (`docker_control.py:4822`), der Browser erzeugt beim
ersten Absenden ein Token und lässt es erst nach **bestätigter** Buchung verfallen — ein
Wiederholungsversuch nach dem 30-Sekunden-Abbruch trägt damit dasselbe Token, ein Neuladen
dagegen ein neues, weil das eine echte zweite Spende ist.

*Vom Betreiber entschieden:* Browser-Token statt Zeitfenster über (Spender, Betrag) — ein Fenster
hätte eine echte schnelle Zweitspende verschluckt und damit echtes Geld verloren.
*Beachte:* `crypto.randomUUID` gibt es nur im sicheren Kontext; da DDC bewusst als reines HTTP
läuft (B3), hat die Erzeugung einen Ersatzweg — ohne ihn entstünde gar kein Token.

*Abgedeckt von* `tests/spec/test_z4_donation_idempotency.py` (3 Dienst-Tests + 2 Verträge zur
Oberfläche, weil eine reine Backend-Durchreichung die Zusicherung im Alltag nicht erfüllt).
*Gegenprobe:* Dienst-Tests vorher `TypeError` (Verfahren fehlte) — ein ehrliches, aber schwaches
Rot. Die beiden Vertragstests waren zuerst aus dem **falschen** Grund rot (Fehler im Test selbst);
nach deren Korrektur wurde die Gegenprobe echt nachgeholt: Token im Frontend entschärft → genau
diese zwei rot, wiederhergestellt → alle grün. Vollständiger Lauf **4.475 grün, 0 Fehlschläge**.
*Dabei gefunden:* `FakeMechService` in `tests/test_unified_donation_service.py` nagelte die alte
Signatur fest — mitbehoben.

### Z5 — Kein Eingriff an einem Container ohne Kanalrecht und erlaubte Aktion.
Start, Stopp und Neustart geschehen nur, wenn der Kanal die Berechtigung trägt **und** der Container
die Aktion erlaubt — auf **jedem** Weg: Knopf, Zeitplan, Automatikregel, Web-Panel.

*Gebrochen, wenn:* ein Weg existiert, der einen Container anfasst, ohne beide Prüfungen zu bestehen.
*Hinweis:* Autorisierung über den **Kanal** ist gewollt (siehe Bewusste Entscheidungen B1). Diese
Zusicherung verlangt keine Nutzerprüfung — sie verlangt, dass die Kanalprüfung **lückenlos** ist.
**Heute: behoben (2026-09-16), mit einer offenen Nebenfrage** (die Scheduler-Ausnahme, siehe unten).
Der Weg dorthin gehört hierher, weil die ursprüngliche Fassung dieser Zeile zu grob war und beim
Nachlesen widerlegt wurde:

- *„Vier Stellen umgehen das Kanalrecht"* — teils widerlegt, **teils zu Unrecht entlastet.**
  `:429` steuert nur das Nachzeichnen der Admin-Nachricht (`:483`). Das dabei gesetzte Kennzeichen
  `_is_admin_control` (`:487`, entfernt bei `:531`) wird an genau zwei Stellen gelesen
  (`status_handlers.py:1051`, `status_info_integration.py:1143`) und unterdrückt dort ebenfalls nur
  Anzeige — die Berechtigung kommt unverändert aus `_channel_has_permission` (`status_handlers.py:1040`).
- *Übrig bleibt **eine** tragende Stelle:* `control_ui.py:304` — `is_admin_control or <Kanalrecht>`.
  Sie ist redundant, solange das Panel in einem Control-Kanal steht (`/control` prüft das Recht
  bereits, `docker_control.py:1947`). Sie wird nur dann zur Lücke, wenn **die Nachricht das Recht
  überdauert**: Panel gepostet, danach Control-Recht entzogen, Panel bleibt bedienbar.
- *Die Scheduler-Ausnahme ist **dokumentiert gewollt***, nicht vergessen:
  `scheduler.py:1791-1794` — „Web UI tasks are admin tasks and always run (R4-1)". Sie gehört unter
  **Bewusste Entscheidungen**, sofern der Betreiber nicht widerspricht.

**Entschieden 2026-09-16 (Betreiber): (a)** — verliert ein Kanal sein `control`-Recht, werden alte
Admin-Panels **sofort wirkungslos**. Eine Berechtigung darf nicht in einer Nachricht stecken, die
Monate alt sein kann. `control_ui.py:304` ist damit ein Befund: Die Titel-Heuristik entfällt an
dieser Stelle, und der Knopf prüft nur noch das **aktuelle** Kanalrecht.
Die rein darstellende Verwendung bei `:429` bleibt unberührt — sie erteilt kein Recht.

**Nachtrag 2026-09-17 — ein zweiter Weg, und eine falsche Einstufung von gestern.**
Oben stand, `control_ui.py:1019-1025` und `:1072-1079` seien „rein darstellend". **Das war falsch.**
Beide berechneten `has_control = is_admin_control or <Kanalrecht>` und entschieden damit, ob
`ContainerInfoAdminView` gebaut wird. Diese Ansicht hängt `TaskManagementButton` **bedingungslos**
ein (`status_info_integration.py:55`), und von dort führt ein Weg über `TaskManagementView` →
`DeleteTasksButton` → `ContainerTaskDeleteButton` zu `delete_task()` — **vier Ebenen, keine einzige
Rechtsprüfung**. Ein alter Nachrichtentitel genügte also, um Zeitaufträge löschen zu können.
Der Kommentar bei `:1053` sagte es sogar offen: „Don't re-check channel permission as it would
ignore admin control context."

*Zweiter Befund an derselben Stelle:* Derselbe Eingriff verlangte je nach Weg ein anderes Recht.
`control_ui.py:1276` prüft `schedule`; `status_info_integration.py` kannte die Zeichenkette
`'schedule'` überhaupt nicht. Wer `control` hatte, aber `schedule` bewusst **nicht**, konnte über den
zweiten Weg trotzdem löschen.

*Behoben:* Beide Stellen entscheiden nur noch nach dem **aktuellen** Kanalrecht (wie `:304` seit
gestern), die dort tot gewordenen Zeilen sind entfernt, und `ContainerTaskDeleteButton` prüft
`schedule` wie sein Zwilling.
*Abgedeckt von* `tests/spec/test_z5_aufgaben_loeschweg.py` (3 Tests).
*Gegenprobe:* 2 rot wie vorhergesagt, beide aus dem richtigen Grund — der Stapel zeigte, dass die
Ansicht bei `control: False` allein wegen des Titels gebaut wurde. Nach der Korrektur 3 grün,
`test_z5_channel_permission.py` unverändert 3, `tests/unit/cogs` unverändert 267.

*Geprüft und diesmal bestätigt:* Das Kennzeichen `_is_admin_control` (`:496`, `:540`, `:1988`,
`:2034`) wird an zwei Stellen gelesen (`status_handlers.py:1051`,
`status_info_integration.py:1143`) und unterdrückt dort **nur Anzeige**. Hier hält die Einstufung.

*Ebenfalls geprüft und abgegrenzt:* Die beiden Web-Wege zu `delete_task`
(`app/blueprints/tasks_bp.py:194`, `services/web/task_management_service.py:817`) hängen an
`@auth.login_required`. Das Panel hat ein eigenes Rechtemodell, nicht das Kanalmodell — kein Teil
dieses Befunds.
**Status: behoben (2026-09-16).** `control_ui.py:304` liest nur noch das aktuelle Kanalrecht.
*Abgedeckt von* `tests/spec/test_z5_channel_permission.py`.
*Gegenprobe:* Das Rot fiel **stärker aus als vorhergesagt** — erwartet hatte ich einen Fehlschlag
an `pending_actions == {}`, tatsächlich riss schon der Stolperdraht bei `:332`, und das Protokoll
zeigte `[ACTION_BTN] STOP action for 'nginx' triggered by Irgendwer`: Ohne Kanalrecht, allein wegen
des Titels, war der Eingriff nicht bloß vorgemerkt, sondern in vollem Gange. Nach der Korrektur
21 grün, `tests/unit/cogs` unverändert 267 grün, vollständiger Lauf **4.485 grün, 0 Fehlschläge**.
*Danach verschärft:* Ein Test, der vorher über einen Stolperdraht fiel, kann danach grün sein, weil
der Draht nicht mehr reißt — nicht, weil die Zusicherung hält. Der Ablehnungstext wird deshalb
festgenagelt; ein bloßes `assert_awaited()` wäre auch vom Pfad „kein Kanal" (`:294`) erfüllt worden.

*Nicht abgedeckt:* Der Scheduler-Weg. `scheduler.py:1791-1794` nimmt Web-Panel-Aufgaben
ausdrücklich von der Nachprüfung aus („Web UI tasks are admin tasks and always run (R4-1)"). Das
ist eine dokumentierte Entscheidung, keine Lücke — aber sie ist **nicht** vom Betreiber bestätigt
und steht auch nicht unter „Bewusste Entscheidungen". Offen.

### Z6 — DDC entfernt oder zerstört niemals einen Container.
Es gibt genau drei Aktionen: `start`, `stop`, `restart`. Kein `kill`, kein `remove`, kein `prune`.

*Gebrochen, wenn:* irgendein Pfad eine andere Docker-Aktion auslöst.
**Heute: hält — und ist seit 2026-09-16 festgenagelt.** Zwei Implementierungen, beide auf diese
drei begrenzt (`docker_action_service.py:90-94`, `docker_utils.py:626-631`).
*Abgedeckt von* `tests/spec/test_z6_docker_actions.py`: beide Aktionslisten, plus eine
projektweite Suche nach zerstörenden Aufrufen (`container.remove()` und Verwandte) — die prüft die
**Aufrufstelle**, nicht nur die Funktion.
*Gegenprobe, hier anders gelagert:* Die Zusicherung hält, es gibt also keinen Fehler zum
Rückgängigmachen. Alle vier Tests waren sofort grün — was sie verdächtig macht. Dagegen belegt ein
eigener Test, dass das Suchmuster überhaupt anschlägt. Nötig war das: Die erste Fassung übersprang
ausgerechnet `container.remove()` und konnte für den wichtigsten Fall nicht fehlschlagen; eine
zweite Stelle enthielt `assert ... is None or True`. Beides beim Gegenlesen gefunden, nicht im Lauf.

### Z7 — Eine Konfiguration überlebt jeden Schreibvorgang.
Jeder Schreibvorgang auf Konfigurations- oder Zustandsdateien ist atomar (Temp-Datei + Umbenennen).
Ein Absturz mitten im Schreiben lässt die alte Datei unversehrt.

*Gebrochen, wenn:* ein Abbruch während des Schreibens eine leere oder abgeschnittene Datei hinterlässt.
**Heute: alle fünf Stellen im Anwendungscode behoben (2026-09-16).** Die Skripte in `scripts/` sind
ausgenommen — das ist eine offene Frage an dich, siehe am Ende dieses Abschnitts.

*Behoben:* `progress_service.py:264` — der Sequenzzähler des Spendenbuchs. Die schwerwiegendste der
fünf: Ein Abbruch ließ die Datei nicht veraltet, sondern **leer** zurück (`open(..., "w")` kürzt beim
Öffnen), `next_seq()` las danach `int("" or 0)` und begann wieder bei 1 — mitten in einem
Ereignislog, in dem diese Nummern schon vergeben sind. Läuft jetzt über den neuen gemeinsamen
Helfer `utils/atomic_io.py`.
*Abgedeckt von* `tests/spec/test_z7_atomic_writes.py`.
*Gegenprobe:* vorher `assert '' == '5'`, danach 18 grün; vollständiger Lauf **4.482 grün, 0 Fehlschläge**.

*Ebenfalls behoben:* `container_status_service.py:153` — die vom Nutzer gepflegte
Container-Konfiguration (Anzeigename, erlaubte Aktionen, Reihenfolge). Ein Abbruch ließ sie
**restlos leer** zurück, und zwar in einem Vorgang, den der Nutzer nie auslöst und nicht sieht:
dem automatischen Deaktivieren, wenn Docker einen Container dauerhaft als abwesend meldet.
*Abgedeckt von* `tests/spec/test_z7_container_config_write.py`.
*Gegenprobe:* vorher `assert ''`, danach grün; vollständiger Lauf **4.497 grün**, 2 rot (nur Z10).

*Dabei der lehrreichste Fund des Tages:* `tests/unit/extended/test_docker_infra_gaps.py` sollte
denselben Fehlerpfad prüfen und war seit jeher grün — aber sein `_bad_open` warf bei **jedem**
Zugriff, also schon beim **Lesen**, lange vor dem Schreiben. Die Methode gab `False` zurück, die
Zusicherung war erfüllt, der Schreibpfad wurde nie erreicht. Der erste Reparaturversuch
(`os.fdopen` mitpatchen) war wirkungslos; belegt wurde das erst durch eine **Mutation**: mit einem
Helfer, der alle Schreibfehler verschluckt, blieb er grün, während der neue Test rot wurde. Erst
die zweite Fassung — nur Schreibzugriffe scheitern lassen — greift nachweislich.
**Allgemein:** Ein grüner Test sagt nichts darüber, ob er greift. Von den 3.962 Alttests wurde
genau einer so geprüft, und er war kaputt. Das gehört nach Stufe 3.

*Ebenfalls behoben:* `member_count/service.py:174` — die Mitgliederzahl-Momentaufnahme. Kein
kosmetischer Verlust: Die Zahl fließt in `requirement_for_level_and_bin()` und bestimmt damit, was
die nächste Mech-Stufe **kostet**. Eine leere oder halbe Datei verschiebt das lautlos, während die
Anzeige normal aussieht. Geschrieben wurde über `Path.write_text`, das beim Öffnen kürzt.
*Abgedeckt von* `tests/spec/test_z7_member_count_write.py`.
*Gegenprobe:* Dieser Test war **zweimal wertlos**, bevor er etwas bewies — beide Male grün. Einmal
lag der Abfangpunkt *vor* dem Schaden (die Attrappe warf, bevor die Datei gekürzt wurde), einmal
zählte die Restprüfung fremde Dateien derselben Ablage mit. Erst die dritte Fassung, die den Schaden
*nachstellt* statt ihn zu verhindern, wurde rot (`assert ''`). Zusätzlich per **Mutation** belegt,
dass der Test greift.

*Ebenfalls behoben:* `mech_reset_service.py:194` — der Mech-Zustand. Verloren ging dort nicht ein
Zählerstand, sondern die **Zuordnung**: `last_glvl_per_channel` und `mech_expanded_states` halten
fest, welcher Discord-Kanal welchen Stand hatte. Die Methode behält diese Struktur und setzt nur
Werte zurück — ein Abbruch beim Schreiben vernichtete sie ganz.
*Abgedeckt von* `tests/spec/test_z7_mech_state_write.py`.
*Gegenprobe:* beim ersten Anlauf getroffen (`assert ''`), Wächter schlug nicht an; per Mutation
belegt, dass der Test greift. Dass es diesmal sofort saß, lag daran, dass die beiden Fallen der
vorigen Durchgänge vorher benannt waren: Abfangpunkt **hinter** der Kürzung, und **nur**
Schreibzugriffe treffen.
*Mitgeprüft:* `mech_reset_service.py:302` greift ebenfalls auf dieselbe Datei zu — nur lesend, kein
Z7-Fall.

*Ebenfalls behoben — die fünfte von fünf:* `server_order.py:45` — die Serverreihenfolge. Die
Einstufung „kosmetisch" bleibt richtig: die Reihenfolge ist jederzeit neu zu legen. Der Grund, es
trotzdem zu tun, ist ein anderer — **der Verlust meldet sich nie**. `load_server_order()` fängt den
`JSONDecodeError` ab und gibt kommentarlos `[]` zurück (:72-74), die Anzeige fällt ohne Fehlermeldung
auf die Standardreihenfolge. Der Lauf hat genau diese Kette protokolliert: erst `Error saving server
order`, dann `Error loading server order: Expecting value: line 1 column 1` — und danach nichts mehr.
Geprüft wird deshalb nicht „die Datei hat Bytes", sondern die nutzerseitige Aussage: nach dem
gescheiterten Schreibvorgang liefert `load_server_order()` noch die gelegte Reihenfolge.
*Abgedeckt von* `tests/spec/test_z7_server_order_write.py`.
*Gegenprobe:* vor der Korrektur rot an genau dieser Zusicherung, beide Wächter hielten. Zusätzlich per
**Mutation** belegt: mit einem `atomic_write_text`, das Fehler verschluckt statt sie weiterzureichen,
wird der Test rot (`assert True is False` — „Ein gescheiterter Schreibvorgang darf nicht als Erfolg
gelten"); wiederhergestellt wieder grün, ohne Mutationsrest.
*Mitgeprüft, nichts nachzuziehen:* Die sieben vorhandenen Tests in `test_coverage_push_v3.py:138-225`
leiten `ORDER_FILE` um und arbeiten mit echten Dateien; der einzige, der abfängt (`os.makedirs`, :182),
trifft eine Stelle **vor** dem Schreibvorgang und bleibt unberührt. Anders als bei
`_deactivate_container` musste hier kein Test mitgezogen werden.

*Offen — und eine Frage an dich, keine Baustelle:* die Skripte in `scripts/`. Gezählt, nicht geschätzt:
**33 Schreibstellen in 16 Skripten** (eine Grep-Zeile war ein Fehltreffer, `migrate_to_modular.sh:281`
liest nur). Zwei davon fassen dieselben Dateien an wie das Programm — `migrate_to_modular.sh` schreibt
den kompletten Konfigurationssatz, `reset_mech.sh` das Spendenbuch.
Mein Vorschlag: **Z7 gilt für den Anwendungscode, nicht für die Skripte.** Sie laufen einmalig, vom
Betreiber angestoßen, der dabei zusieht — der Schaden wäre bemerkt, nicht unbemerkt. Das wäre eine
bewusste Entscheidung (B11) statt einer offenen Zusicherung. Deine Entscheidung, nicht meine.

*Beim Zählen mitgefunden, zwei Nebenbefunde zu den Reset-Skripten:*
1. `reset_mech.sh` sieht gefährlich aus — es schreibt `mech_donations.json` direkt — **ist es aber
   nicht**: Zeile 15 bricht mit `exit 1` ab, der gesamte Code darunter ist unerreichbar. Geprüft,
   kein Z1-Loch.
2. Dasselbe Skript verweist in :3 und :12 auf `scripts/safe_reset_mech.**py**`. Vorhanden ist
   `safe_reset_mech.**sh**`. Wer der Anweisung wörtlich folgt, bekommt „No such file or directory".
   Eine Zeichenkette, kein Datenverlust — aber der Betreiber steht im Reset-Fall vor einer Sackgasse.

*Nebenbefund:* Es gab bereits **zwei** Helfer für atomares Schreiben, und sie wichen voneinander ab —
`utils/token_security.py:25` erhält die Dateirechte und nutzt `os.replace`;
`services/config/channel_config_service.py:47` tut beides nicht und entfernt unter Windows die
Zieldatei vorher, was ein Fenster ohne Datei öffnet. `utils/atomic_io.py` übernimmt die sichere der
beiden. Die Zusammenführung der Altbestände ist ein eigener Punkt, kein Teil dieser Korrektur.

### Z8 — Kein stummer Fehlschlag bei etwas Unwiderruflichem.
Schlägt eine Handlung fehl, die sich nicht zurücknehmen lässt — Container anfassen, Datei löschen,
Nachricht senden, Geld buchen —, wird der Fehler sichtbar. Nie nur `except: pass`.

*Gebrochen, wenn:* ein solcher Fehler ausschließlich im Debug-Log landet oder gar nicht.
**Heute: am Spendenpfad behoben (2026-09-16), sonst weiterhin gebrochen.** Behoben: ein
verschluckter Buchungsfehler führte zu einer Dankesmeldung an alle Kanäle — siehe Z3.
**Offen geblieben:** 25 nackte `except:` in `cogs/` (33 im ganzen Projekt), zwei davon um Nachrichtenlöschungen
(`docker_control.py:4966`, `:4976`); `event_manager.py:78` fängt nur `RuntimeError`, jede andere
Ausnahme reißt die restlichen Handler mit. Diese Zusicherung ist damit **nicht** erfüllt, sondern
nur an einer Stelle durchgesetzt — das ist ausdrücklich festgehalten, damit sie nicht als erledigt
gilt.

### Z9 — Der Bot-Token liegt nie im Klartext auf der Platte.
Nicht in `config.json`, nicht in deren Sicherung, nicht in Logs.

*Gebrochen, wenn:* der entschlüsselte Token in einer Datei auftaucht.
**Heute: hält** und ist bereits getestet (`tests/unit/audit_2026_09/test_pkg_c2_config.py`).
*Ausnahme mit Ansage:* `GET /api/migration-help` gibt den Token bewusst über HTTP zurück — siehe B5.

### Z10 — Kein Image wird ausgeliefert, dessen Tests nicht grün gelaufen sind.
Ein veröffentlichtes Image hat einen vollständigen, bestandenen Testlauf hinter sich.

*Gebrochen, wenn:* ein Image veröffentlicht wird, ohne dass die Suite lief oder obwohl sie rot war.
**Heute: behoben (2026-09-17)** — nach Entscheidung des Betreibers für das **volle Gatter in
gruppenweiser Form**. Die Zusicherung war bei ihrer Formulierung gebrochen, und schwerer als in der
Bestandsaufnahme notiert.

*Was vorgefunden wurde* — vier Stellen, drei davon Testläufe, die **nicht rot werden konnten**:

| Stelle | Art | heute |
|---|---|---|
| `tests.yml:67` „Run unit tests with coverage" | `\|\| true` | entfernt, läuft gruppenweise |
| `tests.yml:122` „Run integration tests" | `\|\| true` **und** `continue-on-error: true` | beides entfernt |
| `code-quality.yml:295` „Run tests with coverage" | `continue-on-error: true` | entfernt, läuft gruppenweise |
| `docker-publish.yml` | führte überhaupt keine Tests aus | eigener `test`-Job, `build_and_push` hängt per `needs:` daran |

*Und der eigentliche Befund, der erst beim Beheben auftauchte:* Die Schutzschalter verbargen keine
roten Tests — sie verbargen, dass **überhaupt nicht getestet wurde**. `pytest tests/unit/` bricht mit
**79** Fehlern beim Einsammeln ab, `pytest tests/` mit **18**; in beiden Fällen läuft kein einziger
Test. Ursache ist eine Paketverdeckung: `tests/unit/services`, `tests/unit/cogs` und
`tests/unit/utils` haben kein `__init__.py`, heißen aber wie die echten Pakete. Das `✅ Unit tests
completed` im Bericht war ein `echo` hinter einem längst gestorbenen pytest.
Hätte man nur die Schutzschalter entfernt, wäre die CI **ab sofort dauerhaft rot** gewesen — und ein
dauerhaft rotes Gatter ist so wertlos wie ein dauerhaft grünes. Alle drei Aufrufe laufen deshalb
jetzt gruppenweise über `tests/GROUPS.txt`.
*Verworfen, weil gemessen:* `--import-mode=importlib` ändert nichts; drei nachgerüstete `__init__.py`
verschlechtern es von 18 auf **54** Fehler (zurückgenommen). Das Test-Layout umzubauen wäre zudem ein
Umbau „damit es testbar wird", ohne wartenden Test.

*Abgedeckt von* `tests/spec/test_z10_ci_test_gate.py` (6 Tests) und `tests/spec/test_z10_gruppenliste.py`
(3 Tests). Der zweite hält die handgepflegte Gruppenliste gegen Drift: **jede Testdatei liegt in genau
einer Gruppe** — sonst liefe eine neue Datei lautlos nie mit, ohne dass irgendetwas rot wird.

*Gegenprobe, in drei Stufen:* Die erste Fassung des Tests fand nur den Integrationsschritt — im
Unit-Test-Schritt steht `pytest` bei `:73` und das `|| true` erst bei `:80`, getrennt durch
Zeilenfortsetzungen. Nach Zerlegung in `- name:`-Schritte und Erweiterung um `continue-on-error`
vier Befunde statt einem, der vierte vorher unbekannt.
Nach dem Bau des Gatters schlug der Test **erneut** an, vier Mal — und alle vier Male auf
**Kommentare**, die gerade erst geschrieben worden waren („Kein `|| true` mehr …"). Der ausführbare
Code war sauber. Statt die Begründungen zu löschen wurde der Melder geschärft: ganze Kommentarzeilen
werden nicht ausgeführt und zählen deshalb nicht. Weil das wie eine Lockerung aussieht, trägt die
Schärfung einen eigenen **Wirkungsnachweis** mit vier Fällen — darunter der entscheidende
`pytest … || true  # sieht harmlos aus`, der weiterhin anschlagen muss. Danach `tests/spec`:
**50 grün, 0 rot.**

**Was damit ausdrücklich NICHT belegt ist:** Geprüft sind der Text und die YAML-Struktur der
Workflow-Dateien, nicht ein echter GitHub-Lauf. Dass der `test`-Job dort anläuft und
`build_and_push` tatsächlich blockiert, zeigt erst der erste Push. Diese Tests belegen, dass das
Gatter **dasteht** — nicht, dass GitHub es so ausführt.

---

## Bewusste Entscheidungen

Dinge, die wie ein Fehler aussehen, aber gewollt sind. Ohne diesen Abschnitt kassiert sie der
nächste Umbau stillschweigend.

**B1 — Autorisierung folgt dem Discord-Kanal, nicht dem Nutzer.**
Wer in einem Control-Kanal schreiben darf, darf alles. Die Zugangskontrolle liegt bei Discord (wer
den Kanal sehen darf), nicht bei DDC. *Vom Betreiber bestätigt am 2026-09-16.*
**Nicht „reparieren"** durch Einbau von Nutzerprüfungen — das bräche das Modell.

**B2 — Die globale Admin-Liste existiert für die Status-Kanäle.**
`/addadmin` schreibt in `admins.json`; dieses Recht überdauert die Kanalmitgliedschaft. Zweck ist,
dass Admins auch dort etwas dürfen, wo die Kanalmitgliedschaft allein nichts erlaubt.
*Vom Betreiber bestätigt am 2026-09-16.*

**B3 — `SESSION_COOKIE_SECURE` bleibt `False`.**
Die meisten Installationen laufen als reines HTTP im LAN, wo ein `Secure`-Cookie nie gesendet würde
(`app/web/config.py:36`). `SameSite=Lax` statt `Strict`, damit ein Link aus Discord die Sitzung im
anderen Tab nicht zerschießt (`:39`).

**B4 — Spenden werden nie hart gelöscht, sondern per Gegenbuchung.**
`progress_service.py:1525` schreibt ein Kompensationsereignis; Löschen ist ein Umschalter und damit
umkehrbar. Zusätzlich sperrt `donation_management_service.py:299` den veralteten Doppelklick.

**B5 — `GET /api/migration-help` gibt den entschlüsselten Bot-Token zurück.**
Beabsichtigt, hinter Anmeldung, Zweck ist der Umzug auf eine Umgebungsvariable
(`services/web/security_service.py:175`). *Risiko mit Ansage:* der Token landet im DOM und damit in
Verlauf und Entwicklerwerkzeugen des Browsers.

*Nachtrag 2026-09-18:* Dieses Risiko bestand bis heute **faktisch nicht** — der Weg war
unerreichbar. `migrate_to_environment_variable` las `self.config_manager`, ein Attribut, das
`__init__` nie setzt; der `AttributeError` wurde gefangen, und der Betreiber sah im Token-Fenster
den rohen Python-Text statt seines Tokens. Mit der Reparatur (Entscheidung des Betreibers) gilt B5
erstmals so, wie es hier steht. Wer den Eintrag vorher las, hielt ein Risiko für real, das keines
war — und hätte umgekehrt nie erfahren, dass die Funktion dahinter tot ist.

**B6 — Stop und Restart werden nach einem Timeout nie ein zweites Mal geschickt.**
Der erste Versuch läuft möglicherweise noch (`services/scheduling/scheduler.py:1812`).

**B7 — Ein einzelnes `NotFound` verbirgt einen Container nicht dauerhaft.**
Während eines Unraid-Auto-Updates wird ein Container entfernt und neu erstellt
(`container_status_service.py:504`).

**B8 — Ein leeres Token-Feld heißt „behalten", nie „löschen".**
`services/config/config_form_parser_service.py:439`.

**B9 — Der Anmelde-Cache speichert nur bereits verifizierte Zugangsdaten.**
Er senkt die Iterationszahl nicht und hilft keinem Angreifer; der Schlüssel enthält den
Passwort-Hash, sodass ein Passwortwechsel alle Einträge sofort unerreichbar macht
(`app/auth.py:23-42`).

**B10 — Es war ein Versehen. Wiederhergestellt am 2026-09-18.** Der Spam-Schutz am Toggle-Knopf war
„intentionally removed", aber eine Begründung stand nirgends — weder im Kommentar noch in der
Commit-Nachricht. Der entfernte Code (`0195074^`) war funktionsfähig. Jeder andere Knopf derselben
Datei prüft; dieser war die einzige Ausnahme, obwohl jeder Druck ein `message.edit` gegen die
Discord-API auslöst — der Knopf mit der niedrigsten Hemmschwelle war der einzige ohne Bremse.

*Nicht zurückgekippt, sondern dem Hausmuster angepasst:* Der alte Code hatte eine **unübersetzte**
Meldung und fing `Exception`. Verwendet wird jetzt der vorhandene Katalogeintrag ohne
`{action}`-Platzhalter (`locales/*.json:1453`, im Code bereits viermal benutzt) und der enge
Fehlerfang `(RuntimeError, AttributeError, KeyError)`.

**Was daran offen bleibt und deine Entscheidung ist:** Der Schlüssel `refresh` hat **kein Feld im
Panel** — dort steht `live_refresh`, ein anderer Schlüssel. Die Abklingzeit liegt damit fest bei
5 Sekunden und ist nicht einstellbar. Das ist genau das, was damals entfernt wurde, widerspricht
aber dem Grundsatz „das Panel bestimmt". Soll `refresh` ein Panel-Feld bekommen? Dieselbe Frage
stellt sich für `auto_refresh`: ebenfalls kein Feld im Panel — und anders als `refresh` hat er
auch nach dieser Korrektur keinen einzigen Abnehmer im Code.

**B11 — Ein Zeitauftrag behält sein Recht, auch wenn der Kanal es verliert.**
`ScheduledTask.__slots__` (`services/scheduling/scheduler.py:167-172`) hat 21 Felder, **keines
kanalbezogen** — nur `created_by` mit dem Nutzernamen. Eine erneute Kanalrechtsprüfung zur
Ausführungszeit ist damit für **keinen** Zeitauftrag möglich, nicht nur für die Web-UI-Ausnahme.
Entziehst du einem Kanal das Steuerrecht, feuern dort früher angelegte Aufträge weiter.
*Vom Betreiber entschieden am 2026-09-18: festhalten, nicht umbauen.* Wer einen Auftrag anlegen
durfte, behält ihn; Altaufträge bleiben unverändert gültig.

*Damit die Tragweite nicht falsch eingeschätzt wird:* Der Schrägstrich-Befehl-Mixin in
`cogs/scheduler_commands.py` ist **toter Code** — die Erweiterungsliste (`app/bot/startup_steps/
commands.py:26-30`) lädt nur `docker_control`, `auto_action_monitor` und `translation_monitor`, und
nichts referenziert den Mixin. Der lebende Weg ist der Knopf bei
`cogs/status_info_integration.py:2331` („TASK_CREATE_BUTTON"). Zeitaufträge entstehen aus Discord
also weiterhin — nur über eine andere Tür als zunächst vermutet.

**Nicht „reparieren"** durch nachträgliches Mitführen von `channel_id`, ohne das vorher zu
entscheiden: Das Datenformat änderte sich, und für Altaufträge ohne Feld bräuchte es eine eigene
Regel (weiterlaufen oder pausieren).

---

## Regeln des Qualitätsprogramms

Keine Zusicherungen an den Nutzer, sondern Regeln für uns — hier festgehalten, damit sie nicht
verloren gehen:

- **R1 — Ein Test ohne widerlegbare Prüfung gilt als Fehler.** Mechanisch prüfbar mit
  `scripts/audit_tests.py`.
- **R2 — Zu jeder Zusicherung existiert mindestens ein Test**, erkennbar an `# @deckt Zn`, und ein
  weiterer Test prüft, dass keine Zusicherung ohne Markierung bleibt.
- **R3 — Ein Befund, ein Commit, ein vollständiger Testlauf.**
- **R4 — Jede Korrektur trägt ihren Grund im Code:** nicht was er tut, sondern was vorher falsch war.
- **R5 — Abdeckung ist keine Zielgröße.**

---

## Zu entscheiden

1. Welche der zehn Zusicherungen gelten? Streichen, ergänzen, umformulieren — das ist deine Entscheidung.
2. ~~**B10:** Gab es einen Grund für das Entfernen des Spam-Schutzes am Toggle-Knopf?~~ **Beantwortet
   am 2026-09-18: ein Versehen, wiederhergestellt.** Offen bleibt nur die Wertfrage — soll `refresh`
   ein Panel-Feld bekommen, damit die Abklingzeit einstellbar wird?
3. Reihenfolge für Stufe 2: Ich schlage vor, mit **Z2** zu beginnen (ein Testlauf, der echte Daten
   zerstören kann, ist die gefährlichste offene Stelle), dann **Z1**, dann **Z4**.
