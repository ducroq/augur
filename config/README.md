# Configuration Files

This folder contains configuration files and templates for Augur.

## Structure

```
config/
├── README.md                    ← This file
├── secrets.ini.template         ← Template for local secrets (copy to local/)
├── backup/                      ← Configuration backups
│   ├── netlify.toml.backup
│   └── netlify.toml.optimized
└── local/                       ← Local secrets (GITIGNORED)
    └── secrets.ini              ← Your actual secrets (DO NOT COMMIT)
```

## Setup for Local Development

### 1. Create Your Secrets File

```bash
# Copy the template
cp config/secrets.ini.template config/local/secrets.ini

# Edit with your actual credentials
nano config/local/secrets.ini  # or use your preferred editor
```

### 2. Fill In Your Credentials

Edit `config/local/secrets.ini` with your actual:
- API keys (ENTSO-E, OpenWeather, etc.)
- Encryption keys
- Database credentials
- Server information

### 3. Verify It's Protected

```bash
# This should NOT show secrets.ini
git status

# This should show "config/local/" is ignored
cat .gitignore | grep "config/local"
```

## Security Notes

⚠️ **IMPORTANT:**
- `config/local/` is in `.gitignore`
- Never commit actual secrets to Git
- Use environment variables in production (Netlify)
- Keep backups of your secrets in a password manager

✅ **Safe to commit:**
- `secrets.ini.template` (example values only)
- This README
- Configuration backups (no secrets)

❌ **Never commit:**
- `config/local/secrets.ini` (actual credentials)
- Any file with real API keys or passwords
- Private keys or certificates

## Production Configuration

For production deployments (Netlify), use environment variables instead:

**Netlify Dashboard → Site Settings → Environment Variables:**

```
ENCRYPTION_KEY_B64=your_base64_encryption_key
HMAC_KEY_B64=your_base64_hmac_key
```

## Configuration Backups

The `backup/` folder contains:
- Previous Netlify configurations
- Alternate configurations for testing
- Safe to keep for rollback purposes

## Need Help?

See [docs/SECURITY.md](../docs/SECURITY.md) for comprehensive security guidelines.
