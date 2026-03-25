# Architecture Documentation

## System Overview

Augur is a static web application that visualizes real-time energy price forecasts for the Netherlands. The system consists of three main components working together to provide secure, performant data visualization.

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│              Energy Data Hub (Backend Repo)                  │
│  GitHub Actions (Daily 16:00 UTC)                           │
│  ├── Collect from 7+ APIs                                   │
│  ├── Validate & normalize to Europe/Amsterdam timezone      │
│  ├── Encrypt with AES-CBC + HMAC                            │
│  └── Publish to GitHub Pages                                │
└────────────────────┬────────────────────────────────────────┘
                     │
              [GitHub Pages]
                     │ (encrypted JSON)
                     │
┌────────────────────▼────────────────────────────────────────┐
│           Augur (This Repo)                                   │
│  Netlify Build (Triggered by webhook)                       │
│  ├── Fetch encrypted forecast data                          │
│  ├── Check cache (skip if < 24h old) ⚡                     │
│  ├── Decrypt with same keys                                 │
│  ├── Generate Hugo static site                              │
│  └── Deploy to CDN                                           │
│                                                              │
│  Client-Side (Browser)                                       │
│  ├── Load decrypted forecast data (ENTSO-E, EPEX, Elspot)  │
│  ├── Fetch live Energy Zero API (every 10 min)              │
│  ├── Render combined chart with Plotly.js                   │
│  └── Update statistics and UI                                │
└──────────────────────────────────────────────────────────────┘
```

## Components

### 1. Data Collection (Energy Data Hub)

**Location:** Separate repository (energydatahub)
**Responsibility:** Collect, encrypt, and publish energy market data

**Process:**
1. GitHub Actions workflow runs daily at 16:00 UTC
2. Collects data from multiple APIs:
   - ENTSO-E Transparency Platform
   - Energy Zero API
   - EPEX SPOT
   - Nord Pool Elspot
3. Normalizes to Europe/Amsterdam timezone
4. Encrypts with AES-CBC-256 + HMAC-SHA256
5. Publishes to GitHub Pages

**Technologies:**
- Python 3.11+
- GitHub Actions
- GitHub Pages for static hosting

### 2. Build Process (This Repository)

**Location:** This repository (augur)
**Responsibility:** Decrypt data and build static site

**Process:**
1. Triggered by webhook or manual deploy
2. Fetches encrypted data from GitHub Pages
3. Checks cache for freshness (< 24h)
4. Decrypts data if needed
5. Generates static Hugo site
6. Deploys to Netlify CDN

**Technologies:**
- Hugo v0.124.0+ (static site generator)
- Python 3.11+ (decryption)
- Netlify (hosting and build)
- Node.js 16+ (build plugins)

### 3. Client-Side Application

**Location:** Browser
**Responsibility:** Interactive data visualization

**Process:**
1. Loads decrypted forecast data from `/data/energy_price_forecast.json`
2. Fetches live Energy Zero data directly from API
3. Normalizes units (EUR/kWh → EUR/MWh)
4. Handles timezone conversions
5. Renders interactive Plotly.js charts
6. Auto-refreshes Energy Zero data every 10 minutes

**Technologies:**
- Vanilla JavaScript (ES6+)
- Plotly.js v2.26.0
- Custom CSS (glassmorphism design)

## Data Flow

### 1. Data Collection Flow

```
ENTSO-E API ─┐
Energy Zero ─┼─→ Data Hub ─→ Validate ─→ Encrypt ─→ GitHub Pages
EPEX SPOT ───┤                           (AES-CBC)
Nord Pool ───┘                           + HMAC
```

### 2. Build-Time Flow

```
GitHub Pages ─→ Fetch ─→ Cache Check ─┬─→ Use Cached ─┐
                                       │               │
                                       └─→ Decrypt ────┤
                                                       │
                                                       ├─→ Hugo Build ─→ Netlify CDN
```

### 3. Runtime Flow

```
Browser ─→ Load Static Site ─→ Fetch Decrypted Data ─┐
                                                       ├─→ Combine ─→ Plotly.js ─→ Display
         ┌─────────────────────────────────────────────┘
         └─→ Fetch Energy Zero API (live) ─────────────┘
```

## Security Architecture

### Encryption Layer

**Algorithm:** AES-CBC with 256-bit keys
**Integrity:** HMAC-SHA256 signatures
**Key Storage:** Environment variables (Netlify)

```python
# Encryption (Energy Data Hub)
encrypted_data = AES-CBC(data, encryption_key)
signature = HMAC-SHA256(encrypted_data, hmac_key)
output = {
    "encrypted_data": base64(encrypted_data),
    "signature": base64(signature)
}

# Decryption (Dashboard Build)
verify(signature, encrypted_data, hmac_key)  # Verify integrity
data = AES-CBC-decrypt(encrypted_data, encryption_key)
```

### Data Protection

1. **At Rest:**
   - Encrypted on GitHub Pages
   - Decrypted only during build
   - No sensitive data in Git repository

2. **In Transit:**
   - HTTPS for all API calls
   - Encrypted data over public CDN
   - Decrypted data over Netlify HTTPS

3. **At Runtime:**
   - Decrypted data in browser memory only
   - No data persistence client-side
   - No user tracking or data collection

## Performance Architecture

### Build Optimization

**Intelligent Caching:**
```python
if cached_data_age < 24 hours:
    if remote_hash == cached_hash:
        ✅ Use cached data (instant!)
        return cached_data
    else:
        🔄 Fetch & decrypt (data changed)
else:
    🔄 Fetch & decrypt (stale cache)
```

**Benefits:**
- 50-70% faster builds for UI changes
- 80-90% reduction in API calls
- Better developer experience

See [Optimization Guide](optimization.md) for details.

### Runtime Optimization

**Client-Side:**
- Lazy loading for interactive features
- Efficient data structures (Maps vs Objects)
- Debounced event handlers
- Smart re-rendering strategies

**CDN Delivery:**
- Netlify global CDN
- Gzip/Brotli compression
- Cache headers optimization
- Edge network distribution

## Data Architecture

### Data Sources

| Source | Provider | Units | Update Frequency | Coverage |
|--------|----------|-------|------------------|----------|
| ENTSO-E | European TSOs | EUR/MWh | Daily | Day-ahead prices |
| Energy Zero | Dutch provider | EUR/kWh | Hourly | Real-time + forecast |
| EPEX SPOT | Power Exchange | EUR/MWh | Daily | Auction prices |
| Nord Pool Elspot | Nordic market | EUR/MWh | Daily | Day-ahead prices |

### Data Format

**Encrypted Format (GitHub Pages):**
```json
{
  "encrypted_data": "base64_encrypted_content",
  "signature": "base64_hmac_signature"
}
```

**Decrypted Format (Dashboard):**
```json
{
  "version": "2.0",
  "entsoe": {
    "metadata": {
      "source": "ENTSO-E Transparency Platform",
      "units": "EUR/MWh",
      "timezone": "Europe/Amsterdam"
    },
    "data": {
      "2025-10-25T00:00:00+02:00": 102.14,
      "2025-10-25T01:00:00+02:00": 98.50
    }
  }
}
```

### Timezone Handling

**Standard:** All timestamps use Europe/Amsterdam timezone
**Format:** ISO 8601 with explicit offset (`+02:00` or `+01:00`)

**Known Issue:** Elspot data may have malformed offsets (`+00:09`)
**Workaround:** Client-side normalization in `chart.js`
**Status:** Tracked in [Backend Issues](backend-issues.md)

## Frontend Architecture

### Component Structure

```
layouts/
├── _default/
│   └── baseof.html          # Base template
└── index.html               # Main dashboard

static/
├── css/
│   └── style.css            # Styling
├── js/
│   ├── chart.js             # Main dashboard class
│   └── dashboard.js         # UI controls
└── data/                    # Generated at build time
    ├── energy_price_forecast.json
    └── energy_data_metadata.json
```

### Main Classes

**EnergyDashboard (chart.js):**
```javascript
class EnergyDashboard {
  constructor()              // Initialize chart
  loadEnergyData()           // Load decrypted forecast
  loadEnergyZeroData()       // Fetch Energy Zero API
  processEnergyDataForChart() // Normalize and prepare traces
  updateChart()              // Render with Plotly
  applyTimeRange()           // Handle time filtering
}
```

### State Management

**No framework:** Vanilla JavaScript with class-based state
**State stored in:**
- `this.energyData` - Decrypted forecast data
- `this.energyZeroData` - Live API data
- `this.currentThreshold` - User-selected price threshold

**Updates trigger:**
- Chart re-rendering
- Statistics recalculation
- UI updates

## Build Architecture

### Netlify Configuration

```toml
[build]
  command = """
    pip install cryptography &&
    python decrypt_data_cached.py &&
    hugo --minify
  """
  publish = "public"

[[plugins]]
  package = "netlify-plugin-cache"
  [plugins.inputs]
    paths = ["static/data"]
```

### Build Contexts

1. **Production (main branch):**
   - Full optimization
   - Cache enabled
   - Minification on

2. **Deploy Preview (PRs):**
   - Same as production
   - Useful for testing changes

3. **Branch Deploys:**
   - Can force fresh data with `--force` flag

### Environment Variables

Required in Netlify:
- `ENCRYPTION_KEY_B64` - AES encryption key (base64)
- `HMAC_KEY_B64` - HMAC signature key (base64)

## Integration Points

### Webhook Integration

Energy Data Hub triggers dashboard rebuild:

```yaml
# In energydatahub/.github/workflows/collect-data.yml
- name: Trigger dashboard rebuild
  run: |
    curl -X POST -d {} ${{ secrets.NETLIFY_BUILD_HOOK }}
```

### API Integration

**Energy Zero API (client-side):**
```javascript
const response = await fetch(
  'https://api.energyzero.nl/v1/energyprices',
  {
    params: {
      fromDate: '2025-10-25',
      tillDate: '2025-10-26',
      interval: 4  // Hourly
    }
  }
);
```

**Timezone Correction:**
```javascript
// Energy Zero returns UTC, convert to NL time (+2h)
const utcTimestamp = new Date(pricePoint.readingDate);
const localTimestamp = new Date(
  utcTimestamp.getTime() + (2 * 60 * 60 * 1000)
);
```

## Scalability Considerations

### Current Limitations

- Single region (Netherlands)
- Daily data updates (16:00 UTC)
- Client-side processing only
- No historical data storage

### Future Scalability

**Multi-Region:**
- Extend to other European markets
- Region-specific data endpoints
- Timezone-aware UI

**Real-Time:**
- WebSocket integration for live updates
- Server-side event streaming
- Incremental data updates

**Storage:**
- Historical data warehouse
- Trend analysis capabilities
- Long-term archival

## Monitoring & Observability

### Build Monitoring

- Netlify deploy logs
- Build time metrics
- Cache hit/miss rates
- Error tracking

### Runtime Monitoring

- Netlify Analytics (optional)
- Browser console errors
- API availability checks
- Performance metrics

### Alerting

**Build Failures:**
- Email notifications from Netlify
- GitHub Action status checks

**Data Issues:**
- Manual monitoring of data freshness
- Validation checks in build process

## Disaster Recovery

### Backup Strategy

**Code:**
- Git repository (primary)
- GitHub (remote backup)

**Data:**
- GitHub Pages (encrypted backup)
- Netlify cached data (temporary)

**Configuration:**
- Environment variables documented
- Keys stored securely offline

### Recovery Procedures

**Build Failure:**
1. Check Netlify logs
2. Verify environment variables
3. Rollback to last working commit
4. Force rebuild with cache clear

**Data Corruption:**
1. Use cached data as fallback
2. Force fresh data fetch
3. Contact Energy Data Hub maintainer

**Complete Outage:**
1. Deploy to alternative platform (Vercel, GitHub Pages)
2. Update DNS if using custom domain
3. Verify environment variables in new platform

## Related Documentation

- [Deployment Guide](deployment.md) - Step-by-step deployment
- [Optimization Guide](optimization.md) - Performance details
- [Backend Issues](backend-issues.md) - Known backend problems
- [Main README](../README.md) - Project overview

---

**Last Updated:** 2026-03-25
**Architecture Version:** 2.0
