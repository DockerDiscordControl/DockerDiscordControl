# Feature Idea: Warning/Alerting System

**Status:** Konzeptphase - Noch nicht geplant
**Erstellt:** 2025-11-30

---

## Grundidee

Ein Monitoring-System das bei bestimmten Bedingungen automatisch Warnungen ausgibt und optional Aktionen auslöst:

- **CPU-Last**: Warnung wenn längere Zeit sehr hoch → Optional Container-Neustart
- **RAM-Verbrauch**: Warnung bei Schwellenwert-Überschreitung
- **Idle-Detection**: Server nach X Stunden Inaktivität automatisch stoppen

---

## Architektur-Analyse

### AAS vs. Warning System - Unterschiedliche Paradigmen

| | AAS (aktuell) | Warning System (neu) |
|---|---|---|
| **Trigger** | Discord-Nachrichten | Docker Metriken |
| **Modus** | Event-driven (reaktiv) | Polling-based (aktiv) |
| **Quelle** | Extern (Update-Bots) | Intern (Docker Stats API) |

### Technisch machbar

**Pro:**
- Docker SDK liefert CPU%, RAM, Network I/O
- Könnte Action-Layer teilen (start/stop/restart)
- Cooldowns & Protected Containers wiederverwenden
- Benachrichtigungen an Discord-Channel

**Herausforderungen:**
- **CPU "längere Zeit hoch"** → Braucht Zustandstracking (gleitender Durchschnitt, Schwellenwert-Dauer)
- **"Idle" erkennen** → Was ist idle? Netzwerk-Traffic? Spieleranzahl? Sehr spielspezifisch
- **Polling-Intervall** → Zu häufig = Overhead, zu selten = Spikes verpasst
- **False Positives** → Kurze Spitzen sollten keine Aktionen auslösen

---

## Einschätzung

**Signifikante Scope-Erweiterung:**
- DDC = "Discord-basierte Docker-Steuerung"
- Warning System = "Monitoring System" → andere Produktkategorie
- Tools wie Prometheus, Uptime Kuma, cAdvisor machen das bereits gut

**Empfehlung:** Wenn überhaupt, dann als separates, optionales Modul - nicht in AAS einweben.

---

## Offene Fragen

- [ ] Hauptanwendungsfall definieren (Game-Server-Idle?)
- [ ] Abgrenzung zu existierenden Monitoring-Tools
- [ ] Polling-Intervall und Performance-Impact
- [ ] Idle-Definition pro Container-Typ

---

## Nächste Schritte

Warten auf weitere Anforderungen und Priorisierung.
