# TODO: Repository Cleanup Required

**Date Created**: 2025-11-18
**Priority**: Medium
**Estimated Effort**: 1-2 hours

---

## Overview

The Augur repository has accumulated technical debt and organizational issues that should be addressed before major feature development continues. This document outlines cleanup tasks to improve maintainability and developer experience.

## Problems Identified

### 1. Duplicate/Redundant Python Scripts

**Current State:**
- `decrypt_data.py` (6.5 KB) - Original decryption script
- `decrypt_data_cached.py` (12.6 KB) - Cached version with intelligent optimization
- `refresh_dashboard_data.py` (2.7 KB) - Purpose unclear, possibly redundant

**Issues:**
- Confusion about which script to use
- `decrypt_data.py` is no longer used in production (netlify.toml uses cached version)
- Potential for changes to one without updating the other
- `refresh_dashboard_data.py` needs evaluation

**Questions to Answer:**
- Can we delete `decrypt_data.py` entirely?
- Is `refresh_dashboard_data.py` still needed?
- Should we rename `decrypt_data_cached.py` to just `decrypt_data.py`?

### 2. Documentation Sprawl

**Current State:**
```
docs/
├── agents/              # Agent system docs
├── decisions/           # ADRs (good!)
├── architecture.md
├── backend-issues.md
├── deployment.md
├── ENERGYLIVEDATA_FEATURES_PLAN.md
├── optimization.md
├── README.md
├── REFACTORING_SUMMARY.md
├── SECURITY.md
└── visualizer_documentation.md
```

**Issues:**
- Multiple overlapping docs (architecture.md, deployment.md, README.md)
- Unclear which docs are current vs historical
- No clear hierarchy or navigation
- Some docs may be outdated after recent changes

**Needs:**
- Consolidate overlapping documentation
- Create a docs index/navigation
- Archive or delete outdated content
- Ensure ADRs are the source of truth for decisions

### 3. Archive Directory

**Current State:**
```
archive/
├── ARCHIVE_README.md
└── energyLiveData/
```

**Questions:**
- What's in `energyLiveData/`?
- Is this content still referenced anywhere?
- Can it be deleted or moved elsewhere?

### 4. Build Artifacts and Cache

**Current State:**
- `public/` directory (Hugo build output)
- `node_modules/` (NPM dependencies)
- `__pycache__/` (Python cache)
- `.hugo_build.lock`

**Issues:**
- `public/` should be in `.gitignore` but is tracked
- Check if all build artifacts are properly ignored

### 5. Configuration Files

**Current State:**
- `hugo.toml` - Hugo config
- `netlify.toml` - Deployment config
- `package.json` - NPM config
- `config/` directory - Purpose unclear

**Questions:**
- What's in `config/` directory?
- Is it redundant with `hugo.toml`?
- Should configs be consolidated?

### 6. Scripts Organization

**Current State:**
```
scripts/
├── test_optimization.bat
└── test_optimization.sh
```

**Questions:**
- Are these scripts still used?
- Should Python scripts also be in `scripts/`?
- Need developer documentation for these

## Recommended Cleanup Tasks

### Phase 1: File Organization (30 minutes)

- [ ] Review and decide on Python script consolidation
  - Keep: `decrypt_data_cached.py` (possibly rename)
  - Evaluate: `decrypt_data.py`, `refresh_dashboard_data.py`

- [ ] Check `.gitignore` completeness
  - [ ] Ensure `public/` is ignored (build output)
  - [ ] Ensure `__pycache__/` is ignored
  - [ ] Add any missing patterns

- [ ] Investigate `config/` directory
  - Document purpose or delete if redundant

- [ ] Evaluate `archive/` directory
  - Delete or document what's being preserved

### Phase 2: Documentation Consolidation (45 minutes)

- [ ] Create `docs/README.md` as documentation index
- [ ] Review each doc file for:
  - Current relevance
  - Accuracy after recent changes
  - Overlap with other docs

- [ ] Consolidate or archive:
  - [ ] `architecture.md` - Still accurate?
  - [ ] `backend-issues.md` - Convert to GitHub issues?
  - [ ] `deployment.md` - Merge with CLAUDE.md?
  - [ ] `REFACTORING_SUMMARY.md` - Historical, can archive?
  - [ ] `visualizer_documentation.md` - Still relevant?

- [ ] Update `CLAUDE.md` to be the primary developer guide
- [ ] Ensure ADRs are up to date

### Phase 3: Code Cleanup (15 minutes)

- [ ] Remove commented-out code in workflows
- [ ] Verify all scripts have proper docstrings
- [ ] Check for unused imports
- [ ] Run linters (if not already set up)

### Phase 4: Testing & Validation (30 minutes)

- [ ] Test local development still works
- [ ] Verify GitHub Actions still pass
- [ ] Confirm Netlify builds successfully
- [ ] Check all documentation links work

## Tools to Use

Claude Code has specialized agents for cleanup tasks:

- **File organization**: Use file operations to move/delete
- **Documentation review**: Read and consolidate docs
- **Code cleanup**: Search for TODOs, remove dead code
- **Testing**: Run builds and validate changes

## Success Criteria

✅ Single source of truth for each concept (no duplicate docs)
✅ Clear file organization with obvious purposes
✅ All build artifacts properly ignored
✅ Documentation is current and accurate
✅ All builds and tests still pass
✅ Developer onboarding experience improved

## Next Steps

When starting the next work session on this repository:

1. **Start with this document**
2. **Use Claude Code cleanup agents**
3. **Work through phases sequentially**
4. **Commit cleanup changes separately from feature work**
5. **Update this document with findings and decisions**

---

**Note**: This cleanup should be done BEFORE starting new feature development to avoid conflicts and ensure a clean foundation.

**Related Documents**:
- ADR-003: Netlify cache fix (recent technical decision)
- CLAUDE.md: Primary developer guide
- ENERGYLIVEDATA_FEATURES_PLAN.md: Future roadmap (validate if still current)
