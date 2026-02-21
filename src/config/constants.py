"""Constants — selectors, URLs, timeouts."""

# ── BytsOne: Courses page ───────────────────────────────────────────────────────

BYTESONE_COURSES = {
    # Sidebar navigation
    "sidebar_courses": "button:has-text('Courses')",
    # Course cards on /home/courses
    "course_card_task":  "text=Product Fit- Task Problems",
    "course_card_class": "text=Product Fit- Class Problems",
    "continue_learning_btn": "button:has-text('Continue Learning'), a:has-text('Continue Learning')",
}

# ── BytsOne: Selectors for auth flow ────────────────────────────────────────────

BYTESONE_SELECTORS = {
    "google_signin_btn": [
        "button:has-text('Sign in with Google')",
        "a:has-text('Sign in with Google')",
        "button:has-text('Continue with Google')",
        "a:has-text('Continue with Google')",
    ]
}

# ── BytsOne: Course curriculum (chapter list) ───────────────────────────────────

BYTESONE_CHAPTER = {
    # Chapter rows in the left sidebar (e.g. "Day 1", "Day 2")
    "chapter_row":   ".chapters-list li, [class*='chapter'], [class*='Chapter']",
    # Day label inside a row
    "day_label":     "text=Day",
    # Lock icon — indicates the day is locked
    "lock_icon":     "[class*='lock'], svg[data-icon='lock'], [aria-label*='lock']",
    # Progress bar / completion badge inside a chapter row
    "completed_check": "[class*='check'], [class*='complete'], [class*='tick']",
    # Percentage text inside a row
    "progress_pct":  "text=%",
}

# ── BytsOne: Problem list (inside a chapter) ────────────────────────────────────

BYTESONE_PROBLEM = {
    # Problem rows listed on the right panel after clicking a day
    "problem_row":      "[class*='problem'], [class*='lesson'], li[class*='item']",
    # Clickable problem name (title text)
    "problem_link":     "a[class*='lesson'], a[class*='problem'], li a",
    # Green checkmark = already completed
    "completed_icon":   "[class*='check-circle'], [class*='completed'], svg[data-icon='check-circle']",
}

# ── BytsOne: Problem detail page ────────────────────────────────────────────────

BYTESONE_CHALLENGE = {
    # "Activate" button (appears for new/unattempted problems)
    "activate_btn":       "button:has-text('Activate'), a:has-text('Activate')",
    # "Take Challenge" button on the problem detail card
    "take_challenge":     "button:has-text('Take Challenge'), a:has-text('Take Challenge')",
    # Confirmation dialog elements
    "dialog_container":   "[role='dialog'], .modal, [class*='modal'], [class*='dialog']",
    "dialog_continue_btn": "button:has-text('Continue')",          # first modal step
    "dialog_checkbox":     "input[type='checkbox']",               # confirmation checkbox
    "dialog_start_btn":    "button:has-text('Start Contest')",     # final confirm
    # Bottom bar buttons (shown when problem detail is open in a course)
    "mark_complete_btn":  "button:has-text('Mark as Complete'), a:has-text('Mark as Complete')",
    "next_lesson_btn":    "button:has-text('Next Lesson'), a:has-text('Next Lesson')",
    # Status indicators
    "challenge_incomplete": "text=Challenge Incomplete",
    "challenge_complete":   "text=Challenge Complete, text=Completed",
}

# ── LeetCode: Problem page ──────────────────────────────────────────────────────

LEETCODE_PROBLEM = {
    # Tab navigation
    "solutions_tab":    "a:has-text('Solutions'), div:has-text('Solutions')[role='tab']",
    "description_tab":  "a:has-text('Description'), div:has-text('Description')[role='tab']",
    # Login detection
    "login_wall":       ["text=Sign in", "a[href*='/accounts/login']"],
    # Already accepted badge (skip re-submit)
    "accepted_badge":   ["text=Accepted", "[class*='accepted']", "[data-e2e-locator='submission-result']:has-text('Accepted')"],
}

# ── LeetCode: Selectors for auth flow ──────────────────────────────────────────

LEETCODE_SELECTORS = {
    "google_signin_btn": [
        "button:has-text('Sign in with Google')",
        "a:has-text('Sign in with Google')",
        "button:has-text('Continue with Google')",
        "a:has-text('Continue with Google')",
    ]
}

# ── LeetCode: Solutions tab ─────────────────────────────────────────────────────

LEETCODE_SOLUTIONS = {
    # Language filter dropdown
    "lang_filter":      "[class*='lang'], select[name*='lang'], button:has-text('Language')",
    # Individual language option (filled with .format(lang))
    "lang_option":      "text={lang}",
    # Solution cards in the list
    "solution_card":    "[class*='solution-card'], [class*='SolutionCard'], div[class*='solution__']",
    # Vote/upvote count inside a card
    "vote_count":       "[class*='vote'], [class*='like'], [class*='upvote']",
    # Title/link of a solution card
    "solution_title":   "a[class*='title'], [class*='solution-title']",
    # Code block inside an opened solution
    "solution_code":    "pre code, [class*='CodeMirror'] .CodeMirror-code, .view-lines",
    # "View solution" or "Read more" expand button
    "expand_btn":       "button:has-text('View'), button:has-text('Read'), a:has-text('View solution')",
}

# ── LeetCode: Code editor & submission ─────────────────────────────────────────

LEETCODE_EDITOR = {
    "code_editor":              ".monaco-editor",
    "lang_selector":            "[id*='lang'] button, button[class*='lang']",
    "java_option":              "text=Java",
    "submit_button":            ["[data-e2e-locator='console-submit-button']", "button:has-text('Submit')"],
    # Primary: read the submission-result panel text to confirm "Accepted"
    "result_accepted":          ["[data-e2e-locator='submission-result']:has-text('Accepted')"],
    # Fallback: CSS-class-based accepted signals (no broad text match)
    "result_accepted_fallback": ["[class*='accepted']", "[class*='success'][class*='result']"],
    "result_wrong":             ["text=Wrong Answer", "text=Runtime Error", "text=Time Limit Exceeded", "text=Compile Error"],
}

# ── Google OAuth ────────────────────────────────────────────────────────────────

GOOGLE_SELECTORS = {
    "account_picker":      "div[data-authuser]",
    "account_email_text":  "div[data-identifier]",
    "use_another_account": "text=Use another account",
    "email_input":         "input[type='email']",
    "email_next":          "#identifierNext, button:has-text('Next')",
    "continue_btn":        "button:has-text('Continue'), button:has-text('Allow')",
}

# ── URLs ────────────────────────────────────────────────────────────────────────

BYTESONE_BASE_URL    = "https://www.bytsone.com"
BYTESONE_COURSES_URL = "https://www.bytsone.com/home/courses"
LEETCODE_BASE_URL    = "https://leetcode.com"
GOOGLE_ACCOUNTS_URL  = "https://accounts.google.com"

# ── Course identifiers ──────────────────────────────────────────────────────────

COURSE_CLASS   = "class_problems"
COURSE_TASK    = "task_problems"

COURSE_TITLE_FRAGMENTS = {
    COURSE_CLASS: "Class Problems",
    COURSE_TASK:  "Task Problems",
}

# ── Timeouts (ms) ──────────────────────────────────────────────────────────────

TIMEOUT_SHORT        = 5_000
TIMEOUT_MEDIUM       = 15_000
TIMEOUT_LONG         = 30_000
TIMEOUT_EXTRA_LONG   = 60_000
TIMEOUT_MANUAL_LOGIN = 300_000

# ── Retry ──────────────────────────────────────────────────────────────────────

MAX_SOLVER_RETRIES = 3
SOLVER_RETRY_DELAY = 3   # seconds
