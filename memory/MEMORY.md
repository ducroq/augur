# Memory

## Topic Files

| File | When to load | Key insight |
|------|-------------|-------------|
| `memory/gotcha-log.md` | Stuck or debugging | Problem-fix archive |
| `memory/data-formats.md` | Working with energyDataHub data | Schema v2.1 structure, units, timezone conventions |
| `memory/ml-decisions.md` | ML architecture choices | Why XGBoost first, why week-ahead, online learning rationale |

## Current State

- Restructured from energyDataDashboard to Augur (2026-03-25)
- Dashboard: production on Netlify, modular JS architecture in place
- ML pipeline: scaffolded (`ml/`), not yet wired to data — Phase 1 (XGBoost baseline) is next
- energyDataHub: stable, collecting daily, ~160 days of history

## Recently Promoted

- (none yet — framework just adopted)

## Key File Paths

| Path | Why it matters |
|------|---------------|
| `ml/features/builder.py` | First file to implement for Phase 1 — needs energyDataHub JSON wiring |
| `decrypt_data_cached.py` | The --force flag is critical for webhook builds (see ADR-003) |
| `netlify.toml` | Build pipeline — will need `python -m ml.inference` added after Phase 1 |

## Active Decisions

- ADR-001: Timezone handling strategy — use `Intl.DateTimeFormat` with Europe/Amsterdam, not hardcoded offsets
- ADR-003: Netlify cache --force flag fix — ensures webhook-triggered builds always decrypt fresh data
- Adopted agent-ready-projects v1.2.0 framework for project structure (2026-03-25)
- Week-ahead (168h) prediction horizon chosen over day-ahead for practical scheduling value
- XGBoost batch baseline before River online learning — need working baseline first
