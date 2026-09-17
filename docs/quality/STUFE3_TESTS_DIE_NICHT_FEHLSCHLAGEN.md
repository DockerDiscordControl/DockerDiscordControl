# Stufe 3 — Tests aussieben, die nicht fehlschlagen können

**Stand:** 2026-09-17 · **Teilbericht.** Von den vier Prüfungen der Stufe ist eine
vollständig durchgeführt, eine stichprobenhaft, zwei stehen aus. Was nicht geprüft wurde, steht
unten in Abschnitt 5 — und ist der wichtigere Teil dieses Berichts.

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

## 3. Spiegeltests · Funktion gegen Aufrufstelle — nicht durchgeführt

Beide Prüfungen der Stufe 3 stehen aus. Was vorliegt, ist die Datengrundlage aus dem AST-Zensus:

| Kategorie | Anzahl |
|---|---|
| gar keine Prüfung | 85 |
| nur triviale Prüfung (`is None`, `isinstance`, `len`) | 265 |
| Mock-Tautologie | 3 |
| `pytest.raises(Exception)` — fängt alles | 3 |
| übersprungen | 6 |
| **hohl insgesamt** | **362 von 3.962 (9,1 %)** |

Davon **45 in Geld-, Lösch- oder Rechte-Nähe**, **134 allein in `tests/unit/extended/`**.

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

- **Spiegeltests** und **Funktion gegen Aufrufstelle** — beide Prüfungen der Stufe 3 stehen aus.
- **3.961 der 3.962 Alttests** wurden nie per Mutation oder Zurückdrehen geprüft. Über sie ist
  nichts bekannt außer: sie sind grün. (Stand nach der Korrektur in Abschnitt 2 — hier stand
  zunächst 3.959, passend zur dort widerlegten Zahl.)
- **Was `get_config()` werfen kann.** Sein Rumpf enthält weder `raise` noch `except`; er reicht
  weiter, was `_migrate_legacy_config_if_needed`, `_loader_service.load_modular_config`,
  `_decrypt_token_if_needed` und der Cache-Dienst werfen. Diese vier wurden **nicht** gelesen.
  Belegt ist allein, dass der `AttributeError` durch das Netz in `docker_utils.py:69` schlüpfte.
- **Ob die sechs Importe mit Nebenwirkung im Betrieb je zuschlagen.** `progress/runtime.py:100-112`
  ist gegen `FileNotFoundError` und `json.JSONDecodeError` abgesichert; gegen `OSError` beim
  Schreiben nicht. Ob das im echten Betrieb erreichbar ist, wurde nicht ermittelt.
- **Die 359 übrigen hohlen Tests** wurden gezählt und einsortiert, aber nicht einzeln gelesen.

---

## 6. Vorschläge — zu entscheiden, nicht umgesetzt

1. **Die sechs Importe mit Nebenwirkung entschärfen.** `docker_utils.py:76-80`, `:676`,
   `progress_service.py:125`: Die Werte erst beim ersten Gebrauch laden statt beim Import. Das ist
   ein Eingriff in Produktivcode und braucht einen wartenden Test — den es noch nicht gibt.
2. **Die beiden reihenfolgeabhängigen Tests** würden dadurch von selbst allein laufen. Sie vorher
   zu ändern hieße, das Symptom zu behandeln.
3. **Das Sicherheitsnetz in `_load_timeout_from_config`** fängt vier Ausnahmetypen. Ob das die
   richtigen sind, lässt sich erst sagen, wenn bekannt ist, was `get_config()` werfen kann.
4. **Reihenfolgeabhängigkeit dauerhaft messen.** Der Einzeldurchlauf über alle 127 Dateien war eine
   einmalige Aktion. Als wiederkehrende Prüfung würde er Rückfälle fangen — kostet aber 127
   Container-Starts.

**Nichts davon ist umgesetzt.** Alle vier berühren Produktivcode oder Laufzeit und sind Entscheidungen
des Betreibers.
