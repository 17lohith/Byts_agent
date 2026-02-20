# Architecture & Design Decisions

## Overview

BytsOne Automation Bot is a **modular, layered architecture** with clear separation of concerns:

```
┌─────────────────────────────────────────────────────┐
│              Orchestration (main.py)                 │
└─────────────────────────────────────────────────────┘
                         │
        ┌────────────────┼────────────────┐
        │                │                │
    ┌───▼────┐    ┌──────▼──────┐   ┌────▼────┐
    │ Auth   │    │ Navigation  │   │Solving  │
    │ Layer  │    │ Layer       │   │Layer    │
    └────────┘    └─────────────┘   └─────────┘
        │                │                │
        └────────────────┼────────────────┘
                         │
        ┌────────────────┼────────────────┐
        │                │                │
    ┌───▼────┐    ┌──────▼──────┐   ┌────▼────┐
    │ Browser│    │ LLM Service │   │Progress │
    │ Service│    │ (OpenAI/    │   │Tracker  │
    │        │    │ Anthropic)  │   │         │
    └────────┘    └─────────────┘   └─────────┘
```

---

## Layer 1: Orchestration (`main.py`)

**Responsibility:** Coordinate the entire workflow

**Design:**
- Single entry point for the entire application
- Handles top-level error handling and reporting
- Manages context managers (`with BrowserManager() as browser:`)
- Implements the main problem-solving loop
- Detects mid-run session expiry and triggers re-authentication

**Key Pattern:** Context managers (`__enter__` / `__exit__`)
- Ensures browser is always closed, even on error
- Saves session state before exit

**Failure Modes:**
- `.env` validation fails → exit with config error (fast-fail)
- BytsOne login fails → exit with clear message
- LeetCode login fails → exit with clear message
- Mid-run problem failure → mark as failed, continue with next
- Mid-run session expiry → auto re-auth, retry problem once

---

## Layer 2: Auth Layer (`src/auth/`)

### Design Decision: Google OAuth Handler vs. Direct Login

**Why Google OAuth?**
- Both BytsOne and LeetCode support it
- More reliable than trying to detect/fill password fields (varies per site)
- Single auth method for both sites
- Supports 2FA automatically (Google handles it)

### `session.py` — Login Orchestration

**Responsibilities:**
1. Detect current login state
2. Route to manual login (first-run) or auto re-auth (subsequent runs)
3. Validate login succeeded before proceeding

**Implementation:**

```python
def ensure_bytesone_login(page, url, email, timeout, first_run):
    page.goto(url)
    if _is_logged_in(page, BYTESONE_LOGGED_IN):
        return True

    if first_run:
        return wait_for_manual_login(page, ...)
    else:
        return handle_google_relogin(page, email, ...)
```

**Why separate?**
- First-run: human is in control; bot waits for them
- Re-auth: bot is in control; auto-clicks account

### `google_oauth.py` — Account Selection

**Problem:** Google account picker shows multiple accounts. Need to click the right one.

**Solution:** Three strategies in order:

1. **Account Picker** (most common)
   - Google shows accounts already logged into the browser
   - Look for account row matching expected email
   - Click it

2. **"Use Another Account"** (fallback)
   - If our email not in picker, click "Use another account"
   - Type email manually
   - Submit

3. **Direct Email Entry** (rare, direct entry screen)
   - Type email directly if no picker shown

**Why polling in LeetCode login?**

Original design waited for a selector: `"nav a[href*='/profile']"`. This broke when:
- LeetCode updated their navbar UI
- Selector didn't exist in their current design
- `wait_for()` kept waiting until browser closed (timeout)

New design polls every 2 seconds:
```python
while elapsed < timeout_ms:
    page.wait_for_timeout(2000)
    if _is_leetcode_logged_in(page):  # smart detection
        return True
    elapsed += 2000
```

`_is_leetcode_logged_in()` uses **multi-strategy detection**:
1. Try known UI element selectors
2. If none match, check: URL on `leetcode.com` + no login button = logged in
3. URL-based approach survives UI changes

---

## Layer 3: Navigation Layer (`src/bytesone/navigator.py`, `src/leetcode/solver.py`)

### BytsOne Navigator — Fuzzy Course Matching

**Problem:** Course names in `.env` may not exactly match what's displayed
- Names contain timestamps: `"... (16-2-2026 to 21-2-2026)"`
- Minor whitespace/punctuation differences
- User may type partial name

**Solution: Fuzzy Matching Fallback**
```
1. Exact text match
2. Partial text match (contains full course name)
3. Substring match (first 40 chars)
```

Benefits over strict matching:
- More forgiving of minor typos
- Survives small UI changes
- User can provide just first part of course name

### LeetCode Solver — Fallback Selectors

**Problem:** LeetCode frequently updates DOM. Single selector breaks.

**Solution: Multiple Fallbacks**
```python
for selector in ["[data-cy='question-title']", "h1", "[class*='text-title']"]:
    try:
        el = page.locator(selector).first
        el.wait_for(state="visible", timeout=TIMEOUT_MEDIUM)
        text = el.inner_text().strip()
        if text: return text
    except PWTimeout:
        continue
```

**Why this approach?**
- **Graceful degradation:** if first selector breaks, others take over
- **Maintenance-free:** new selectors can be added without code change
- **Logging:** knows which selector matched (helps debug when LeetCode updates)
- **Pattern:** can be applied to any brittle selector

### Monaco Editor Code Injection

**Problem:** Need to inject code into LeetCode's Monaco editor

**Solution: Two Methods**

1. **JavaScript API** (preferred)
   ```javascript
   const models = monaco.editor.getModels();
   models[0].setValue(code);
   ```
   - Fast, reliable, verifiable
   - Doesn't require user interaction

2. **Keyboard Fallback**
   ```python
   editor.click()
   page.keyboard.press("Control+a")
   page.keyboard.type(code)
   ```
   - Works if Monaco JS API unavailable
   - Slower but doesn't require browser state

**Verification:** After injection, read back to confirm:
```python
actual = page.evaluate("() => monaco.editor.getModels()[0].getValue()")
if code.strip() in actual:
    return True
```

---

## Layer 4: Solving Layer

### `src/ai/solver.py` — LLM Integration

**Design: Provider Agnostic**

```python
if provider == "openai":
    response = client.chat.completions.create(...)
elif provider == "anthropic":
    message = client.messages.create(...)
```

**Retry Strategy: Exponential Backoff**
```
Attempt 1: fail → wait 2s
Attempt 2: fail → wait 4s
Attempt 3: fail → wait 8s
```

Why?
- **Rate limiting:** LeetCode has rate limits; backoff reduces retry collisions
- **Transient errors:** API may recover; retry after brief delay
- **Exponential:** avoids hammering the API

**Response Cleaning:**
- LLM may wrap code in markdown fences: ` ```python ... ``` `
- Strip them: `re.sub(r"^```[\w]*\n?", "", code)`
- Pass clean code to LeetCode

### `src/state/progress.py` — Atomic Progress Saving

**Design: JSON-based State Machine**

```json
{
  "completed": ["two-sum", "..."],
  "failed": ["reverse-string"]
}
```

**State Transitions:**
- `not_started` → `completed` (success)
- `not_started` → `failed` (failure, will retry)
- `failed` → `completed` (successful retry)

**Atomic Saves:**
Every state change immediately writes to disk:
```python
def mark_completed(self, problem_id):
    self.data["completed"].append(problem_id)
    self.save()  # write now, don't batch
```

Why?
- **Crash-safe:** if bot crashes, no progress is lost
- **Incremental:** can resume from any point
- **Simple:** easy to inspect and debug

---

## Layer 5: Infrastructure (`src/browser/manager.py`, `src/config/`)

### Browser Manager — Persistent Context

**Old Design (CDP):**
- Attached to running Brave browser via Chrome DevTools Protocol
- Required manual Brave startup: `brave --remote-debugging-port=9222`
- Didn't manage browser lifecycle

**New Design (Persistent Context):**
- Launches Playwright's bundled Chromium
- Stores cookies/localStorage in `browser_profile/` directory
- Sessions survive across runs
- Fully automated

```python
context = playwright.chromium.launch_persistent_context(
    user_data_dir="browser_profile",
    headless=False,  # needed to see login prompts
)
context.storage_state(path="storage_state.json")
```

**Benefits:**
- No external dependencies
- Automated browser lifecycle
- Session persistence without manual intervention
- Better control over browser flags/options

### Configuration (`src/config/`)

**`settings.py` — Pydantic Validation**

```python
class Settings(BaseSettings):
    bytesone_email: str = ""

    @model_validator(mode="after")
    def validate_emails_set(self):
        if not self.bytesone_email:
            raise ValueError("BYTESONE_EMAIL must be set")
```

**Why Pydantic?**
- **Type safety:** catches misconfigurations early
- **Validation:** custom validators for complex rules
- **Parsing:** automatically converts env strings to types
- **Docs:** field descriptions as validation context

**`constants.py` — Selector Library**

Centralized selector management:
- Easy to update when LeetCode changes UI
- Fallbacks in one place
- Timeout values consistent
- No magic strings in code

---

## Error Handling Strategy

### Layered Approach

```
Layer 1: Try operation
Layer 2: Catch specific errors (PWTimeout, ElementNotFound)
Layer 3: Log context (which selector, what URL)
Layer 4: Decide: retry, fallback, or propagate
```

Example: Finding problem title
```python
def _get_title(self):
    for sel in LEETCODE_SELECTORS["problem_title"]:
        try:                               # Layer 1: try
            el = page.locator(sel).first
            el.wait_for(timeout=TIMEOUT)
            text = el.inner_text().strip()
            if text:
                logger.debug(f"Title matched: {sel}")
                return text
        except PWTimeout:                  # Layer 2: catch specific error
            logger.debug(f"Title selector failed: {sel}")  # Layer 3: log
            continue                       # Layer 4: retry next selector

    logger.error("No title selector matched")  # Layer 4: propagate
    return None
```

### Graceful Degradation

- Problem title selector fails → return None → problem skipped (not crash)
- LeetCode submit button not found → return False → problem marked failed
- BytsOne "Mark Complete" fails → warning logged → continue to next problem

Philosophy: **Incomplete success > complete failure**

---

## Testing & Debugging

### Logging Strategy

**Three levels:**
- `DEBUG`: selector matching, LLM response sizes, state changes
- `INFO`: major milestones, login detected, problem solved
- `ERROR`: unrecoverable failures

**Log Output:**
- **Console:** colored, real-time feedback
- **File:** `logs/automation.log`, persistent record

### Selector Debugging

Live testing:
```bash
python3 -i main.py  # start Python REPL after setup

# After manual login:
from src.config.constants import LEETCODE_SELECTORS
page.goto("https://leetcode.com/problems/two-sum/")
page.wait_for_load_state("networkidle")

for sel in LEETCODE_SELECTORS["problem_title"]:
    try:
        result = page.locator(sel).first.inner_text()
        print(f"✓ {sel}: {result}")
        break
    except:
        print(f"✗ {sel} (not found)")
```

---

## Performance Considerations

### Timeout Strategy

```python
TIMEOUT_SHORT = 5_000          # UI elements, validators
TIMEOUT_MEDIUM = 15_000        # page navigation
TIMEOUT_LONG = 30_000          # code execution, submission wait
TIMEOUT_EXTRA_LONG = 60_000    # initial page loads
TIMEOUT_MANUAL_LOGIN = 300_000 # 5 min for human interaction
```

Rationale:
- Fast operations (selectors) use short timeouts → quick feedback
- Network operations use medium timeouts → allow connection slowness
- Execution wait uses long timeout → LeetCode can be slow
- Manual login uses very long timeout → user may be AFK

### Slowmo Setting

```
SLOW_MO = 100  # milliseconds between each action
```

Benefits:
- Visible debugging: can see what bot is doing
- Stability: gives JS time to execute
- LeetCode doesn't rate-limit rapid clicks

---

## Known Issues & Workarounds

### Issue 1: LeetCode DOM Changes
**Symptom:** "No title selector matched"
**Root cause:** LeetCode updated their UI
**Workaround:** Add new selector to `LEETCODE_SELECTORS["problem_title"]` in `constants.py`

### Issue 2: Google Account Picker Not Showing
**Symptom:** Stuck waiting for account picker
**Root cause:** Browser already logged into exact email, Google skips picker
**Workaround:** Auto-detect and proceed (handled in code)

### Issue 3: Monaco Editor Not Initialized
**Symptom:** Code injection fails
**Root cause:** Monaco JS API not available (edge case)
**Workaround:** Fall back to keyboard input

### Issue 4: Session Expiry Detection Slow
**Symptom:** Takes 2-5 seconds to detect session expired
**Root cause:** Polling every 2 seconds (intentional for robustness)
**Workaround:** Acceptable latency; ensures reliable detection

---

## Future Architecture Improvements

### 1. Async/Await (Performance)
Current: Synchronous, one problem at a time
Future: Async to solve multiple problems in parallel

```python
async def solve_all_problems(problems):
    tasks = [solve_problem(p) for p in problems]
    results = await asyncio.gather(*tasks)
```

### 2. Plugin System (Flexibility)
Allow custom problem solvers (e.g., for interactive problems)

```python
class ProblemSolver(ABC):
    @abstractmethod
    def can_solve(self, problem) -> bool:
        pass

    @abstractmethod
    def solve(self, problem) -> str:
        pass
```

### 3. Metrics & Observability (Monitoring)
Track success rates, solve times, cost

```python
@dataclass
class SolveResult:
    problem_id: str
    success: bool
    time_elapsed: float
    llm_cost: float
```

### 4. Configuration Management (Ops)
Support multiple environments, profiles, dry-run modes

```python
# .env
PROFILE = "production"  # or "dry_run"

# dry-run: navigate but don't submit
# production: full execution
# debug: verbose logging
```

---

## Deployment Considerations

### Headless Mode
- Development: `HEADLESS=false` (see what's happening)
- Production: `HEADLESS=true` (no UI overhead)

### API Key Rotation
- Store keys in `.env` (never commit)
- Consider environment variable injection in CI/CD
- Rotate keys periodically

### Rate Limiting
- Add metrics tracking to monitor API usage
- Exponential backoff built-in
- Manual rate-limit logic for batch runs

### Crash Recovery
- Progress saved atomically → resume from last completed problem
- Session persisted → no re-login required
- Logs detailed for debugging

---

## Testing Strategy

### Unit Tests (not yet implemented)
```python
def test_strip_markdown():
    code = "```python\nprint('hello')\n```"
    assert LeetCodeSolver._strip_markdown(code) == "print('hello')"

def test_fuzzy_course_matching():
    assert BytesOneNavigator._find_course("Karunya") matches "Karunya 2028 - ..."
```

### Integration Tests
- Mock LeetCode/BytsOne with fixtures
- Test auth flow (manual login detection)
- Test progress tracking

### E2E Tests
- Run against live sites (small problem set)
- Verify solve pipeline: extract → generate → inject → submit
- Manual: verify session persistence across runs

---

