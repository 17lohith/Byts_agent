"""
Session manager — orchestrates first-run login and subsequent re-login checks.
"""

import os
from playwright.sync_api import Page

from src.auth.google_oauth import wait_for_manual_login, handle_google_relogin
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

# Selectors that confirm the user is logged in on each site
BYTESONE_LOGGED_IN = "button:has-text('Courses'), [class*='sidebar'], nav"

# LeetCode login detection: look for user avatar/menu elements in current UI.
# Falls back to URL-based check in _is_leetcode_logged_in().
LEETCODE_LOGGED_IN_SELECTORS = [
    "[class*='nav-user-icon']",
    "img[alt='avatar']",
    "a[href*='/u/']",          # profile link e.g. /u/username/
    "#navbar-right",
    ".nav-user-icon-base",
]
# Selector that should NOT be visible when logged in
LEETCODE_SIGNOUT_INDICATOR = "a[href*='/accounts/login'], button:has-text('Sign in'), a:has-text('Sign In')"


def is_first_run(session_file: str) -> bool:
    return not os.path.exists(session_file)


def ensure_bytesone_login(page: Page, bytesone_url: str, email: str,
                           login_wait_timeout: int, first_run: bool) -> bool:
    """
    Navigate to BytsOne and ensure we are logged in.

    - first_run=True  → wait for manual login
    - first_run=False → check if logged in; auto re-login if not
    """
    logger.info(f"Checking BytsOne login … ({bytesone_url})")
    page.goto(bytesone_url)
    page.wait_for_load_state("networkidle")

    if _is_logged_in(page, BYTESONE_LOGGED_IN):
        logger.info("BytsOne: already logged in ✅")
        return True

    if first_run:
        return wait_for_manual_login(
            page,
            site_name="BytsOne",
            dashboard_indicator=BYTESONE_LOGGED_IN,
            timeout_ms=login_wait_timeout,
        )
    else:
        logger.info("BytsOne session expired — attempting auto re-login …")
        ok = handle_google_relogin(page, expected_email=email, site_name="BytsOne")
        if ok:
            page.wait_for_load_state("networkidle")
        return ok


def ensure_leetcode_login(page: Page, leetcode_url: str, email: str,
                           login_wait_timeout: int, first_run: bool) -> bool:
    """
    Navigate to LeetCode and ensure we are logged in.
    """
    logger.info(f"Checking LeetCode login … ({leetcode_url})")
    page.goto(leetcode_url)
    page.wait_for_load_state("networkidle")

    if _is_leetcode_logged_in(page):
        logger.info("LeetCode: already logged in ✅")
        return True

    if first_run:
        return _wait_for_leetcode_manual_login(page, login_wait_timeout)
    else:
        logger.info("LeetCode session expired — attempting auto re-login …")
        ok = handle_google_relogin(page, expected_email=email, site_name="LeetCode")
        if ok:
            page.wait_for_load_state("networkidle")
        return ok


# ── internal ───────────────────────────────────────────────────────────────────

def _is_logged_in(page: Page, selector: str) -> bool:
    """Return True if any of the comma-separated selectors is visible."""
    for sel in selector.split(", "):
        try:
            page.locator(sel.strip()).first.wait_for(state="visible", timeout=5_000)
            return True
        except Exception:
            continue
    return False


def _is_leetcode_logged_in(page: Page) -> bool:
    """
    LeetCode login check — two strategies:
    1. Look for known logged-in UI elements (avatar, profile link, etc.)
    2. Confirm no "Sign In" button is present on the page
    Both must agree to avoid false positives.
    """
    # Strategy 1: look for logged-in element
    for sel in LEETCODE_LOGGED_IN_SELECTORS:
        try:
            page.locator(sel).first.wait_for(state="visible", timeout=3_000)
            logger.debug(f"LeetCode logged-in selector matched: {sel}")
            return True
        except Exception:
            continue

    # Strategy 2: if we're on leetcode.com and there's no sign-in button → logged in
    current_url = page.url
    if "leetcode.com" in current_url and "accounts/login" not in current_url:
        sign_in_visible = False
        try:
            page.locator(LEETCODE_SIGNOUT_INDICATOR).first.wait_for(
                state="visible", timeout=3_000
            )
            sign_in_visible = True
        except Exception:
            pass

        if not sign_in_visible:
            logger.debug("LeetCode: on leetcode.com with no sign-in button → logged in")
            return True

    return False


def _wait_for_leetcode_manual_login(page: Page, timeout_ms: int) -> bool:
    """
    Wait for the user to complete LeetCode login manually.
    Polls every 2 seconds instead of relying on a single unreliable selector.
    """
    import time
    logger.info(
        f"\n{'='*60}\n"
        "  ACTION REQUIRED — Please log in to LeetCode in the browser window.\n"
        f"  Waiting up to {timeout_ms // 1000} seconds …\n"
        f"{'='*60}"
    )
    elapsed = 0
    poll_interval = 2_000  # ms
    while elapsed < timeout_ms:
        page.wait_for_timeout(poll_interval)
        elapsed += poll_interval
        if _is_leetcode_logged_in(page):
            logger.info("Login to LeetCode detected ✅")
            return True
        logger.debug(f"Still waiting for LeetCode login … ({elapsed // 1000}s)")

    logger.error("Timed out waiting for LeetCode login")
    return False
