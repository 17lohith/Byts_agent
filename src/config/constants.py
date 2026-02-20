"""Constants — selectors, URLs, timeouts."""

# ── BytsOne ────────────────────────────────────────────────────────────────────

BYTESONE_SELECTORS = {
    "sidebar_courses": "button:has-text('Courses')",
    "continue_learning": "text=Continue Learning",
    "activate_button": "text=Activate",
    "take_challenge": "text=Take Challenge",
    "mark_completed": "text=Mark as Completed",
    # Login detection
    "login_wall": "text=Sign in",
    "google_signin_btn": "button:has-text('Continue with Google'), button:has-text('Sign in with Google'), a:has-text('Sign in with Google')",
}

# ── LeetCode ───────────────────────────────────────────────────────────────────

# Multiple fallback selectors per element — tried in order until one matches
LEETCODE_SELECTORS = {
    "problem_title": [
        "[data-cy='question-title']",
        "h1",
        "[class*='title__']",
        "[class*='text-title']",
    ],
    "problem_description": [
        "[data-cy='question-content']",
        "[class*='content__']",
        "[class*='description__']",
        "[class*='elfjS']",
    ],
    "code_editor": ".monaco-editor",
    "submit_button": [
        "[data-e2e-locator='console-submit-button']",
        "button:has-text('Submit')",
    ],
    "result_accepted": [
        "text=Accepted",
        "[data-e2e-locator='submission-result']:has-text('Accepted')",
    ],
    "result_wrong": [
        "text=Wrong Answer",
        "text=Runtime Error",
        "text=Time Limit Exceeded",
    ],
    # Login detection
    "login_wall": [
        "text=Sign in",
        "a[href*='/accounts/login']",
    ],
    "google_signin_btn": [
        "a:has-text('Continue with Google')",
        "button:has-text('Continue with Google')",
    ],
}

# ── Google OAuth ───────────────────────────────────────────────────────────────

GOOGLE_SELECTORS = {
    # Account picker screen
    "account_picker": "div[data-authuser]",
    "account_email_text": "div[data-identifier]",    # each row shows email
    "use_another_account": "text=Use another account",
    # Email entry screen
    "email_input": "input[type='email']",
    "email_next": "#identifierNext, button:has-text('Next')",
    # Already signed in confirmation / consent
    "continue_btn": "button:has-text('Continue'), button:has-text('Allow')",
}

# ── URLs ───────────────────────────────────────────────────────────────────────

LEETCODE_BASE_URL = "https://leetcode.com"
BYTESONE_BASE_URL = "https://www.bytsone.com"
GOOGLE_ACCOUNTS_URL = "https://accounts.google.com"

# ── Timeouts (ms) ──────────────────────────────────────────────────────────────

TIMEOUT_SHORT = 5_000
TIMEOUT_MEDIUM = 15_000
TIMEOUT_LONG = 30_000
TIMEOUT_EXTRA_LONG = 60_000
TIMEOUT_MANUAL_LOGIN = 300_000   # 5 minutes for the human to complete OAuth

# ── Retry ──────────────────────────────────────────────────────────────────────

MAX_SOLVER_RETRIES = 3
SOLVER_RETRY_DELAY = 5
