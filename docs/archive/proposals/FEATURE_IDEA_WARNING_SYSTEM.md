# Feature Idea: Warning/Alerting System

**Status:** Concept phase - not yet planned
**Created:** 2025-11-30

---

## Basic idea

A monitoring system that automatically issues warnings under certain conditions and optionally triggers actions:

- **CPU load**: Warning when very high for an extended period → optionally restart the container
- **RAM usage**: Warning when a threshold is exceeded
- **Idle detection**: Automatically stop a server after X hours of inactivity

---

## Architecture analysis

### AAS vs. Warning System - different paradigms

| | AAS (current) | Warning System (new) |
|---|---|---|
| **Trigger** | Discord messages | Docker metrics |
| **Mode** | Event-driven (reactive) | Polling-based (active) |
| **Source** | External (update bots) | Internal (Docker Stats API) |

### Technically feasible

**Pro:**
- Docker SDK provides CPU%, RAM, network I/O
- Could share the action layer (start/stop/restart)
- Reuse cooldowns & protected containers
- Notifications to a Discord channel

**Challenges:**
- **CPU "high for an extended period"** → needs state tracking (moving average, threshold duration)
- **Detecting "idle"** → What is idle? Network traffic? Player count? Very game-specific
- **Polling interval** → too frequent = overhead, too rare = spikes missed
- **False positives** → short spikes should not trigger actions

---

## Assessment

**Significant scope expansion:**
- DDC = "Discord-based Docker control"
- Warning System = "monitoring system" → a different product category
- Tools such as Prometheus, Uptime Kuma, cAdvisor already do this well

**Recommendation:** If at all, then as a separate, optional module - do not weave it into AAS.

---

## Open questions

- [ ] Define the main use case (game server idle?)
- [ ] Distinction from existing monitoring tools
- [ ] Polling interval and performance impact
- [ ] Idle definition per container type

---

## Next steps

Waiting for further requirements and prioritisation.
