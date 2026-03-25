# ADR-002: Implement Grid Imbalance Data Collection in energyDataHub

**Date**: 2025-11-15
**Status**: Accepted
**Deciders**: User + Claude Code
**Tags**: architecture, data-collection, grid-analytics, energydatahub

---

## Context

**What is the issue we're facing?**

The Augur roadmap includes displaying TenneT grid imbalance data to provide users with:
- Real-time grid health indicators
- Historical imbalance patterns for predictive analysis
- Correlation between grid stress and energy price volatility

Initial consideration was to implement grid status as a client-side feature in Augur (Feature 1.2 from ENERGYLIVEDATA_FEATURES_PLAN.md). However, this raised the architectural question: **Where should data collection happen?**

**Forces:**
- Augur is a static Hugo site (client-side only, no backend)
- energyDataHub is already set up for multi-source data collection with robust infrastructure
- Grid imbalance data has research value (historical analysis, prediction models)
- Separation of concerns: Data collection vs visualization
- Reusability: Other projects could consume published grid data

---

## Decision

**What did we decide?**

We will implement **TenneT grid imbalance data collection in the energyDataHub repository**, not in Augur.

**Key aspects:**
- **Data Collection**: energyDataHub adds a new `TennetCollector` using the existing BaseCollector pattern
- **Publishing**: Grid imbalance data published as encrypted JSON to GitHub Pages (`grid_imbalance.json`)
- **Visualization**: Augur will consume the published data (Phase 2)
- **Reusability**: Any project can consume the grid imbalance endpoint

**Architecture:**
```
TenneT API
    ↓
energyDataHub/collectors/tennet.py
    ↓ (Daily at 16:00 UTC)
GitHub Pages: grid_imbalance.json (encrypted)
    ↓
Augur/decrypt_data.py
    ↓
Dashboard visualization (secondary Y-axis chart)
```

---

## Consequences

### Positive ✅

- **Separation of concerns**: Data collection stays in the backend, visualization in frontend
- **Robust infrastructure**: Leverages existing BaseCollector (retry logic, circuit breakers, caching)
- **Historical data**: energyDataHub automatically collects and archives historical imbalance data
- **Reusability**: Other projects can consume `grid_imbalance.json` endpoint
- **Security**: Grid data encrypted with same AES-CBC + HMAC-SHA256 as other sources
- **Testability**: energyDataHub has 49% test coverage, 177 tests - new collector will be tested
- **No dashboard complexity**: Dashboard remains simple (consume data, visualize)
- **Research enablement**: Historical imbalance data enables predictive modeling (Phase 3)

### Negative ❌

- **Cross-repo coordination**: Implementation split across two repositories
- **Build dependency**: Dashboard must wait for energyDataHub to publish data
- **Deployment complexity**: Two deployment pipelines (energyDataHub GitHub Actions, Augur Netlify)

### Neutral ⚪

- **Follows existing pattern**: Energy Zero data is already fetched from API, grid data will be similar
- **No new technology**: Uses existing Python collectors, JavaScript consumption

---

## Alternatives Considered

### Alternative 1: Implement Grid Status Client-Side in Dashboard

**Description:**
Add a JavaScript module in Augur that fetches TenneT data directly from their API in the browser.

**Pros:**
- Single repository (simpler coordination)
- Faster implementation (no backend changes)
- Real-time data (fetched on page load)

**Cons:**
- No historical data collection (browser can't store long-term data)
- CORS issues (TenneT API may not allow browser requests)
- No retry logic/circuit breaker (browser limitations)
- Not reusable by other projects
- No encryption/security layer
- Performance impact on dashboard load time

**Why rejected:**
Augur is designed as a lightweight visualization layer. Adding data collection responsibilities violates separation of concerns and loses the benefits of the existing robust collection infrastructure.

### Alternative 2: Create Separate Grid Data Service

**Description:**
Build a new microservice specifically for TenneT grid data collection.

**Pros:**
- Complete isolation (no impact on existing systems)
- Could scale independently
- Focused responsibility

**Cons:**
- Duplicate infrastructure (retry logic, encryption, publishing)
- More maintenance burden (3 repositories instead of 2)
- Over-engineering for single data source
- energyDataHub already has 8 collectors - adding a 9th is trivial

**Why rejected:**
energyDataHub already has the perfect infrastructure for this. Creating a separate service would be premature optimization and duplicate existing work.

### Alternative 3: Use energyLiveData Repository

**Description:**
Implement in the archived energyLiveData repository (which was originally planned for this type of feature).

**Pros:**
- Original vision for energyLiveData included grid status monitoring
- Documentation already exists

**Cons:**
- energyLiveData was never implemented (planning phase only)
- Archived for a reason (functionality moved to Augur/energyDataHub split)
- Would require building from scratch (no BaseCollector infrastructure)
- Violates the decision to archive it

**Why rejected:**
energyLiveData was archived because its core functionality (Energy Zero API) was already implemented in the energyDataHub + Augur architecture. Adding grid data to energyDataHub follows the established pattern.

---

## Implementation

**How will this decision be implemented?**

### Phase 1: energyDataHub Implementation (3-4 days)

**Repository**: `energyDataHub`

**Actions:**
1. Create `collectors/tennet.py` inheriting from BaseCollector
2. Implement TenneT API integration:
   - Endpoint: https://www.tennet.org/english/operational_management/export_data.aspx
   - Data: System imbalance (MW), imbalance price (EUR/MWh), direction (short/long)
   - Resolution: Hourly aggregation (TenneT publishes 4-second resolution)
3. Add unit tests (`tests/unit/test_tennet_collector.py`)
4. Update `data_fetcher.py` to include TennetCollector
5. Add encryption and publishing to `grid_imbalance.json`
6. Update GitHub Actions workflow
7. Deploy and verify data collection

**Data format:**
```json
{
  "version": "1.0",
  "tennet_imbalance": {
    "metadata": {
      "data_type": "grid_imbalance",
      "source": "TenneT TSO",
      "units": "MW",
      "country": "NL"
    },
    "data": {
      "2025-11-15T00:00:00+01:00": -45.2,
      "2025-11-15T01:00:00+01:00": 12.8
    }
  }
}
```

**Success criteria:**
- ✅ TennetCollector passes all tests
- ✅ Data published to GitHub Pages daily
- ✅ Encrypted data verified
- ✅ Circuit breaker and retry logic working

### Phase 2: Augur Visualization (2-3 days)

**Repository**: `Augur`

**Actions** (deferred until Phase 1 complete):
1. Update `decrypt_data.py` to fetch `grid_imbalance.json`
2. Create `static/js/modules/grid-status.js`
3. Add secondary Y-axis to Plotly chart (EUR/MWh left, MW right)
4. Add status indicator widget (🟢🟡🔴)
5. Make grid imbalance trace toggleable
6. Update documentation

**Timeline:**
- Week 1: energyDataHub implementation
- Week 2: Verify data collection, deploy
- Week 3: Augur visualization

---

## Related Decisions

- [ADR-001: Amsterdam Timezone Handling](./001-timezone-handling-strategy.md) - TenneT data must use same timezone pattern
- [ENERGYLIVEDATA_FEATURES_PLAN.md](../ENERGYLIVEDATA_FEATURES_PLAN.md) - Original feature roadmap (Feature 1.2)
- [AI_AUGMENTED_WORKFLOW.md](../agents/AI_AUGMENTED_WORKFLOW.md) - Agent system framework

---

## References

**energyDataHub:**
- Repository: `C:\Users\scbry\HAN\HAN H2 LAB IPKW - Projects - WebBasedControl\01. Software\energyDataHub`
- README: https://github.com/ducroq/energydatahub/blob/main/README.md
- BaseCollector: `collectors/base.py`
- Existing collectors: 8 sources (ENTSO-E, Energy Zero, EPEX, Elspot, OpenWeather, MeteoServer, Google Weather, Luchtmeetnet)

**TenneT TSO:**
- System Imbalance Data: https://www.tennet.org/english/operational_management/
- Export Data: https://www.tennet.org/english/operational_management/export_data.aspx
- Data Format: CSV (4-second resolution, hourly aggregation needed)
- API: Free, no authentication required

**Augur:**
- Repository: https://github.com/ducroq/Augur
- Live: https://energy.jeroenveen.nl
- Decryption: `decrypt_data.py`

---

## Notes

**Handoff to energyDataHub:**

This ADR documents the architectural decision. **Implementation will happen in the energyDataHub repository**.

**For the energyDataHub session, the context includes:**
1. **Goal**: Add TenneT grid imbalance data collection
2. **Pattern**: Use BaseCollector (same as other 8 collectors)
3. **Data source**: TenneT TSO system imbalance (free, no auth)
4. **Output**: Publish to `grid_imbalance.json` (encrypted)
5. **Next**: After data is publishing, return to Augur for visualization

**Open questions:**
- Should we collect 4-second resolution or hourly aggregation? (Recommend hourly for dashboard use case)
- Should we include activated reserves data? (TenneT also publishes reserve activation)
- Should we add imbalance price or just volume? (Recommend both - price correlates with energy prices)

**Future considerations:**
- Phase 3: Predictive modeling (grid imbalance → price forecast)
- Academic research potential (grid dynamics + renewable integration)
- Mobile app could show real-time grid status notifications

---

## Review History

| Date | Reviewer | Action | Notes |
|------|----------|--------|-------|
| 2025-11-15 | Claude Code | Created | Architectural decision for grid data |
| 2025-11-15 | User + Claude | Accepted | Proceed with energyDataHub implementation |

---

**Last Updated**: 2025-11-15
**Version**: 1.0

**Next Action**: Switch to energyDataHub repository for implementation
