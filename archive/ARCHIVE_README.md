# Archive Directory

This directory contains archived projects and documentation related to Augur.

## Contents

### energyLiveData/
**Archived:** 2025-11-15
**Original Repository:** https://github.com/ducroq/energyLiveData
**Status:** Planning/Research phase only (minimal implementation)

#### What It Was
A planned real-time data collection backend to complement Augur with:
- 15-minute interval data collection (GitHub Actions)
- Grid status monitoring (TenneT, ENTSO-E)
- Weather correlation data
- Forecast validation framework
- Market transparency analysis

#### Why Archived
The core functionality (Energy Zero API integration) was implemented **directly in Augur** client-side code instead of as a separate backend service. The planning documentation remains valuable for:
- Understanding the original architecture vision
- Reference for potential future enhancements
- Research context for Energy Zero integration decisions

#### Features Already in Augur
- ✅ Energy Zero API integration (`static/js/modules/api-client.js`)
- ✅ Multi-source data visualization
- ✅ Auto-refresh (10-minute intervals)
- ✅ Forecast + live data comparison

#### Potential Future Use
The documentation in `energyLiveData/docs/` contains valuable research on:
- Grid status monitoring implementation
- Weather API integration patterns
- Forecast validation methodologies
- Market analysis frameworks

These could be incrementally added if needed.

---

**See Also:**
- `docs/decisions/` for ADRs related to architecture decisions
- `docs/agents/SESSION_STATE.md` for current project status
