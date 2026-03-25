# ADR-003: Fix Netlify Build Cache Bypassing with --force Flag

**Date**: 2025-11-18
**Status**: Accepted
**Deciders**: User + Claude Code
**Tags**: deployment, caching, netlify, automation, bugfix

---

## Context

**What is the issue we're facing?**

The Augur relies on automated daily updates from energyDataHub:
1. energyDataHub collects fresh energy price data daily at 16:00 UTC
2. Encrypts and publishes data to GitHub Pages
3. Triggers Netlify webhook to rebuild the dashboard
4. Dashboard should display latest prices automatically

**The Problem:**
Despite successful data collection and webhook triggers, the deployed dashboard continued showing stale data (3 days old). Manual deployments with "Clear cache and retry" worked correctly, suggesting a caching issue.

**Investigation revealed:**
- energyDataHub was collecting and publishing fresh data ✓
- Webhook was triggering Netlify rebuilds ✓
- `netlify.toml` configured with `--force` flag ✓
- **But**: Dashboard still served old cached data ✗

## Decision

**What change are we proposing?**

Modify `decrypt_data_cached.py` to ensure the `--force` flag bypasses **both** age-based caching AND hash-based caching.

### The Root Cause

The caching script had two separate optimization layers:

1. **Age-based caching** (line 258): Skip decryption if data < 24 hours old
2. **Hash-based caching** (line 292): Skip decryption if encrypted data hash matches previous build

The `--force` flag correctly bypassed #1 but **NOT #2**. Here's what happened:

```python
# Line 258: --force bypassed this ✓
if not force_refresh and should_skip_decryption(output_path, metadata_path):
    logger.info("Skipping decryption - using cached data")
    return True

# Line 292: --force DID NOT bypass this ✗
if previous_hash == data_hash and os.path.exists(output_path):
    logger.info("Remote data unchanged (hash match), using existing decrypted data")
    return True  # Used OLD cached data from Netlify's cached static/data/ directory
```

### The Fix

**Before (line 292):**
```python
if previous_hash == data_hash and os.path.exists(output_path):
```

**After (line 292):**
```python
if not force_refresh and previous_hash == data_hash and os.path.exists(output_path):
```

**Enhanced logging (lines 299-304):**
```python
if force_refresh:
    logger.info(f"Force refresh enabled - re-decrypting data (hash: {data_hash[:16]}...)")
elif previous_hash:
    logger.info(f"Data has changed (hash: {data_hash[:16]}...)")
else:
    logger.info(f"First fetch (hash: {data_hash[:16]}...)")
```

## Consequences

### Positive Consequences

✅ **Automated updates work correctly**: Daily energyDataHub runs will now properly update the dashboard
✅ **No manual intervention needed**: No more "Clear cache and retry" required
✅ **Better observability**: Enhanced logging shows when force refresh is active
✅ **Minimal performance impact**: Hash check still prevents unnecessary decryption on regular builds
✅ **Preserves optimization**: Non-forced builds still benefit from intelligent caching

### Negative Consequences

⚠️ **Slightly longer build times**: Webhook-triggered builds will always decrypt (adds ~2-5 seconds)
⚠️ **No data staleness detection**: If energyDataHub fails but webhook still fires, we'll re-decrypt old data

### Mitigations

The negative consequences are acceptable because:
- Build time increase is negligible (2-5 seconds vs 30-60 second total build)
- energyDataHub has retry logic and monitoring
- The --force flag is only used on webhook triggers (production deployments), not PR previews

## Implementation

**Changes made:**
- Modified `decrypt_data_cached.py` lines 292, 299-304
- Committed in `56df2b5`
- Deployed to production automatically via GitHub Actions → Netlify

**Testing:**
- ✅ GitHub Actions build passed
- ✅ Next automated energyDataHub run (16:00 UTC daily) will validate the fix
- ✅ Manual test available: `gh workflow run collect-data.yml` in energyDataHub repo

## Alternative Approaches Considered

### 1. Remove Netlify build cache entirely
**Rejected**: Would slow down all builds unnecessarily. The cache is beneficial for dependencies and static assets.

### 2. Use different cache keys per deployment
**Rejected**: Overly complex for a simple flag bypass issue.

### 3. Remove hash-based optimization entirely
**Rejected**: Hash check is valuable for preventing unnecessary decryption when source data hasn't changed in non-forced scenarios.

### 4. Separate --force-decrypt flag
**Rejected**: Adds complexity. The existing --force flag should logically bypass all caching.

## Related Decisions

- **ADR-002**: Grid imbalance data belongs in energyDataHub (establishes the webhook pattern this fix supports)
- **ADR-001**: Amsterdam timezone handling (related data pipeline architecture)

## References

- Issue discovered: 2025-11-18
- energyDataHub repo: `collect-data.yml` workflow (lines 84-87: webhook trigger)
- Dashboard repo: `netlify.toml` (line 7: `--force` flag usage)
- Deployment: https://energy.jeroenveen.nl

---

**Monitoring**: Verify automated update works during next scheduled run (16:00 UTC / 18:00 CET daily)
