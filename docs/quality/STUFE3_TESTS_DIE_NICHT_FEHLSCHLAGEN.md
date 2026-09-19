# Stufe 3 — Tests aussieben, die nicht fehlschlagen können

**Stand:** 2026-09-17. Von den vier Prüfungen der Stufe sind **drei vollständig durchgeführt**
(„läuft er allein?", Spiegeltests, Funktion gegen Aufrufstelle), **eine nur stichprobenhaft**
(Gegenprobe durch Zurückdrehen: genau ein Alttest von 3.962). Was nicht geprüft wurde, steht unten in
Abschnitt 5 — und ist der wichtigere Teil dieses Berichts.

*Der Kopf sagte bis 2026-09-17 „zwei stehen aus" und widersprach damit Abschnitt 3.
Nachgezogen — dieselbe Sorte Selbstwiderspruch war heute schon dreimal zu bereinigen.*

**Gelöscht wurde nichts.** Der Programmtext sagt: berichten, nichts ohne Einverständnis entfernen.

---

## 1. „Läuft der Test auch allein?" — vollständig durchgeführt

**Jede** der 127 Testdateien wurde einzeln in einem eigenen Wegwerf-Container gestartet.

| | |
|---|---|
| Dateien geprüft | **127** |
| halten auch allein | **125** |
| scheitern allein | **1** (zwei Tests darin) |
| Messaussetzer | 1 — **Fehler meines Werkzeugs**, siehe Abschnitt 4 |

### Der Befund ohne Befund gehört auch in den Bericht

Der AST-Zensus hatte **16 Stellen** gefunden, die `sys.modules` verändern — also die Modulwelt für
alle nachfolgenden Tests umbauen. Ich hatte damit gerechnet, dass daraus reihenfolgeabhängige Tests
werden. **Keine einzige davon erzeugt eine.** Meine Erwartung war düsterer als der Befund.

### Der eine Fund: `tests/unit/audit_2026_09/test_r2_g5_mech.py`

Zwei von 41 Tests darin scheitern allein:

- `test_r1_7_startup_step_keeps_updates_made_while_it_runs`
- `test_r1_7_startup_step_does_not_set_a_goal_at_max_level`

In der Gruppe sind beide grün (`tests/unit/audit_2026_09`: 564 grün).

**Sie scheitern nicht an ihrer eigenen Zusicherung, sondern schon am `import` in ihrer ersten
Zeile.** Die Kette ist neun Ebenen lang:

```
from app.bot.startup_steps import member_count
  → app/bot/__init__.py:12   → events.py
  → startup.py:16            → startup_steps/__init__.py:25
  → scheduler.py:12          → services/scheduling/__init__.py:13
  → scheduler.py:27          → services/docker_service/__init__.py:10
  → docker_utils.py:76       → _load_timeout_from_config(...) → load_config()

AttributeError: 'types.SimpleNamespace' object has no attribute 'get_config'
```

**Die Ursache liegt im Produktivcode, nicht im Test:** `docker_utils.py:76-80` ruft **fünfmal auf
Modulebene** `_load_timeout_from_config(...)` auf, und jeder dieser Aufrufe ruft `load_config()`.
Ein weiterer Fall steht in `progress_service.py:125` (`CFG = load_config()`), ein sechster in
`docker_utils.py:676` (`_CACHE_TTL = _get_cache_ttl()`). **Ein `import` sollte nichts tun.** Hier
liest er Konfiguration von der Platte — und kann dabei scheitern.

*Warum es in der Gruppe gutgeht — belegt, nicht vermutet:* `test_r2_g3_startup.py:42` importiert
`app.bot` auf **Modulebene**, `test_pkg_f_startup.py:148` innerhalb eines Tests. Beide stehen in der
alphabetischen Sammelreihenfolge **vor** `test_r2_g5_mech.py`, das als letzte Datei des Verzeichnisses
kommt. Wenn es an die Reihe kommt, liegt die ganze Kette längst in `sys.modules` und der
`load_config()`-Aufruf findet gar nicht mehr statt. Allein gestartet findet er statt — und trifft auf
die Attrappe, die die `ps`-Fixture bei `:104` erst *nach* dem Import setzt.

*Und das Sicherheitsnetz hat ein Loch:* `_load_timeout_from_config` fängt
`(ConfigLoadError, KeyError, ValueError, TypeError)`. Der `AttributeError` ist **durchgeschlüpft**.
Was `get_config()` sonst noch hinaufreichen kann, wurde **nicht** untersucht (Abschnitt 5).

**Einstufung nach „fällt es dem Nutzer auf":** Die beiden Tests sind nicht wertlos — sie prüfen
etwas Echtes, aber nur, solange jemand anderes vorher importiert hat. Der schwerere Teil ist der
Import mit Nebenwirkung. Im Betrieb ist die Konfiguration echt, der Fall also selten; scheitert er
aber, kommt er als `ImportError` tief in einer neunstufigen Kette statt als verständliche Meldung.

> **Behoben am 2026-09-17** — für `docker_utils.py`, nicht für `progress_service.py:125`
> (Begründung in Abschnitt 6). Die Werte laden jetzt beim ersten Zugriff statt beim Import.
> Der wartende Test kam zuerst und war rot mit genau diesem Stapel;
> `tests/spec/test_import_without_side_effects.py` hält das fest.
>
> **Der Wirkungsnachweis ist stärker als eine Mutation:** `test_r2_g5_mech.py` allein vorher
> 2 von 41 rot, nachher **41 grün — ohne dass ein einziger Test angefasst wurde**. Die
> Reihenfolgeabhängigkeit verschwand, weil ihre Ursache weg ist. Damit ist die Ursachenanalyse
> dieses Abschnitts nicht mehr erschlossen, sondern belegt.

---

## 2. Gegenprobe durch Zurückdrehen — nur stichprobenhaft

Während der Stufen 1 und 2 wurde für **jede** neue Zusicherung die Gegenprobe gefahren: erst den
Test rot sehen und den Grund prüfen, dann korrigieren. Zusätzlich wurde bei fünf Z7-Tests per
**Mutation** belegt, dass sie greifen.

Vom **Altbestand** wurde so genau **ein** Test von 3.962 geprüft — und **der war kaputt**:
`tests/unit/extended/test_docker_infra_gaps.py` steuerte denselben Fehlerpfad an wie ein neuer Test
und war seit jeher grün, weil sein `_bad_open` schon beim **Lesen** warf, lange vor dem Schreiben.
Der erste Reparaturversuch war wirkungslos; belegt wurde das erst durch eine Mutation.

**Aus einer einzigen Probe folgt über die übrigen 3.961 exakt nichts** — auch nicht, dass es dort
besser aussieht. Sie sagt nur: grün beweist nichts.

> **Korrektur, nachgetragen 2026-09-17.** Hier stand bis eben „drei von 3.962" und „Drei von 3.962
> erlauben keine Hochrechnung". Die Zahl war nie ausgezählt, sie stammte aus meiner Erinnerung an
> denselben Arbeitstag. Die Auszählung ergibt: Mutationsnachweise tragen drei `tests/spec`-Dateien —
> die sind **neu**, nicht Altbestand. Der einzige mutationsgeprüfte Altbestandstest ist
> `test_docker_infra_gaps.py`. Ein Treffer in `tests/unit/utils/test_crypto_cache.py:519`
> („Mutation isolation") ist ein Fehltreffer der Textsuche und beschreibt einen Schlüssel-Cache.
>
> *Beim Auszählen mitgefunden:* `tests/spec/test_z7_server_order_write.py` trägt **keinen**
> Mutationsvermerk, obwohl die Mutation nachweislich gefahren wurde (belegt in SPEC.md Z10-Abschnitt
> zu Z7). Vier Mutationen, drei vermerkt — dieselbe Lücke, nur in der Dokumentation.
>
> Damit ist dies die sechste Zahl dieses Programms, die ich aus dem Gedächtnis statt aus einer
> Messung übernommen hatte. Die fünf übrigen stehen in `STUFE0_BESTANDSAUFNAHME.md`.

---

## 3. Spiegeltests · Funktion gegen Aufrufstelle — durchgeführt (2026-09-17)

### 3a. Funktion gegen Aufrufstelle — **ein Befund, behoben**

`app/web/app_factory.py:create_app` setzt die Flask-Anwendung aus elf Schritten zusammen. Jeder
einzelne ist geprüft, die **Verdrahtung** war es nicht. Per Mutation belegt: Vier Schritte einzeln
entfernt, `tests/test_web_factory.py` blieb **jedes Mal grün** — darunter `install_csrf_protection`.
Der CSRF-Schutz konnte aus der Anwendung fallen, ohne dass die Suite es merkte.

*Warum die vorhandenen Tests blind waren:* `test_web_factory.py` prüft Flask-Instanz, `/health` und
`Content-Security-Policy` — damit ist `install_security_handlers` abgedeckt und sonst nichts.
`test_bundle3_security.py` **ersetzt** `register_blueprints` und `register_routes` per `monkeypatch`,
prüft also ausdrücklich nicht den echten Aufbau. `test_security_sast.py` importiert aus `app.web_ui`
und überspringt bei `ImportError`.

*Behoben* durch `tests/spec/test_app_factory_wiring.py`, per Mutation als wirksam belegt.

**Und der lehrreichste Fund der ganzen Stufe ist, dass meine erste Fassung dieses Tests selbst ein
Spiegeltest war.** Sie zog die Erwartungsliste aus den *Aufrufen innerhalb* von `create_app`. Fällt
ein Aufruf heraus, verschwindet er zugleich aus der Erwartung — der Test verglich die Datei mit sich
selbst und konnte nicht fehlschlagen. Bei denselben Mutationen blieb er grün. Der Wächter
`len(schritte) >= 8` fing es nicht: aus elf werden zehn, die Schwelle hält.
Zweite Fassung: Erwartung aus den **Importen**, abgegrenzt über die **Signatur des Herkunftsmoduls**.
Beides steht außerhalb des Prüflings.

### 3b. Spiegeltests — **ein Befund, berichtet**

*Wie gesucht wurde, und warum die erste Suche wertlos war:* Ein grobes Muster („Test liest Quelltext")
fand **60** Dateien. Die allermeisten sind Fehlalarme: `read_text` steht in fast jedem Z7-Test, weil er
eine **Datendatei in `tmp_path`** liest, um zu prüfen, ob sie nach einem Absturz noch vollständig ist —
das Gegenteil eines Spiegeltests. Eingeengt auf Lesevorgänge aus dem **Produktivbaum** bleiben **6**.

Die Grenze, die zählt: *Legitim* ist, eine Produktivdatei gegen eine Regel zu prüfen, die außerhalb
steht („kein nacktes `except:`", „keine zeichengleichen Zwillinge"). *Spiegel* ist, den Dateiinhalt
selbst zur Erwartung zu machen — dann fällt bei einer Änderung beides weg.

Fünf der sechs sind Vertragstests. Belegt statt behauptet: `test_settings_take_effect_everywhere.py`
wurde per Mutation geprüft — eine einzige zurückgedrehte Stelle macht ihn rot
(`docker_control.py:183`), wiederhergestellt wieder grün. Er **beißt**.

**Der eine Befund:** `tests/unit/audit_2026_09/test_pkg_d1_services.py:197-206` liest den Standardwert
`60` per Regex aus `scheduler_service.py` und vergleicht die Panel-Vorbelegung damit — **beide Seiten
aus derselben Quelle**. Gerettet wird er allein durch das angehängte `== "60"`, das die Erwartung von
außen festnagelt. Ohne dieses Literal wäre er ein reiner Spiegeltest. *Nicht korrigiert:* Der Test ist
im Ergebnis richtig, seine Bauart ist fragil. Das ist eine Entscheidung des Betreibers.

*Alte Fassung dieses Abschnitts:* „Beide Prüfungen der Stufe 3 stehen aus." — erledigt.

Die Datengrundlage aus dem AST-Zensus:

| Kategorie | Anzahl |
|---|---|
| gar keine Prüfung | 85 |
| nur triviale Prüfung (`is None`, `isinstance`, `len`) | 264 |
| Mock-Tautologie | 3 |
| `pytest.raises(Exception)` — fängt alles | 3 |
| übersprungen | 6 |
| **hohl insgesamt** | **361 von 4.017 (9,0 %)** |

Davon **134 allein in `tests/unit/extended/`** und **null in `tests/spec/`** — die 21 Dateien und 55
Tests dieses Programms haben den hohlen Anteil nicht vergrößert. Das ist kein Verdienst, sondern die
Mindestanforderung; es belegt aber, dass „erst Rot sehen, dann grün" Tests erzeugt, die der Zensus
nicht beanstandet.

> **Zahlenstand berichtigt 2026-09-17.** Hier stand 362 von 3.962 bei 113 Dateien. Das war der
> Zensus von gestern Nacht. Ich hatte ihn neu laufen lassen, danach aber die **alte** Ausgabedatei im
> Scratchpad ausgewertet statt der frischen im Projektverzeichnis — `audit_tests.py` schreibt ohne
> zweites Argument nach `./test_audit.json`. Aufgefallen ist es nur, weil eine Zahl sich nach 14
> gelöschten und 55 neuen Tests **nicht gerührt** hatte. Siebte Zahl dieses Programms, die aus einer
> überholten Quelle stammte.

### Entschieden: gelöscht wird nichts

Der Betreiber hat das Löschen wertloser Tests freigegeben. **Ich nutze die Freigabe nicht**, und das
ist eine begründete Entscheidung, keine Bequemlichkeit.

Die 85 Tests „ohne Prüfung" wurden nach der Länge ihres Rumpfes aufgeschlüsselt: 13 einzeilig, der
Rest 2 bis 12 Anweisungen. Die **dreizehn einzeiligen sind vollständig gelesen** — keiner ist leer.
Zwölf sichern zu, dass ein Aufruf nicht wirft (`_debug_time_conversion` mit kaputter Eingabe,
`_log_task_deletion` mit fehlenden Schlüsseln, `_perform_sync_cache_warmup` bei fehlendem Modul). Das
ist eine schwache, aber echte Zusicherung auf Pfaden, die sonst niemand berührt. Sie zu löschen
verbessert nichts und nimmt Abdeckung weg.

**Und einer ist besser als seine Kategorie:**
`test_animation_cache_service.py:728` setzt `side_effect=AssertionError("should not reach")` — der
Test **fällt um**, wenn der Code den verbotenen Pfad nimmt. Die Zusicherung steht in der Attrappe,
nicht in einem `assert`. Der Zensus sieht sie nicht.

**Das ist ein Befund über das Messwerkzeug selbst**, und er ist ausgezählt statt geschätzt:
**Drei** der 85 tragen ihre Zusicherung in einem `side_effect` und werden vom Zensus trotzdem als
„gar keine Prüfung" geführt — `test_animation_cache_service.py:701`, `:728` und `:1221`. Übrig
bleiben **82** ohne erkennbare Zusicherung.

`scripts/audit_tests.py` zählt `assert`, `pytest.raises`, `mock.assert_*`, `pytest.fail()` und
Helfer, die `assert*`/`verify*`/`check_*` heißen. Ein `side_effect=AssertionError(...)` steht in
keiner dieser Formen — die Zusicherung wandert in die Attrappe, und das Werkzeug sieht sie nicht.
Der Zensus unterschätzt die Abdeckung damit, statt sie zu überschätzen; das ist die harmlosere
Richtung, aber es ist eine Ungenauigkeit, und sie gehört benannt.

Die Kategorie „nur `mock.assert_*`" (65 Tests) zählt **nicht** als hohl — sie prüft die
**Aufrufstelle** und ist damit ein Vorzug, kein Mangel.

### Eine eigene Gattung, drei davon gelesen

Sieben der hohlen Tests in Risikonähe heißen `*_swallows_*`, `*_handles_bad_*` oder `*_is_caught`.
Ihr gesamter Rumpf ist: Funktion aufrufen, sie soll nicht werfen. Sie *können* fehlschlagen, nageln
aber nur fest, dass nichts fliegt — nie, ob das Wegräumen das **Richtige** tat.

Drei wurden vollständig gelesen, samt der Code-Stellen dahinter. **Ergebnis: keine der drei
Code-Stellen rechtfertigt einen Eingriff.** Der Befund sind die Tests, nicht der Code. Details und
die zwei Fehlreihungen, die mir dabei unterliefen, stehen in
`STUFE0_BESTANDSAUFNAHME.md`, Abschnitt zum Zensus.

---

## 4. Das Messwerkzeug war selbst kaputt

Dreimal meldete meine Auswertungsschleife „keine Messung" für eine Gruppe, die in Wahrheit
durchgelaufen war. Einmal wurde daraus stillschweigend eine um 447 zu niedrige Gesamtzahl.

**Ursache, vollständig bewiesen:** Die Schleife wertete mit `echo "$R" | grep` aus. Die Shell ist
zsh, und dessen eingebautes `echo` deutet Rückwärtsschrägstrich-Folgen aus. Die Datei
`tests/unit/services/mech/test_animation_cache_service.py` enthält einen parametrisierten Test, dessen
Name die Zeichenkette `\x00` trägt (`test_xor_is_symmetric[\x00\x01\x02\x03]`). `echo` macht daraus
ein **echtes NUL-Byte**; `grep` behandelt die Eingabe daraufhin als binär und gibt für Treffer
**nichts** mehr aus — nicht `0`, sondern leer.

Belegt an derselben Ausgabe: 0 NUL im Original → 1 NUL nach `echo` → `grep` ohne `-a` leer, mit `-a`
findet es die Zeile. Mit `printf '%s\n'`: 0 NUL, Zeile gefunden. Das erklärt auch, warum ausgerechnet
die drei Gruppen betroffen waren, die genau diese Datei enthalten.

**Behoben** und im Maßstab nachgewiesen: Vor der Korrektur meldete der Gesamtlauf
`FEHLENDE_MESSUNGEN=1`, danach `0` — bei 43 von 43 Gruppen mit je genau einem Zählwert.

**Aufgefallen ist es nur, weil vor jedem Lauf eine Zahl angesagt war.** Beim ersten Mal wich das
Ergebnis um 444 ab statt um 3. Ohne diese Vorhersage wäre es durchgegangen — der Wächter, der es
schließlich fing, existierte da noch nicht.

---

## 5. Was NICHT geprüft wurde

- **Praktisch der gesamte Altbestand** wurde nie per Mutation oder Zurückdrehen geprüft. Genau
  **ein** Test von damals 3.962 ist so geprüft worden (Abschnitt 2) — über die übrigen ist nichts
  bekannt außer: sie sind grün. Der Baum zählt heute 4.017 Testfunktionen in 134 Dateien; die 55
  hinzugekommenen sind sämtlich mit gesehenem Rot entstanden, was für den Altbestand nichts besagt.
  (Hier stand zunächst 3.959, dann 3.961 — beide aus überholten Zensus-Ständen.)
- **Was `get_config()` werfen kann.** Sein Rumpf enthält weder `raise` noch `except`; er reicht
  weiter, was `_migrate_legacy_config_if_needed`, `_loader_service.load_modular_config`,
  `_decrypt_token_if_needed` und der Cache-Dienst werfen. Diese vier wurden **nicht** gelesen.
  Belegt ist allein, dass der `AttributeError` durch das Netz in `docker_utils.py:69` schlüpfte.
- **Ob die sechs Importe mit Nebenwirkung im Betrieb je zuschlagen.** `progress/runtime.py:100-112`
  ist gegen `FileNotFoundError` und `json.JSONDecodeError` abgesichert; gegen `OSError` beim
  Schreiben nicht. Ob das im echten Betrieb erreichbar ist, wurde nicht ermittelt.
- **Die übrigen hohlen Tests** wurden gezählt und einsortiert, aber nicht einzeln gelesen. Von den
  361 sind 13 vollständig gelesen (die einzeiligen ohne Prüfung, Abschnitt 3) und 3 als vom Zensus
  falsch eingestuft belegt. Über die restlichen 345 sagt dieser Bericht nichts.
- **Ob weitere Zusicherungen in Attrappen stecken.** Gezählt wurde nur `side_effect=AssertionError`
  und `pytest.raises`. Andere Formen — ein `Mock`, dessen Rückgabe später verglichen wird, oder ein
  `autospec`, das eine falsche Signatur auffliegen ließe — sind nicht erfasst.

---

## 6. Vorschläge — zu entscheiden, nicht umgesetzt

1. ~~**Die sechs Importe mit Nebenwirkung entschärfen.**~~ **Erledigt am 2026-09-17** — für
   `docker_utils.py` (fünf Zeitwerte plus `_CACHE_TTL`), **nicht** für `progress_service.py:125`.
   Die Werte laden jetzt beim ersten Zugriff statt beim Import, über ein modulweites `__getattr__`
   (PEP 562); für jeden Leser sieht alles unverändert aus. Der wartende Test, den dieser Vorschlag
   noch vermisste, steht als `tests/spec/test_import_without_side_effects.py` und prüft in einem
   **eigenen Prozess**, dass ein `import` keine Konfiguration liest.
   *`progress_service.py:125` bleibt bewusst wie es ist:* Fünf Testdateien weisen
   `progress_service.CFG` von außen zu, es ist damit faktisch eine Schnittstelle. Es träge zu machen
   wäre kein Umbau ohne wartenden Test, sondern einer **gegen** fünf wartende Tests.
2. ~~**Die beiden reihenfolgeabhängigen Tests** würden dadurch von selbst allein laufen.~~
   **Bestätigt:** `test_r2_g5_mech.py` allein vorher 2 von 41 rot, nachher **41 grün — ohne dass ein
   einziger Test angefasst wurde**. Das ist der Wirkungsnachweis der Korrektur und zugleich der
   Beleg, dass die Ursachenanalyse dieses Berichts stimmte.
3. **Das Sicherheitsnetz in `_load_timeout_from_config`** fängt vier Ausnahmetypen. Ob das die
   richtigen sind, lässt sich erst sagen, wenn bekannt ist, was `get_config()` werfen kann.
4. **Reihenfolgeabhängigkeit dauerhaft messen.** Der Einzeldurchlauf über alle 127 Dateien war eine
   einmalige Aktion. Als wiederkehrende Prüfung würde er Rückfälle fangen — kostet aber 127
   Container-Starts.

**Stand 2026-09-17:** Punkt 1 und 2 sind umgesetzt und gemessen (siehe oben). Punkt 3 und 4 sind es
**nicht** — beide berühren Produktivcode oder Laufzeit und bleiben Entscheidungen des Betreibers.

*Punkt 1 wurde nicht in der Form umgesetzt, in der er hier ursprünglich stand.* Der Vorschlag nannte
sechs Stellen in einem Atemzug. Beim Nachzählen der Aufrufstellen zeigte sich, dass
`progress_service.CFG` von fünf Testdateien von außen zugewiesen wird und damit eine Schnittstelle
ist — der Vorschlag war dort schlecht, und er war es, weil ich ihn geschrieben hatte, ohne die
Aufrufstellen zu zählen. Umgesetzt wurde deshalb nur `docker_utils.py`.
