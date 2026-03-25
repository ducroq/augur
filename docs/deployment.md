# Deployment Guide

Complete step-by-step guide for deploying Augur to Netlify.

## Prerequisites

- GitHub account
- Netlify account (free tier works)
- Encryption keys from Energy Data Hub project

## Quick Deploy to Netlify

### Step 1: Fork Repository

```bash
git clone https://github.com/ducroq/augur.git
cd augur
```

### Step 2: Install Dependencies

```bash
npm install
```

### Step 3: Connect to Netlify

1. Go to [Netlify](https://netlify.com) and sign up/login
2. Click "New site from Git"
3. Select your forked repository
4. Netlify auto-detects `netlify.toml` configuration

### Step 4: Configure Environment Variables

In Netlify dashboard → Site Settings → Environment Variables:

- `ENCRYPTION_KEY_B64`: Your base64-encoded encryption key
- `HMAC_KEY_B64`: Your base64-encoded HMAC key

*(Same keys used in Energy Data Hub project)*

### Step 5: Deploy!

- Netlify automatically builds and deploys
- ⚡ First build: ~50s (fetches and decrypts data)
- ⚡ Subsequent builds: ~25s (uses cached data if fresh!)

## Local Development

### Setup

1. **Prerequisites**
   - [Hugo](https://gohugo.io/getting-started/installing/) v0.124.0+
   - Python 3.11+ with `cryptography` package
   - Node.js 16+ (for npm dependencies)

2. **Install Dependencies**
   ```bash
   npm install
   pip install cryptography
   ```

3. **Set Environment Variables**
   ```bash
   # Windows PowerShell
   $env:ENCRYPTION_KEY_B64 = "your_base64_key"
   $env:HMAC_KEY_B64 = "your_base64_key"

   # Linux/Mac
   export ENCRYPTION_KEY_B64="your_base64_key"
   export HMAC_KEY_B64="your_base64_key"
   ```

4. **Fetch Data**
   ```bash
   # Standard fetch (with caching)
   python decrypt_data_cached.py

   # Force fresh data
   python decrypt_data_cached.py --force
   ```

5. **Run Hugo Server**
   ```bash
   hugo server -D
   # Visit http://localhost:1313
   ```

## Automated Updates

### Setting up Build Hooks

To auto-rebuild when backend publishes new data:

1. **Create Netlify Build Hook**
   - Netlify dashboard → Build & deploy → Build hooks
   - Create hook named "Energy Data Update"
   - Copy webhook URL

2. **Add to Energy Data Hub**

   In `energydatahub/.github/workflows/collect-data.yml`:
   ```yaml
   - name: Trigger dashboard rebuild
     run: |
       curl -X POST -d {} ${{ secrets.NETLIFY_BUILD_HOOK }}
     continue-on-error: true
   ```

3. **Add Secret**
   - In energydatahub repo → Settings → Secrets
   - Add `NETLIFY_BUILD_HOOK` with the webhook URL

Now dashboard auto-updates daily after backend runs! 🎉

## Deployment Checklist

### Pre-Deployment

- [ ] All files committed to Git
- [ ] npm dependencies installed (`npm install`)
- [ ] Environment variables configured in Netlify
- [ ] Backup of previous configuration created
- [ ] Local tests pass (`test_optimization.bat`)

### During Deployment

- [ ] Push to GitHub
- [ ] Monitor Netlify build logs
- [ ] Watch for successful build completion
- [ ] Check for cache plugin initialization

### Post-Deployment Verification

- [ ] Visit dashboard URL
- [ ] Verify charts display correctly
- [ ] Check data timestamp is recent (< 24 hours)
- [ ] Test interactive features (zoom, hover)
- [ ] Verify price statistics are accurate
- [ ] Check mobile responsiveness

## Build Verification

### First Deploy (Expected: Cache Miss)

Look for in logs:
```
🔧 Installing Python dependencies...
📦 Fetching and decrypting energy data (with caching)...
Output file does not exist, decryption required

Fetching energy data from https://ducroq.github.io/energydatahub/...
Successfully fetched ... characters
Decrypting data...
✓ Energy data ready!
```

### Second Deploy (Expected: Cache Hit)

```bash
# Make a trivial change to trigger deploy
git commit --allow-empty -m "Test cache hit"
git push
```

Look for in logs:
```
🔧 Installing Python dependencies...
📦 Fetching and decrypting energy data (with caching)...
Cached data is X hours old (max: 24.0h)
✓ Using cached data (still fresh)
Skipping decryption - using cached data
✓ Energy data ready!
🏗️  Building Hugo site...
```

### Build Times

| Build | Type | Expected Time |
|-------|------|---------------|
| First (cache miss) | Data fetch + decrypt | ~50s |
| Second (cache hit) | Cached data | ~25s |
| Third (cache hit) | Cached data | ~25s |

**Success Criteria:**
- ✅ Cache hit builds are 40-60% faster
- ✅ Dashboard displays correctly
- ✅ No errors in deploy log

## Troubleshooting

### Build Fails with Decryption Error

**Symptoms:**
```
Error: Environment variable validation failed: ENCRYPTION_KEY_B64 is not set
```

**Solution:**
1. Verify keys in Netlify → Site Settings → Environment Variables
2. Ensure keys are base64-encoded
3. Keys must match Energy Data Hub keys

### Dashboard Shows No Data

**Symptoms:**
- Charts empty or not rendering
- Console shows fetch errors

**Solution:**
1. Check `/data/energy_price_forecast.json` exists
2. Verify Energy Data Hub is publishing correctly
3. Check browser console for JavaScript errors
4. Manually trigger Netlify rebuild

### Dashboard Shows Old Data

**Symptoms:**
- Timestamps > 24 hours old
- Missing today's prices

**Solution:**
1. Check Energy Data Hub GitHub Action ran at 16:00 UTC
2. Verify build hook triggered Netlify deploy
3. Force rebuild: Netlify → Clear cache and deploy
4. Check `static/data/energy_data_metadata.json` timestamp

### Cache Not Working

**Symptoms:**
- Every build shows "decryption required"
- Build times always ~50s

**Solution:**
1. Verify `npm install` completed
2. Check `netlify-plugin-cache` in `package.json`
3. Netlify → Deploys → Clear cache and deploy
4. Review deploy logs for cache plugin messages

## Rollback Procedure

If deployment causes problems:

### Quick Rollback (5 minutes)

```bash
cd C:/local_dev/augur

# Restore original files
cp netlify.toml.backup netlify.toml

# Commit rollback
git commit -m "Rollback to previous configuration"
git push origin main
```

### Verify Rollback

1. Check Netlify deploy log
2. Build times return to previous values
3. Dashboard displays correctly
4. No new errors introduced

## Monitoring

### Build Performance Tracking

Create a simple tracking log:

| Date | Deploy # | Type | Cache Hit? | Build Time | Data Age | Notes |
|------|----------|------|------------|------------|----------|-------|
| 2025-10-25 | 1 | Initial | No | 50s | Fresh | First deploy |
| 2025-10-25 | 2 | UI change | Yes | 25s | 1h | Cache working! |
| 2025-10-26 | 3 | Scheduled | No | 48s | Fresh | Daily update |

### Success Metrics

Track these over first week:

- **Average build time (cache hit):** ___ seconds (target: < 30s)
- **Average build time (cache miss):** ___ seconds (target: < 55s)
- **Cache hit rate:** ___% (target: > 80%)
- **Failed builds:** ___% (target: < 5%)

## Security Considerations

### Environment Variables

- Never commit encryption keys to Git
- Use Netlify's secure environment variable storage
- Rotate keys periodically for security

### Build Security

- Review Netlify build logs for sensitive data leaks
- Ensure data files are not committed to repository
- Use HTTPS for all data transfers

### Access Control

- Limit Netlify admin access
- Use separate environments for testing/production
- Monitor deployment logs regularly

## Support & Resources

- **[Optimization Guide](optimization.md)** - Performance and caching details
- **[Troubleshooting](troubleshooting.md)** - Common issues and solutions
- **[GitHub Issues](https://github.com/ducroq/augur/issues)** - Report bugs
- **[Netlify Documentation](https://docs.netlify.com/)** - Platform documentation

## Next Steps

After successful deployment:

1. Set up monitoring and alerts
2. Configure custom domain (if desired)
3. Enable automatic updates via build hooks
4. Review and optimize cache settings
5. Plan for future enhancements

---

**Deployment Status:** Ready for production

**Last Updated:** 2026-03-25
