# BytsOne Automation Bot

A Python automation bot that bridges **BytsOne** (learning platform) with **LeetCode** using AI to automatically solve coding problems.

**Status:** ✅ Working — auth system complete, ready for problem-solving testing

---

## 🎯 Project Goal

1. Navigate the BytsOne course management platform
2. Extract LeetCode problem links from courses
3. Use **OpenAI or Anthropic** to generate solutions
4. Automatically submit solutions to LeetCode
5. Mark problems as completed on BytsOne
6. Maintain persistent progress across runs

---

## 🏗️ Architecture Overview

### Tech Stack
- **Browser Automation:** Playwright (persistent Chromium context)
- **Session Persistence:** Playwright storage state + browser profile directory
- **Auth:** Google OAuth (handles first-run manual login + auto re-auth)
- **LLM:** OpenAI (GPT-4) or Anthropic (Claude 3.5 Sonnet)
- **Config:** Pydantic + environment variables

### Data Flow

```
┌─────────────────────────────────────────────────────────┐
│                        main.py                           │
└────────────────────────┬────────────────────────────────┘
                         │
        ┌────────────────┼────────────────┐
        │                │                │
        ▼                ▼                ▼
   ┌────────┐      ┌──────────┐     ┌──────────┐
   │Browser │      │Auth Mgr  │     │Progress  │
   │Manager │      │          │     │Tracker   │
   └────────┘      └──────────┘     └──────────┘
        │                │                │
        └────────────────┼────────────────┘
                         │
        ┌────────────────┼────────────────┐
        │                │                │
        ▼                ▼                ▼
   ┌──────────┐   ┌────────────┐   ┌────────────┐
   │BytsOne   │   │LeetCode    │   │LLM Solver  │
   │Navigator │   │Solver      │   │(OpenAI/   │
   │          │   │            │   │ Anthropic) │
   └──────────┘   └────────────┘   └────────────┘
```

### Session Flow

**First Run:**
```
1. Browser Manager launches persistent Chromium
   ↓
2. Auth: BytsOne login (manual via Google OAuth)
   ↓
3. Auth: LeetCode login (manual via Google OAuth)
   ↓
4. Session saved to storage_state.json
   ↓
5. Begin problem solving
```

**Subsequent Runs:**
```
1. Load storage_state.json into browser
   ↓
2. Quick login check on both sites
   ↓
3. If session expired: auto re-login (click correct Google account)
   ↓
4. Begin problem solving
```

---

## 📁 Project Structure

```
Byts_agent/
├── main.py                           # Orchestration entry point
├── .env                              # Your credentials (DO NOT COMMIT)
├── .env.example                      # Configuration template
├── .gitignore                        # Ignores browser profiles, logs, .env
├── requirements.txt                  # Python dependencies
├── progress.json                     # Problem tracking (auto-created)
├── storage_state.json                # Playwright session (auto-created)
│
├── browser_profile/                  # Chromium profile (persistent cookies)
├── logs/                             # Execution logs
│
└── src/
    ├── config/
    │   ├── settings.py              # Pydantic config from .env
    │   └── constants.py             # Selectors, URLs, timeouts
    │
    ├── browser/
    │   └── manager.py               # Persistent Chromium context
    │
    ├── auth/                        # NEW: Authentication module
    │   ├── session.py               # Login detection + orchestration
    │   └── google_oauth.py          # Google account picker handler
    │
    ├── bytesone/
    │   └── navigator.py             # Course navigation, fuzzy matching
    │
    ├── leetcode/
    │   └── solver.py                # Problem extraction, code injection
    │
    ├── ai/
    │   └── solver.py                # LLM integration (OpenAI/Anthropic)
    │
    ├── state/
    │   └── progress.py              # JSON-based progress tracking
    │
    └── utils/
        └── logger.py                # Colored console + file logging
```

---

## 🔑 Key Components

### 1. **Browser Manager** (`src/browser/manager.py`)
- Launches Playwright Chromium with persistent context
- Preserves cookies/localStorage in `browser_profile/` across runs
- Saves Playwright storage state to `storage_state.json` after login
- No CDP dependency — completely self-contained

**Why:** Previous version used Brave via CDP (required manual Brave startup). Now it's fully automated.

### 2. **Auth Module** (`src/auth/`)

#### `session.py` — Login Orchestration
- `ensure_bytesone_login()` — detect login, wait for manual on first run, auto re-auth on expiry
- `ensure_leetcode_login()` — same, but uses polling + URL-based fallback for detection
- First-run pauses and waits for human to complete Google OAuth manually
- Subsequent runs auto-detect session expiry and re-authenticate

#### `google_oauth.py` — Google Account Handler
- `wait_for_manual_login()` — displays browser and waits for user to complete login
- `handle_google_relogin()` — automatically clicks the correct Google account during OAuth
  - Looks for account picker screen, finds matching email
  - Falls back to typing email if account not in picker
  - Handles consent screens
- Waits for redirect away from `accounts.google.com`

**Why:** Both sites use Google OAuth. The bot needs to pick the right account:
- BytsOne → Karunya institutional email
- LeetCode → Personal Gmail

### 3. **BytsOne Navigator** (`src/bytesone/navigator.py`)
- `navigate_to_course()` — finds course by fuzzy name matching (exact → partial → substring)
- `get_problem_links()` — extracts all LeetCode URLs on the page
- `mark_completed()` — clicks "Mark as Completed" after LeetCode success
- Graceful error handling — warnings instead of crashes

**Improvement:** Now uses **fuzzy course name matching** instead of exact match. Course names often differ by timestamps or minor changes.

### 4. **LeetCode Solver** (`src/leetcode/solver.py`)
- `solve_problem(url)` — full pipeline: fetch → generate → inject → submit
- Multiple **fallback selectors** for every element:
  - Title: `[data-cy='question-title']` → `h1` → `[class*='text-title']`
  - Description: `[data-cy='question-content']` → `[class*='description__']`
  - Submit button: `[data-e2e-locator='...']` → `button:has-text('Submit')`

- **Code injection:** Uses Monaco editor JS API with keyboard fallback
  - Verifies injection succeeded before submitting

- **Login wall detection:** Checks for "Sign In" button; if found, returns False so main can re-auth

**Why:** LeetCode frequently updates their DOM. Multiple fallbacks handle layout changes gracefully.

### 5. **LLM Solver** (`src/ai/solver.py`)
- Supports OpenAI (GPT-4) and Anthropic (Claude 3.5 Sonnet)
- Sends problem title + description to LLM with prompt: "Write a complete python3 solution"
- **Exponential backoff retry** (2s → 4s → 8s) for API rate limits
- Returns code directly (strips markdown fences if LLM added them)

**Improvement:** Added retry logic. Large problem sets can hit rate limits; now handles gracefully.

### 6. **Progress Tracker** (`src/state/progress.py`)
- Persists to `progress.json`: `{"completed": [...], "failed": [...]}`
- Atomic saves after each success/failure
- Prevents re-solving already completed problems

### 7. **Configuration** (`src/config/`)

#### `settings.py` (Pydantic-based)
```python
BYTESONE_EMAIL = "student@karunya.edu.in"       # Karunya account
LEETCODE_EMAIL = "personal@gmail.com"           # Personal Gmail
LLM_PROVIDER = "openai"                         # or "anthropic"
OPENAI_API_KEY = "sk-proj-..."
COURSE_NAME = "Karunya 2028 - Product Fit- ..."
HEADLESS = false                                # Always headed for login visibility
BROWSER_PROFILE_DIR = "browser_profile"
SESSION_FILE = "storage_state.json"
LOGIN_WAIT_TIMEOUT = 300_000                    # 5 min for manual login
```

#### `constants.py`
- Selector library with fallbacks
- Google OAuth selectors (account picker, email input, continue buttons)
- Login-wall detection selectors
- URL constants
- Timeout values

### 8. **Main Orchestration** (`main.py`)

**Execution flow:**
```python
1. Validate .env (email addresses must be set)
2. Launch browser (first-run or load session)
3. Ensure BytsOne login (manual or auto)
4. Ensure LeetCode login (manual or auto)
5. Save session
6. Navigate to course
7. For each problem:
   a. Skip if already completed
   b. Generate solution with LLM
   c. Submit to LeetCode
   d. If login wall detected: re-auth + retry once
   e. Mark as completed
8. Report summary (solved/skipped/failed)
```

---

## 🚀 Setup & Usage

### Prerequisites
- Python 3.8+
- OpenAI or Anthropic API key
- Karunya email (for BytsOne)
- Personal Gmail (for LeetCode)

### Installation

```bash
# 1. Clone & enter directory
cd /home/lebi/projects/Byts_agent

# 2. Create virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Install Playwright browser
playwright install chromium

# 5. Copy & configure .env
cp .env.example .env
# Edit .env:
# - BYTESONE_EMAIL = your Karunya email
# - LEETCODE_EMAIL = your personal Gmail
# - OPENAI_API_KEY or ANTHROPIC_API_KEY
# - COURSE_NAME = your exact course name (or substring)
```

### First Run

```bash
python3 main.py
```

A browser window opens. You'll see:
```
============================================================
  FIRST RUN DETECTED
  You will need to log in to both BytsOne and LeetCode
  manually in the browser window that opens.
  BytsOne  → use your Karunya email
  LeetCode → use your personal Gmail
============================================================
```

**What happens:**
1. Bot navigates to BytsOne, pauses, displays a message in the terminal
2. You manually log in with Karunya email via Google OAuth (bot watches)
3. Once logged in, bot detects success and moves to LeetCode
4. Bot navigates to LeetCode, pauses for your manual login
5. You log in with personal Gmail via Google OAuth
6. Bot saves the session and begins problem-solving

### Subsequent Runs

```bash
python3 main.py
```

Bot automatically:
1. Loads saved session from `storage_state.json`
2. Checks if still logged in on both sites
3. If session expired, auto-clicks the correct Google account (you may need to do 2FA)
4. Proceeds directly to problem-solving

---

## 🔍 Selectors & Robustness

### Why Multiple Fallbacks?

LeetCode frequently updates their UI. A single selector can break. The bot now tries multiple selectors for each element:

```python
# Before: single selector (brittle)
title = page.locator("[class*='text-title']").inner_text()

# After: multiple fallbacks
for selector in ["[data-cy='question-title']", "h1", "[class*='text-title']"]:
    try:
        title = page.locator(selector).first.inner_text()
        if title: break
    except: continue
```

### LeetCode Login Detection

Previous issue: selectors like `#navbar-right` didn't exist on current LeetCode.
**Solution:** Polling with URL-based fallback:
- Try to find logged-in UI elements (avatar, profile link)
- If not found, check: "we're on `leetcode.com`, not on login page, no Sign In button" → assume logged in
- Poll every 2 seconds instead of waiting on single selector

---

## 📊 Progress Tracking

### `progress.json`
```json
{
  "completed": [
    "two-sum",
    "add-two-numbers",
    "longest-substring-without-repeating-characters"
  ],
  "failed": [
    "reverse-string"
  ]
}
```

**Behavior:**
- Problems in `completed` are always skipped
- Problems in `failed` are retried
- Moved from `failed` → `completed` when solved
- Atomic saves after each change

---

## 📝 Logging

Console output (colored) + file logging to `logs/automation.log`

```
12:02:51 [INFO] main: BytsOne Automation Bot starting …
12:02:51 [INFO] src.browser.manager: Launching Playwright Chromium …
12:04:06 [INFO] src.auth.google_oauth: Login to BytsOne detected ✅
12:07:09 [INFO] src.leetcode.solver: Attempt 1/3: https://leetcode.com/problems/two-sum/
12:07:15 [DEBUG] src.leetcode.solver: Title selector matched: [data-cy='question-title']
12:07:20 [INFO] src.ai.solver: Sending 'Two Sum' to openai (gpt-4-turbo)
12:07:25 [DEBUG] src.ai.solver: OpenAI response: 234 chars
12:07:28 [INFO] src.leetcode.solver: Code injected via Monaco JS API ✅
12:07:35 [INFO] src.leetcode.solver: Accepted: Two Sum ✅
```

---

## 🐛 Known Limitations & Future Work

### Current Limitations
- ✅ Python3 only (hardcoded in LLM prompt)
- ✅ Assumes Monaco editor on LeetCode (most problems use this)
- ⚠️ No support for premium LeetCode problems (if they redirect)
- ⚠️ No handling of interactive/special problems (graph visualization, etc.)

### Future Improvements
1. **Language selection** — detect available languages, let user choose
2. **Dry-run mode** — navigate without submitting (for testing)
3. **Problem categorization** — group by difficulty, topic
4. **Rate limiting** — smart backoff based on LeetCode response codes
5. **Metrics** — success rate, avg time per problem, cost tracking
6. **Parallel solving** — (if using async) solve multiple problems concurrently

---

## 🔧 Development Notes

### Module Dependencies

```
main.py
  ├── BrowserManager (src/browser/manager.py)
  ├── Auth Session (src/auth/session.py)
  │   └── Google OAuth (src/auth/google_oauth.py)
  ├── BytsOne Navigator (src/bytesone/navigator.py)
  ├── LeetCode Solver (src/leetcode/solver.py)
  │   └── LLM Solver (src/ai/solver.py)
  └── Progress Tracker (src/state/progress.py)
```

All modules initialized fresh per run. Global `settings` instance loaded from `.env`.

### Testing Selectors

To debug selectors live:
```bash
# Start Python REPL
python3 -i main.py

# After login, use page object:
from src.config.constants import LEETCODE_SELECTORS
page.goto("https://leetcode.com/problems/two-sum/")
page.wait_for_load_state("networkidle")

# Try selectors
for sel in LEETCODE_SELECTORS["problem_title"]:
    try:
        text = page.locator(sel).first.inner_text()
        print(f"✓ {sel}: {text}")
        break
    except: print(f"✗ {sel}")
```

---

## 🎓 Learning Resources

- **Playwright:** https://playwright.dev/python/
- **Pydantic:** https://docs.pydantic.dev/
- **OpenAI API:** https://platform.openai.com/docs/
- **Anthropic API:** https://docs.anthropic.com/

---

## 📜 License

Internal project — BytsOne learning automation

---

## 🤝 Contributing

This is a personal automation bot. Code structure prioritizes:
1. **Reliability** — multiple fallback selectors, graceful error handling
2. **Persistence** — session/progress saved automatically
3. **Clarity** — modular design, typed functions, comprehensive logging
4. **Simplicity** — avoid over-engineering; only add features when needed

---

## ❓ Troubleshooting

### "Browser closed" or "Target page ... has been closed"
- Ensure `HEADLESS=false` in `.env` so the browser window stays visible
- Manual login may have been interrupted; try again

### LeetCode login selector not matching
- LeetCode likely updated their UI
- Check `logs/automation.log` for which selectors were tried
- Add new fallback selector to `LEETCODE_LOGGED_IN_SELECTORS` in `src/auth/session.py`

### "Could not find 'Sign in with Google' button"
- Ensure you're on the correct site URL
- Check that Google OAuth is enabled for that site
- Try manually navigating to the site's login page to see the button

### LLM API errors
- Verify API key in `.env` and that it's valid
- Check account has credits/quota
- Logs show exponential backoff in action

### Course not found
- Check exact `COURSE_NAME` in `.env` against what appears in BytsOne
- Try using just the first 40 characters (fuzzy matching will kick in)
- Ensure you have access to the course

---

## 📞 Support

Check `logs/automation.log` first — usually contains the full error and context.

Most issues are selector-related (LeetCode DOM changes). Update selectors in `src/config/constants.py` as needed.

