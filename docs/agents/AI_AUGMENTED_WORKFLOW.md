# AI-Augmented Development Workflow - Augur

**Purpose:** This document defines how AI assistants (Claude Code and others) should work on the Augur project. It establishes the philosophy, principles, and operational protocols for AI-augmented solo development.

**For AI Assistants:** Read this document at the start of each session to understand how to behave.

**For Humans:** This documents the "contract" between you and your AI assistant.

---

## Core Philosophy

### 1. Documentation Should Be Effortless

**Principle:** Documentation is maintained by AI, not humans.

**Why:** Documentation decay happens when it requires manual effort. If the AI assistant automatically maintains docs as a side effect of development work, documentation stays fresh without cognitive overhead.

**In practice:**
- Human: "Fix the timezone offset for the 'now' line"
- AI: Fixes the issue, offers to update docs
- Human: "Yes"
- AI: Updates SESSION_STATE.md, creates ADR if architectural change

### 2. Single Source of Truth

**Principle:** Configuration drives behavior, not hardcoded values.

**Why:** When information exists in multiple places, they drift out of sync. By making config files the authoritative source, scripts automatically stay correct when config changes.

**In practice:**
- Encryption keys in environment variables (`.env`)
- API endpoints in configuration
- Timezone offsets in timezone-utils.js
- Generic scripts read config, not hardcoded values

### 3. Progressive Disclosure

**Principle:** Load context as needed, not everything at once.

**Why:** AI context windows are limited. Loading entire codebases wastes tokens and time. Progressive disclosure (broad → specific) gets answers faster with relevant context only.

**In practice:**
- Start: Read SESSION_STATE.md (2k tokens)
- Navigate: Find relevant component (1k tokens)
- Detail: Read specific code section (5k tokens)
- Total: 8k tokens vs 50k+ for full codebase dump

### 4. Sandbox for Experiments

**Principle:** Git-ignored directories for friction-free experimentation.

**Why:** Fear of polluting git history stifles experimentation. Sandbox directories give freedom to try ideas, fail fast, and document learnings without committing garbage.

**In practice:**
- Risky idea → Work in `sandbox/2025-11-15_new_feature/`
- Success → Clean up, move to proper location, create ADR
- Failure → Document in `sandbox/failed/` with learnings

### 5. Architecture Decision Records

**Principle:** Significant decisions are documented with context, not just the outcome.

**Why:** Future developers (including yourself in 6 months) need to understand WHY decisions were made, not just WHAT was decided. ADRs capture the thinking.

**In practice:**
- Significant decision made in conversation
- AI offers: "Should I create an ADR for this?"
- ADR documents context, decision, consequences, alternatives

### 6. Agent-Assisted Quality Assurance

**Principle:** Complex validation tasks are delegated to specialized agents.

**Why:** Multi-step validation across many files is tedious and error-prone for humans. Agents can systematically validate data pipelines, test chart rendering, and catch issues.

**In practice:**
- After updating chart logic
- Human: "Validate chart rendering using Chart agent"
- Agent tests different time ranges, validates data sources
- Human reviews report, fixes issues

---

## Session Start Protocol

### When Starting a New Session

**1. Read Core Context (Required)**
```
Read: SESSION_STATE.md
Purpose: Understand current status, recent accomplishments, next steps
```

**2. Check Recent Changes (If applicable)**
```
Run: git status
Check: Any uncommitted work?
Run: git log -5 --oneline
Check: Recent commits since last session
```

**3. Scan Recent Decisions (If applicable)**
```
Read: docs/decisions/ (sort by date, read latest 2-3)
Purpose: Understand recent architectural decisions
```

**4. Orient the User**
```
Provide concise summary:
- Where we left off (from SESSION_STATE.md)
- Current status of key components
- Suggested next steps (from "Next Steps" section)
```

**Example:**
```
"Welcome back! Based on SESSION_STATE.md:

Current Status:
- Dashboard deployed and displaying energy prices
- Energy Zero API integration working with timezone fixes
- Chart supports 24h, 48h, 7d, and custom date ranges

Next Steps:
1. Investigate data source display issues
2. Add historical data comparison feature
3. Optimize chart performance for mobile

What would you like to work on?"
```

---

## During Development

### Proactive Behaviors

**1. Recognize Significant Decisions**

When the conversation involves:
- Choosing between architectural approaches
- Making trade-offs with long-term impact
- Establishing patterns or conventions
- Changing previous decisions

→ Offer to create an ADR:
```
"This seems like a significant architectural decision. Should I create an ADR documenting:
- Context: [brief context]
- Decision: [what we decided]
- Alternatives considered: [what we rejected and why]?"
```

**2. Suggest Documentation Updates**

After completing significant work:
- Created/modified JavaScript modules
- Changed data handling logic
- Resolved issues
- Completed features

→ Offer to update docs:
```
"I've completed [task]. Should I update the documentation?
- SESSION_STATE.md (add to accomplishments)
- CLAUDE.md (update usage examples)
- Create ADR if applicable"
```

**3. Use Progressive Context Loading**

When answering questions:
1. Start broad (SESSION_STATE.md, CLAUDE.md)
2. Navigate to relevant area (static/js/, decrypt_data.py, utils/)
3. Load specific context (relevant code sections only)
4. Synthesize answer with file:line references

**Don't:**
- Read entire files unless needed
- Load entire codebase for simple questions
- Dump large code blocks in responses

**4. Move Experiments to Sandbox**

When user wants to try something risky:
```
"This sounds like a good experiment for sandbox/. Want me to create
sandbox/2025-11-15_[experiment_name]/ for this?"
```

**5. Flag Potential Issues**

When you notice:
- Documentation getting stale
- Hardcoded values that should be in config
- Code duplication
- Missing tests or validation

→ Proactively mention it:
```
"I notice [issue]. Should we address this now or add it to the backlog?"
```

---

## Session End Protocol

### Before User Leaves

**1. Offer Final Documentation Update**
```
"Before you go, should I update SESSION_STATE.md with today's progress?
- Add accomplishments
- Update current status
- Refresh next steps"
```

**2. Suggest Commit Message (If work completed)**
```
"Ready to commit? Suggested message:
'Fix timezone offset for 'now' indicator line

- Updated timezone-utils.js to use Amsterdam offset
- Added constants for timezone offsets
- Tested with different time ranges
- Updated SESSION_STATE.md

🤖 Generated with [Claude Code](https://claude.com/claude-code)'
"
```

**3. Summarize Open Items**
```
"Summary of where we're at:
✅ Completed: [list completed items]
🚧 In Progress: [list partial work]
📋 Next: [list next steps]

See SESSION_STATE.md for details."
```

---

## Rules of Engagement

### Always

- ✅ Use progressive context loading (aim for 10-20k tokens)
- ✅ Offer to document significant decisions as ADRs
- ✅ Update SESSION_STATE.md at session end
- ✅ Move experiments to sandbox/ (git-ignored)
- ✅ Reference specific file:line locations when helpful
- ✅ Verify commands before running destructive operations
- ✅ Explain trade-offs when multiple approaches exist

### Never

- ❌ Dump entire files unless specifically asked
- ❌ Create documentation "just because" (pragmatic over dogmatic)
- ❌ Commit to git without user approval
- ❌ Make breaking changes without discussion
- ❌ Hardcode values that should be in config
- ❌ Duplicate code instead of making generic
- ❌ Leave documentation stale after significant changes
- ❌ Commit encryption keys or sensitive data

### When Uncertain

- 🤔 Ask clarifying questions instead of guessing
- 🤔 Offer options with trade-offs instead of dictating
- 🤔 Suggest searching docs before reading entire codebase
- 🤔 Propose experiments in sandbox/ for risky ideas

---

## Project-Specific Context: Augur

### Key Concepts

**1. Augur Energy Price Forecasting Platform**
- Purpose: Forecast and visualize energy prices in the Netherlands
- Data Sources: Energy Data Hub (encrypted forecasts), Energy Zero API (live data)
- Technology: Hugo static site generator + vanilla JavaScript + Plotly.js + XGBoost/River ML
- Deployment: Netlify with build-time data decryption

**2. Data Security**
- Encrypted data: `energy_price_forecast.json` encrypted with AES-CBC + HMAC-SHA256
- Build-time decryption: `decrypt_data.py` runs during Netlify build
- Environment variables: `ENCRYPTION_KEY_B64`, `HMAC_KEY_B64` (never commit!)
- See: `CLAUDE.md` for security model details

**3. Frontend Stack**
- Hugo 0.124.0 (static site generator)
- Vanilla JavaScript (no framework)
- Plotly.js (charting library)
- Modular architecture: `api-client.js`, `ui-controller.js`, `timezone-utils.js`

**4. Data Pipeline**
- **Fetch encrypted data:** Energy Data Hub GitHub Pages
- **Decrypt:** `decrypt_data.py` using `SecureDataHandler`
- **Build:** Hugo generates static site
- **Client-side:** Fetch decrypted JSON + live Energy Zero API data
- **Render:** Plotly.js charts with multi-source data

**5. Timezone Handling**
- Energy Zero API returns UTC timestamps
- Dashboard converts to Netherlands time (UTC+2 in summer, UTC+1 in winter)
- "Now" line uses Amsterdam timezone offset
- See: `static/js/modules/timezone-utils.js`

### Directory Structure

```
augur/
├── ml/                            # ML forecasting pipeline
│   ├── features/builder.py       # Feature engineering
│   ├── training/trainer.py       # Model training lifecycle
│   ├── models/                    # Trained artifacts (gitignored)
│   └── inference.py               # Build-time inference
├── docs/
│   ├── agents/                    # For AI assistants
│   │   ├── AI_AUGMENTED_WORKFLOW.md  # This file
│   │   ├── SESSION_STATE.md       # Current status (START HERE)
│   │   └── templates/             # Agent templates
│   ├── decisions/                 # Architecture Decision Records
│   ├── architecture.md
│   ├── deployment.md
│   └── SECURITY.md
├── layouts/
│   └── index.html                 # Main dashboard template
├── static/
│   ├── js/
│   │   ├── dashboard.js           # Main entry point
│   │   └── modules/
│   │       ├── api-client.js      # Data fetching
│   │       ├── ui-controller.js   # Chart rendering
│   │       └── timezone-utils.js  # Timezone conversions
│   ├── css/
│   │   └── style.css              # Glassmorphism styling
│   └── data/
│       └── energy_price_forecast.json  # Decrypted forecast data
├── utils/
│   ├── secure_data_handler.py     # Encryption/decryption
│   ├── timezone_helpers.py
│   └── data_types.py
├── decrypt_data_cached.py         # Build-time decryption script
├── hugo.toml                      # Hugo configuration
├── netlify.toml                   # Build configuration
├── CLAUDE.md                      # Project instructions
└── sandbox/                       # Git-ignored experiments
```

### Important Files

**Always read first:**
- `docs/agents/SESSION_STATE.md` - Current status, accomplishments, next steps

**Reference as needed:**
- `CLAUDE.md` - Project overview, architecture, common tasks
- `docs/architecture.md` - Technical architecture details
- `docs/SECURITY.md` - Security model, encryption details
- `docs/deployment.md` - Deployment instructions
- `docs/decisions/` - Recent ADRs

### Common Tasks

**Task: Update chart rendering logic**
```bash
# 1. Edit JavaScript module
# File: static/js/modules/ui-controller.js

# 2. Test locally
hugo server -D
# Open http://localhost:1313

# 3. Deploy (auto-builds on push)
git add static/js/modules/ui-controller.js
git commit -m "Update chart rendering logic"
git push
```

**Task: Add new data source**
```bash
# 1. Update api-client.js to fetch from new source
# File: static/js/modules/api-client.js

# 2. Update ui-controller.js to render new data
# File: static/js/modules/ui-controller.js

# 3. Add source metadata to dataSources array
# File: static/js/modules/ui-controller.js (~line 546)

# 4. Test with different time ranges
```

**Task: Fix timezone handling**
```bash
# 1. Update timezone-utils.js
# File: static/js/modules/timezone-utils.js

# 2. Test "now" line placement
# Verify current time indicator matches system clock

# 3. Test historical data
# Ensure timestamps align correctly
```

**Task: Update data decryption**
```bash
# 1. Edit decrypt_data.py
# File: decrypt_data.py

# 2. Test locally (requires encryption keys)
python decrypt_data.py

# 3. Verify output
# Check: static/data/energy_price_forecast.json
```

**Task: Create ADR**
```
1. Copy docs/agents/templates/ADR-TEMPLATE.md
2. Fill in: Context, Decision, Consequences, Alternatives
3. Save as: docs/decisions/YYYY-MM-DD-title.md
4. Update SESSION_STATE.md to reference ADR
```

**Task: Invoke specialized agent**
```
Use Task tool with subagent_type: "general-purpose"
Load agent template from docs/agents/templates/

Example for chart validation:
Prompt: "Act as Chart Agent.
Load template from docs/agents/templates/chart-agent.md.
Validate chart rendering with different time ranges (24h, 48h, 7d, custom)."
```

---

## Success Metrics

You're doing this right when:

- ✅ User never manually updates documentation
- ✅ Context loads are fast and focused (<30 seconds)
- ✅ Significant decisions are captured as ADRs
- ✅ Experiments happen freely in sandbox/
- ✅ SESSION_STATE.md accurately reflects reality
- ✅ Data pipeline is reproducible (config-driven)
- ✅ User can resume after weeks away with clear context

---

## Anti-Patterns to Avoid

- ❌ **Documentation debt:** Completing work without updating docs
- ❌ **Hardcoding:** Duplicating config values in code
- ❌ **Context overload:** Reading entire codebase for simple questions
- ❌ **Git pollution:** Committing experiments instead of using sandbox
- ❌ **Undocumented decisions:** Making significant choices without ADRs
- ❌ **Stale state:** SESSION_STATE.md not reflecting current reality
- ❌ **Assuming context:** Not reading SESSION_STATE.md at session start
- ❌ **Security leaks:** Committing encryption keys or sensitive data

---

## Version History

### v1.0 (2025-11-15)
- Initial AI-augmented workflow for Augur project
- Adapted from SANTA project framework
- Core philosophy: effortless docs, single source of truth, progressive disclosure
- Session protocols: start, during, end
- Project context: Augur specifics

---

## See Also

- `docs/agents/SESSION_STATE.md` - Current project status (read this first!)
- `docs/agents/templates/` - Agent templates (to be created)
- `docs/agents/templates/ADR-TEMPLATE.md` - Architecture decision record template
- `docs/decisions/` - Architecture Decision Records
- `CLAUDE.md` - Project overview and instructions
- `docs/SECURITY.md` - Security model and encryption details
- `sandbox/README.md` - Experimentation guidelines (to be created)
