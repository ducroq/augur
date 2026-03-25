# energyLiveData Features - Implementation Plan

**Created:** 2025-11-15
**Status:** Planning
**Target:** Incrementally enhance Augur with energyLiveData capabilities

---

## Executive Summary

This document outlines a **phased approach** to integrating valuable energyLiveData features into the existing Augur. Rather than building a separate backend service, we'll add features **incrementally** to the current client-side dashboard.

### What We Already Have ✅
- Energy Zero API integration (client-side)
- Forecast data visualization (encrypted, build-time)
- Multi-source data display
- Time range selection (24h, 48h, 7d)
- Auto-refresh (10-minute intervals)
- Modular JavaScript architecture

### What energyLiveData Would Add 🎯
- Grid status monitoring (TenneT imbalance data)
- Weather correlation (impact on pricing)
- Forecast vs actual comparison (validation metrics)
- Market transparency (wholesale vs consumer gap analysis)
- Real-time alerts (price thresholds, grid events)

---

## Feature Prioritization Matrix

| Feature | User Value | Technical Effort | Priority | Phase |
|---------|-----------|------------------|----------|-------|
| **Forecast vs Actual Comparison** | ⭐⭐⭐⭐⭐ | 🔧🔧 | **HIGH** | Phase 1 |
| **Grid Status Indicator** | ⭐⭐⭐⭐ | 🔧🔧 | **HIGH** | Phase 1 |
| **Price Gap Analysis** | ⭐⭐⭐⭐⭐ | 🔧🔧🔧 | **MEDIUM** | Phase 2 |
| **Weather Correlation** | ⭐⭐⭐ | 🔧🔧🔧🔧 | **MEDIUM** | Phase 2 |
| **Real-time Alerts** | ⭐⭐⭐⭐ | 🔧🔧 | **MEDIUM** | Phase 2 |
| **Air Quality Integration** | ⭐⭐ | 🔧🔧🔧 | **LOW** | Phase 3 |
| **15-min Data Collection** | ⭐⭐⭐ | 🔧🔧🔧🔧🔧 | **LOW** | Phase 3 |
| **Historical Archive** | ⭐⭐ | 🔧🔧🔧🔧 | **LOW** | Phase 3 |

Legend:
- ⭐ = User value (more stars = higher value)
- 🔧 = Technical effort (more wrenches = more complex)

---

## Phase 1: Quick Wins (1-2 weeks)

### 🎯 Goal
Add high-value, low-effort features that enhance existing dashboard with minimal infrastructure.

### Feature 1.1: Forecast vs Actual Comparison

**What:** Overlay actual prices (Energy Zero) against forecast predictions on the same chart.

**Value:**
- Users see forecast accuracy in real-time
- Educational value (how accurate are predictions?)
- Research potential (MAPE calculation, accuracy metrics)

**Implementation:**
```javascript
// In data-processor.js, add comparison trace
function createForecastVsActualTrace(forecast, actual) {
    // Match timestamps
    const matched = matchTimestamps(forecast, actual);

    // Calculate difference
    const differences = matched.map(point => ({
        timestamp: point.timestamp,
        forecast: point.forecast,
        actual: point.actual,
        diff: point.actual - point.forecast,
        diffPercent: ((point.actual - point.forecast) / point.forecast) * 100
    }));

    return {
        trace: createDifferenceTrace(differences),
        metrics: calculateAccuracyMetrics(differences)
    };
}
```

**UI Enhancement:**
- Add toggle: "Show Forecast vs Actual"
- Display accuracy metric (MAPE) in info card
- Highlight areas where forecast significantly differs

**Effort:** 🔧🔧 (2-3 days)
- Modify data-processor.js (timestamp matching logic)
- Add new trace type to chart
- Create accuracy metrics calculation
- Update UI with toggle and metrics display

**APIs Needed:** None (use existing Energy Zero + forecast data)

---

### Feature 1.2: Grid Status Indicator

**What:** Display current grid imbalance status from TenneT.

**Value:**
- Real-time grid health indicator
- Correlates with price volatility
- Educational (users understand grid balancing)

**Implementation:**
```javascript
// New module: grid-status.js
class GridStatusMonitor {
    async fetchTennetImbalance() {
        // TenneT publishes CSV data
        const url = 'https://www.tennet.org/english/operational_management/export_data.aspx';
        const data = await fetch(url); // Parse CSV

        return {
            systemImbalance: data.imbalance, // MW
            imbalancePrice: data.price,       // EUR/MWh
            direction: data.direction,        // 'short' or 'long'
            timestamp: new Date()
        };
    }
}
```

**UI Enhancement:**
- Add status indicator in header:
  - 🟢 Green: Balanced (±50 MW)
  - 🟡 Yellow: Moderate (50-200 MW)
  - 🔴 Red: High imbalance (>200 MW)
- Tooltip: "Grid is currently [short/long] by [X] MW"

**Effort:** 🔧🔧 (2-3 days)
- Create grid-status.js module
- Parse TenneT CSV data
- Add visual indicator to UI
- Update every 5-15 minutes

**APIs Needed:**
- TenneT System Imbalance (free, CSV format)
- No authentication required

---

### Feature 1.3: Enhanced Info Cards

**What:** Expand info cards with market intelligence.

**Current Info Cards:**
- Current price
- Min/Max in range
- Average price

**Enhanced Info Cards:**
```javascript
{
    currentPrice: 120.50,           // EUR/MWh
    forecastAccuracy: 8.2,          // MAPE %
    gridStatus: 'balanced',         // green/yellow/red
    priceGap: 45.30,               // Wholesale vs Consumer
    nextPriceChange: '+15.2%',     // Tomorrow vs today
    volatility: 'moderate'         // price volatility indicator
}
```

**Effort:** 🔧 (1 day)
- Extend info card logic in ui-controller.js
- Calculate new metrics
- Update HTML template

---

## Phase 2: Deep Integration (2-4 weeks)

### Feature 2.1: Price Gap Analysis (Wholesale vs Consumer)

**What:** Show the gap between wholesale prices (ENTSO-E) and consumer prices (Energy Zero).

**Value:**
- Market transparency (how much markup?)
- Policy relevance (regulatory insights)
- Research potential (price transmission studies)

**Implementation:**
```javascript
// Add ENTSO-E wholesale data source
async fetchENTSOEPrices() {
    const apiKey = ENTSOE_API_KEY; // Requires registration (free)
    const url = `https://web-api.tp.entsoe.eu/api?...`;

    return wholesalePrices; // EUR/MWh
}

// Calculate gap
function calculatePriceGap(wholesale, consumer) {
    return {
        gap: consumer - wholesale,      // EUR/MWh
        gapPercent: ((consumer - wholesale) / wholesale) * 100,
        components: {
            energy: wholesale,
            tax: consumer.tax,
            grid: consumer.grid_cost,
            margin: consumer.supplier_margin
        }
    };
}
```

**UI Enhancement:**
- New chart trace: "Wholesale Price" (different color)
- Visual gap shading between wholesale and consumer
- Info card: "Current markup: XX% (€XX/MWh)"

**Effort:** 🔧🔧🔧 (5-7 days)
- Register for ENTSO-E API (free)
- Create ENTSO-E data fetcher
- Add price gap calculation
- Create gap visualization (shaded area)
- Add component breakdown (tax, grid, margin)

**APIs Needed:**
- ENTSO-E Transparency Platform (free, requires registration)

---

### Feature 2.2: Weather Correlation

**What:** Display weather conditions alongside energy prices to show correlation.

**Value:**
- Educational (understand renewable impact)
- Predictive (cloudy days = higher prices?)
- Research (weather-price correlation studies)

**Implementation:**
```javascript
// Simple weather widget
async fetchCurrentWeather() {
    const url = `https://api.openweathermap.org/data/2.5/weather?q=Amsterdam&appid=${API_KEY}`;
    const weather = await fetch(url).then(r => r.json());

    return {
        temperature: weather.main.temp,
        windSpeed: weather.wind.speed,
        cloudCover: weather.clouds.all,  // % (affects solar)
        timestamp: new Date()
    };
}
```

**UI Enhancement:**
- Weather widget in corner:
  - Temperature: 15°C
  - Wind: 5.2 m/s (→ wind generation)
  - Cloud cover: 60% (→ solar impact)
- Optional: Overlay wind/solar generation on chart

**Effort:** 🔧🔧🔧🔧 (7-10 days)
- Register for OpenWeather API (free tier: 1000 calls/day)
- Create weather fetcher
- Design weather widget UI
- Optional: Fetch actual wind/solar generation (ENTSO-E)
- Show correlation metrics

**APIs Needed:**
- OpenWeather API (free tier available)
- Optional: ENTSO-E Generation data (free)

---

### Feature 2.3: Real-time Alerts

**What:** Notify users when significant events occur.

**Triggers:**
- Price exceeds threshold (e.g., >€200/MWh)
- Price drops below threshold (e.g., <€50/MWh)
- Grid imbalance exceeds limit
- Forecast error exceeds 20%

**Implementation:**
```javascript
class AlertManager {
    checkAlerts(currentData, thresholds) {
        const alerts = [];

        if (currentData.price > thresholds.priceHigh) {
            alerts.push({
                type: 'price_high',
                severity: 'warning',
                message: `High price alert: €${currentData.price}/MWh`,
                timestamp: new Date()
            });
        }

        return alerts;
    }
}
```

**UI Enhancement:**
- Alert banner at top of page (dismissible)
- Browser notification (if permission granted)
- Alert history in sidebar

**Effort:** 🔧🔧 (3-4 days)
- Create alert manager
- Add notification system
- UI for alert display
- User preferences (which alerts to show)

---

## Phase 3: Advanced Features (4-8 weeks)

### Feature 3.1: 15-Minute Data Collection Backend

**What:** Build GitHub Actions workflow to collect data every 15 minutes.

**Why Deferred:**
- Current dashboard works well with hourly data
- Significant infrastructure overhead
- Requires server-side processing
- Best suited for research, not consumer dashboard

**If Implemented:**
```yaml
# .github/workflows/collect-data.yml
name: Collect Energy Data
on:
  schedule:
    - cron: '*/15 * * * *'  # Every 15 minutes
jobs:
  collect:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Run collection script
        run: python scripts/collect_data.py
      - name: Encrypt and store
        run: python scripts/encrypt_and_publish.py
```

**Effort:** 🔧🔧🔧🔧🔧 (2-3 weeks)
- Create Python collection scripts
- Set up GitHub Actions
- Implement rolling data windows
- Create encrypted storage
- Test reliability

---

## Implementation Strategy

### Recommended Order

**Week 1-2: Phase 1 Quick Wins**
1. ✅ Fix timezone bug (immediate)
2. 🎯 Add Forecast vs Actual comparison
3. 🎯 Add Grid Status indicator
4. 🎯 Enhance info cards

**Week 3-4: Testing & Refinement**
- User testing of Phase 1 features
- Performance optimization
- Mobile responsiveness
- Create ADR for architecture decisions

**Week 5-6: Phase 2 (if value demonstrated)**
- Price gap analysis (ENTSO-E integration)
- Weather correlation
- Real-time alerts

**Month 3+: Phase 3 (research-focused)**
- 15-minute data collection
- Historical archive
- Advanced analytics

---

## Success Metrics

**Phase 1 Success:**
- Users can see forecast accuracy (MAPE displayed)
- Grid status indicator shows real-time data
- No performance degradation (<2s load time)
- User engagement increases (time on page)

**Phase 2 Success:**
- Price gap analysis reveals market transparency insights
- Weather correlation provides educational value
- Alert system reduces manual monitoring

**Phase 3 Success:**
- Research publications using collected data
- Community adoption (other developers use dashboard)
- Policy impact (pricing transparency advocacy)

---

## Risk Mitigation

### Technical Risks
- **API rate limits:** Use caching, respect limits, have fallbacks
- **API reliability:** Graceful degradation if source unavailable
- **Performance:** Lazy load features, optimize data processing

### Operational Risks
- **Complexity creep:** Stick to phased approach, don't over-engineer
- **Maintenance burden:** Automate testing, monitor API health
- **Feature bloat:** Only add features with demonstrated user value

---

## Cost Estimate

### Phase 1 (Quick Wins)
- **APIs:** Free (TenneT is free, Energy Zero is free)
- **Time:** 1-2 weeks solo development
- **Infrastructure:** $0 (client-side only)

### Phase 2 (Deep Integration)
- **APIs:**
  - ENTSO-E: Free (requires registration)
  - OpenWeather: Free tier (1000 calls/day)
- **Time:** 2-4 weeks solo development
- **Infrastructure:** $0 (still client-side)

### Phase 3 (Backend Collection)
- **APIs:** Same as Phase 2
- **Time:** 4-8 weeks development
- **Infrastructure:** $0 (GitHub Actions free tier sufficient)

**Total Cost:** €0-5/month (if exceeding API free tiers)

---

## Next Steps

### Immediate (This Week)
1. ✅ Create this implementation plan
2. 🎯 Fix timezone bug in chart-renderer.js
3. 🎯 Create ADR for energyLiveData feature integration strategy
4. 🎯 Implement Feature 1.1 (Forecast vs Actual) as proof of concept

### Short Term (Next 2 Weeks)
5. Implement Feature 1.2 (Grid Status indicator)
6. Enhance info cards (Feature 1.3)
7. User testing and feedback
8. Performance testing

### Medium Term (Month 2)
9. Evaluate Phase 1 success
10. Decide on Phase 2 features based on user feedback
11. Create research plan if academic value demonstrated

---

## See Also
- `archive/energyLiveData/docs/` - Original research and planning
- `docs/agents/SESSION_STATE.md` - Current project status
- `docs/decisions/` - ADRs for architectural decisions
- `CLAUDE.md` - Project overview and architecture

---

**Status:** Ready for implementation
**First Feature:** Forecast vs Actual Comparison (Feature 1.1)
**Estimated Start:** After timezone bug fix
