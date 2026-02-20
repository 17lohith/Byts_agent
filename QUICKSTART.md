# Quick Start Guide

## 30-Second Setup

```bash
# 1. Install
pip install -r requirements.txt
playwright install chromium

# 2. Configure
cp .env.example .env
# Edit .env — add your emails and API key

# 3. Run
python3 main.py
# Log in manually when prompted, then bot takes over
```

---

## Configuration Checklist

Before running, edit `.env`:

```bash
✓ BYTESONE_EMAIL=student@karunya.edu.in    # Your Karunya account
✓ LEETCODE_EMAIL=you@gmail.com             # Your personal Gmail
✓ LLM_PROVIDER=openai                      # or "anthropic"
✓ OPENAI_API_KEY=sk-proj-...               # Get from OpenAI platform
✓ COURSE_NAME=Karunya 2028 - ...           # From BytsOne dashboard
✓ HEADLESS=false                           # Keep false for login visibility
```

---

## First Run Experience

```
12:02:51 [INFO] main: BytsOne Automation Bot starting …
12:02:51 [INFO] main:
============================================================
  FIRST RUN DETECTED
  You will need to log in to both BytsOne and LeetCode
  manually in the browser window that opens.
  BytsOne  → use your Karunya email
  LeetCode → use your personal Gmail
============================================================
12:02:52 [INFO] src.browser.manager: Browser ready ✅
12:02:52 [INFO] src.auth.session: Checking BytsOne login …
12:03:15 [INFO] src.auth.google_oauth:
============================================================
  ACTION REQUIRED — Please log in to BytsOne in the browser window.
  Waiting up to 300 seconds …
============================================================
```

**What you do:**
1. A browser window opens
2. You see BytsOne login screen
3. Click "Sign in with Google" → select/type your Karunya email
4. Complete 2FA if prompted
5. Bot detects you're logged in and moves to LeetCode
6. Repeat for LeetCode with your personal Gmail

---

## Running the Bot

### Normal Run (after first-run setup)

```bash
python3 main.py
```

Bot will:
1. Load saved session (no re-login needed if fresh)
2. Navigate to your course
3. Extract LeetCode links
4. Solve and submit each problem
5. Print summary

```
Done!  Solved: 5  |  Skipped: 3  |  Failed: 1
```

---

## Progress Tracking

Bot automatically saves progress to `progress.json`:

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
- Problems in `completed` are **always skipped** (even if you run twice)
- Problems in `failed` are **retried** (3 attempts per problem)
- Successfully solved problems move from `failed` to `completed`

To reset progress (start over):
```bash
rm progress.json
python3 main.py
```

---

## Logs & Debugging

### View Live Logs
```bash
tail -f logs/automation.log
```

### Common Log Messages

✅ **Expected (success):**
```
[INFO] src.auth.google_oauth: Login to BytsOne detected ✅
[INFO] src.leetcode.solver: Accepted: Two Sum ✅
[INFO] main: Done!  Solved: 5  |  Skipped: 3  |  Failed: 1
```

❌ **Warning (will retry):**
```
[WARNING] src.bytesone.navigator: 'Mark as Completed' button not found — skipping
[WARNING] src.leetcode.solver: Not accepted on attempt 1
```

🔴 **Error (need investigation):**
```
[ERROR] main: Could not log in to BytsOne — aborting
[ERROR] src.config.settings: OPENAI_API_KEY must be set
```

---

## Troubleshooting

### Problem: "Browser closed" or "Target page has been closed"

**Cause:** Login detection timed out or browser crashed

**Fix:**
1. Ensure `HEADLESS=false` in `.env`
2. Check that you actually completed the login (clicked buttons, saw final page)
3. Try again — may have been a one-time network issue

```bash
python3 main.py  # retry
```

---

### Problem: Course not found

**Cause:** Course name in `.env` doesn't match what's in BytsOne

**Fix:**

1. **Find exact name:** Go to BytsOne, click Courses, copy the exact course name
2. **Update .env:**
   ```
   COURSE_NAME=Your Exact Course Name (including dates)
   ```
3. **Or use partial:** Bot tries fuzzy matching, so you can use just the first part:
   ```
   COURSE_NAME=Karunya 2028  # Will match "Karunya 2028 - Product Fit - ..."
   ```

**Debug:**
```python
# In Python REPL (after login):
page.goto("https://www.bytsone.com/home/dashboard")
page.wait_for_load_state("networkidle")
page.locator("button:has-text('Courses')").click()
page.wait_for_load_state("networkidle")

# Find all course links
courses = page.locator("a").all()
for c in courses:
    print(c.inner_text())  # See all available courses
```

---

### Problem: LeetCode login not detected

**Cause:** Selector changed or login incomplete

**Fix:**

Check logs:
```bash
tail -f logs/automation.log | grep -i leetcode
```

Look for:
```
[DEBUG] src.auth.session: LeetCode: on leetcode.com with no sign-in button → logged in
```

If not found, try manual navigation in browser to confirm you're actually logged in.

---

### Problem: "No title selector matched" or "Could not extract problem description"

**Cause:** LeetCode updated their UI since last update

**Fix:**

1. **Check what's on the page:**
   ```bash
   # In Python REPL (during run or after)
   page.goto("https://leetcode.com/problems/two-sum/")
   page.wait_for_load_state("networkidle")

   # Try to find the title manually
   print(page.inner_text()[:500])  # Print first 500 chars
   ```

2. **Find the right selector:**
   - Open DevTools (F12) in the browser
   - Right-click on title → Inspect
   - Copy the selector or element class
   - Note it

3. **Update selectors:**
   Edit `src/config/constants.py`:
   ```python
   LEETCODE_SELECTORS = {
       "problem_title": [
           "[data-cy='question-title']",    # Try this first
           "h1",                            # Fallback
           "[class*='NEW_CLASS_NAME']",     # New selector if others fail
       ],
   }
   ```

4. **Test:**
   ```bash
   python3 main.py  # Bot will now try new selector
   ```

---

### Problem: OpenAI/Anthropic API errors

**Cause:** Invalid key, no credits, or rate limit

**Fix:**

1. **Verify API key:**
   ```bash
   # In Python:
   from src.config.settings import settings
   print(settings.openai_api_key)  # Should show first 10 chars
   ```

2. **Check account:**
   - OpenAI: https://platform.openai.com/account/usage/overview
   - Anthropic: https://console.anthropic.com/account/usage

3. **If rate-limited:** Bot automatically retries with exponential backoff. Wait a few seconds.

---

### Problem: Strange selector errors or "element not found"

**Check in this order:**

1. **Browser window is actually open?**
   ```
   HEADLESS=false should be in .env
   ```

2. **Page loaded completely?**
   Look for: `[INFO] src.bytesone.navigator: wait_for_load_state("networkidle")`

3. **Selector is modern?** (selectors change over time)
   - View the browser DevTools to see current HTML
   - Update constants.py with working selector

4. **Still stuck?** Turn on DEBUG logging:
   ```bash
   LOG_LEVEL=DEBUG python3 main.py 2>&1 | tee debug.log
   ```
   Share the log file to see exactly what happened.

---

## Performance Tips

### Speed Up Runs
```bash
# Reduce wait times (only if you have fast internet)
SLOW_MO=50 python3 main.py  # default 100
```

### Skip Already-Solved Problems
Progress is saved automatically. Bot skips solved problems.

### Test on Small Set First
Edit `.env`:
```
COURSE_NAME=... (select course with 1-2 problems first)
```

Run once to verify setup works, then switch to full course.

---

## Common Patterns

### I want to start completely fresh

```bash
# Remove all saved state
rm progress.json storage_state.json

# Delete browser profile (forces re-login)
rm -rf browser_profile

# Run fresh
python3 main.py
```

### I want to re-solve a specific problem

```bash
# Remove it from progress.json
# Edit the file manually, or:

python3 -c "
import json
progress = json.load(open('progress.json'))
progress['completed'].remove('problem-id')
json.dump(progress, open('progress.json', 'w'), indent=2)
"

python3 main.py
```

### I want to see what the bot is doing

```bash
# Already enabled by default (HEADLESS=false)
# But if you want verbose logs:

LOG_LEVEL=DEBUG python3 main.py
```

---

## File Reference

| File | Purpose |
|------|---------|
| `.env` | Your configuration (DO NOT COMMIT) |
| `progress.json` | Problem completion tracking |
| `storage_state.json` | Playwright session state |
| `browser_profile/` | Chromium cookies & cache |
| `logs/automation.log` | Execution logs |
| `main.py` | Entry point |
| `src/config/` | Settings & constants |
| `src/auth/` | Google OAuth handler |
| `src/browser/` | Browser automation |
| `src/bytesone/` | BytsOne navigation |
| `src/leetcode/` | LeetCode solver |
| `src/ai/` | LLM integration |
| `src/state/` | Progress tracking |

---

## Getting Help

1. **Check logs first:**
   ```bash
   tail -100 logs/automation.log
   ```

2. **Enable DEBUG logging:**
   ```bash
   LOG_LEVEL=DEBUG python3 main.py 2>&1 | head -50
   ```

3. **Test selectors manually:**
   Use the Python REPL examples above to debug CSS selectors

4. **Check `.env`:**
   Verify all required fields are set and typo-free

5. **Try fresh:**
   ```bash
   rm -rf browser_profile storage_state.json
   python3 main.py
   ```

---

## Next Steps

After first successful run:

- ✅ Bot is working
- ✅ Progress is being tracked
- ✅ Session is persistent

Future improvements to consider:

- [ ] Test with multiple courses
- [ ] Monitor API costs
- [ ] Add metrics dashboard
- [ ] Support multiple language choices
- [ ] Implement async solving (parallel problems)

---

