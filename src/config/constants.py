"""Constants used throughout the application."""

# BytsOne Selectors
BYTESONE_SELECTORS = {
    "sidebar_courses": "button:has-text('Courses')",
    "continue_learning": "text=Continue Learning",
    "activate_button": "text=Activate",
    "take_challenge": "text=Take Challenge",
    "mark_completed": "text=Mark as Completed",
    "continue_with_profile": "text=Continue",
}

# LeetCode Selectors
LEETCODE_SELECTORS = {
    "problem_title": "[class*='text-title']",
    "problem_description": "[class*='elfjS']",
    "code_editor": ".monaco-editor",
    "submit_button": "[data-e2e-locator='console-submit-button']",
    "run_button": "[data-e2e-locator='console-run-button']",
    "result_accepted": "text=Accepted",
    "result_wrong": "text=Wrong Answer",
}

# URLs
LEETCODE_BASE_URL = "https://leetcode.com"
BYTESONE_BASE_URL = "https://www.bytsone.com"

# Timeouts (in milliseconds)
TIMEOUT_SHORT = 5000
TIMEOUT_MEDIUM = 15000
TIMEOUT_LONG = 30000
TIMEOUT_EXTRA_LONG = 60000

# Retry Configuration
MAX_SOLVER_RETRIES = 3
SOLVER_RETRY_DELAY = 5

# Progress States
STATE_NOT_STARTED = "not_started"
STATE_IN_PROGRESS = "in_progress"
STATE_COMPLETED = "completed"

# Problem Status
PROBLEM_UNSOLVED = "unsolved"
PROBLEM_SOLVED = "solved"
PROBLEM_IN_PROGRESS = "in_progress"
