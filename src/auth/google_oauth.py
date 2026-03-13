"""
Google OAuth handler.

Handles two scenarios:
  1. First-run  → pause and wait for the human to complete login manually,
                  then capture which email was used.
  2. Re-login   → automatically click the correct Google account from the
                  account picker (or type the email if picker not shown).
"""

import time
from playwright.sync_api import Page, TimeoutError as PWTimeout

from src.config.constants import GOOGLE_SELECTORS, TIMEOUT_SHORT, TIMEOUT_MEDIUM
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


# ── helpers ────────────────────────────────────────────────────────────────────

def _locator_visible(page: Page, selector: str, timeout: int = TIMEOUT_SHORT) -> bool:
    try:
        page.locator(selector).first.wait_for(state="visible", timeout=timeout)
        return True
    except PWTimeout:
        return False


def _click_first_visible(page: Page, *selectors: str) -> bool:
    """Try each selector in order, click the first visible one."""
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            loc.wait_for(state="visible", timeout=TIMEOUT_SHORT)
            loc.click()
            return True
        except PWTimeout:
            continue
    return False


# ── public API ─────────────────────────────────────────────────────────────────

def wait_for_manual_login(page: Page, site_name: str, dashboard_indicator: str,
                           timeout_ms: int = 300_000) -> bool:
    """
    Block until the user completes login manually.

    `dashboard_indicator` is a selector that only appears when the user is
    successfully logged in (e.g. the sidebar or profile avatar).

    Returns True when login is detected, False on timeout.
    """
    logger.info(
        f"\n{'='*60}\n"
        f"  ACTION REQUIRED — Please log in to {site_name} in the browser window.\n"
        f"  Waiting up to {timeout_ms // 1000} seconds …\n"
        f"{'='*60}"
    )
    try:
        page.locator(dashboard_indicator).first.wait_for(
            state="visible", timeout=timeout_ms
        )
        logger.info(f"Login to {site_name} detected ✅")
        return True
    except PWTimeout:
        logger.error(f"Timed out waiting for {site_name} login")
        return False


def handle_google_relogin(page: Page, expected_email: str, site_name: str) -> bool:
    """
    Automatically handle Google OAuth re-login.

    Flow:
      1. Click the site's "Sign in with Google" button.
      2. On Google account picker → click the row matching expected_email.
         If that row is not shown → click "Use another account" and type the email.
      3. Wait to be redirected back (Google URL disappears).

    Returns True if re-login succeeded.
    """
    from src.config.constants import (
        BYTESONE_SELECTORS, LEETCODE_SELECTORS, GOOGLE_ACCOUNTS_URL,
        TIMEOUT_MEDIUM, TIMEOUT_LONG,
    )

    logger.info(f"Auto re-login for {site_name} with {expected_email} …")

    # --- Step 1: click site's Google sign-in button -------------------------
    site_google_btns = (
        BYTESONE_SELECTORS["google_signin_btn"]
        if "byts" in site_name.lower()
        else LEETCODE_SELECTORS["google_signin_btn"]
    )
    clicked = _click_first_visible(page, *site_google_btns)
    if not clicked:
        logger.error("Could not find 'Sign in with Google' button")
        return False

    # --- Step 2: wait for Google accounts page ------------------------------
    try:
        page.wait_for_url(f"{GOOGLE_ACCOUNTS_URL}/**", timeout=TIMEOUT_MEDIUM)
    except PWTimeout:
        logger.warning("Didn't navigate to Google accounts page — might be auto-selected")

    time.sleep(1)  # let the picker render

    # --- Step 3: pick the right account -------------------------------------
    if _locator_visible(page, GOOGLE_SELECTORS["account_picker"]):
        # Account picker is shown — look for our email
        account_rows = page.locator(GOOGLE_SELECTORS["account_email_text"]).all()
        found = False
        for row in account_rows:
            text = row.inner_text().strip().lower()
            if expected_email.lower() in text:
                row.click()
                found = True
                logger.info(f"Clicked account: {expected_email}")
                break

        if not found:
            # Our email not in picker → use another account
            logger.info(f"{expected_email} not in picker — clicking 'Use another account'")
            if not _click_first_visible(page, GOOGLE_SELECTORS["use_another_account"]):
                logger.error("Could not find 'Use another account' option")
                return False
            _enter_email(page, expected_email)

    elif _locator_visible(page, GOOGLE_SELECTORS["email_input"]):
        # Straight email entry form (no picker)
        _enter_email(page, expected_email)
    else:
        logger.warning("Unknown Google login state — waiting for redirect …")

    # --- Step 4: handle any consent / continue button -----------------------
    time.sleep(2)
    _click_first_visible(page, GOOGLE_SELECTORS["continue_btn"])

    # --- Step 5: wait to leave Google domain --------------------------------
    try:
        page.wait_for_function(
            "() => !window.location.hostname.includes('accounts.google.com')",
            timeout=TIMEOUT_LONG,
        )
        logger.info(f"Re-login to {site_name} succeeded ✅")
        return True
    except PWTimeout:
        logger.error(f"Still on Google page after re-login attempt for {site_name}")
        return False


# ── internal ───────────────────────────────────────────────────────────────────

def _enter_email(page: Page, email: str):
    """Type email into Google's email input and press Next."""
    try:
        inp = page.locator(GOOGLE_SELECTORS["email_input"]).first
        inp.wait_for(state="visible", timeout=TIMEOUT_MEDIUM)
        inp.fill(email)
        time.sleep(0.5)
        _click_first_visible(page, GOOGLE_SELECTORS["email_next"])
        logger.info(f"Entered email: {email}")
    except PWTimeout:
        logger.error("Could not find Google email input field")
