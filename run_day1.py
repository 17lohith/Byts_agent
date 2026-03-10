"""
Direct Day 1 completion script for:
  Karunya 2028 Product Fit - Class Problems - ( 9-3-2026 to 13-3-2026)

Strategy:
  1. Navigate directly to the Day 1 module page (e4bc254f section)
  2. Detect all problem titles in the right content panel (x > 600)
  3. For each problem: click via page.mouse.click, wait for URL to change to
     course-player format (4 UUIDs), then Activate → Take Challenge → Solve → Mark Complete
"""

import sys
import time
import re
import logging

from src.config.settings import settings
from src.utils.logger import setup_logger
from src.browser.manager import BrowserManager
from src.auth.session import ensure_bytesone_login, ensure_leetcode_login
from src.leetcode.solver import LeetCodeSolver
from src.bytesone.navigator import BytesOneNavigator
from src.state.progress import ProgressTracker

logger = setup_logger("run_day1")

# ── Constants ──────────────────────────────────────────────────────────────────

COURSE_KEY   = "class_problems"
DAY_KEY      = "day_1"
COURSE_ID    = "30cc6dab-07a7-40b7-b63f-9476c892537a"
# Day 1 content module UUID (contains matrix/hash-map problems for this week)
DAY1_MODULE_UUID = "e4bc254f-039e-4484-a722-57ef4b56aed5"
DAY1_MODULE_URL  = f"https://www.bytsone.com/home/course/{COURSE_ID}/active/{DAY1_MODULE_UUID}"

UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I
)

JUNK_TITLES = {
    "toggle sidebar", "bytsone", "back", "curriculum", "goal",
    "analytics", "leaderboard", "certificate", "communication channel",
    "chapters", "select module", "earn certificate", "continue learning",
    "start learning", "activate", "log out", "dashboard", "explore",
    "assessments", "schedule", "live session", "ide", "resume builder",
    "notifications", "settings", "profile", "certificate available",
    "5 chapters", "overall report", "contest calendar", "mentoring support",
}


def _slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9\s-]", "", text.lower().strip())
    return re.sub(r"\s+", "-", s).strip("-")


def get_day1_problems(page) -> list:
    """
    Navigate to the Day 1 module URL and return a list of
    {'title', 'x', 'y', 'completed'} dicts for each problem in the
    right content panel (x > 300).
    """
    page.goto(DAY1_MODULE_URL)
    page.wait_for_load_state("load")
    page.wait_for_timeout(2500)

    items = page.evaluate("""
        () => {
            const results = [];
            const seen = new Set();
            document.querySelectorAll('span, div').forEach(el => {
                // leaf-ish nodes only
                if (el.children.length > 2) return;
                const t = (el.textContent || '').trim().replace(/\\s+/g, ' ');
                if (!t || t.length < 3 || t.length > 80) return;
                const r = el.getBoundingClientRect();
                if (r.x < 300 || r.height <= 0 || r.width < 40) return;

                if (seen.has(t)) return;
                seen.add(t);

                // detect completion: check-circle / completed icon in parent HTML
                let node = el;
                let isDone = false;
                for (let i = 0; i < 6; i++) {
                    if (!node) break;
                    const h = node.innerHTML || '';
                    if (/check.*circle|done|completed|fa-check/i.test(h) && el !== node) {
                        isDone = true; break;
                    }
                    node = node.parentElement;
                }

                results.push({
                    title: t,
                    x: Math.round(r.x + r.width / 2),
                    y: Math.round(r.y + r.height / 2),
                    completed: isDone
                });
            });
            return results;
        }
    """)

    logger.debug(f"Raw items from DOM (before filter): {[i['title'] for i in items]}")

    problems = []
    for item in items:
        lower = item["title"].lower()
        if lower in JUNK_TITLES:
            continue
        if any(lower.startswith(j) for j in ["day ", "karunya", "toggle",
                                               "course content", "select",
                                               "1. day", "2. day", "3. day"]):
            continue
        if "%" in item["title"] or "karunya" in lower:
            continue
        problems.append(item)

    if not problems:
        # Fallback: if nothing detected after filters, log coordinate distribution
        logger.warning(f"No problems after filter. Raw count={len(items)}, "
                       f"first 15 raw titles: {[i['title'] for i in items[:15]]}")
        logger.warning(f"x-coords of raw items: {sorted(set(i['x'] for i in items))[:30]}")

    return problems


def click_problem_and_wait(page, item: dict) -> bool:
    """
    Click a problem in the content panel.
    Primary: Playwright text-based locator (no href, just text match scoped to right panel).
    Fallback: pixel-based mouse.click using stored coordinates.
    Waits for React router to navigate to the course player URL (≥3 UUIDs) or for
    Activate/Take Challenge button to appear.
    """
    before_url = page.url
    title = item["title"]
    clicked = False

    # Strategy 1: text-based click (precise — matches only exact text)
    try:
        el = page.locator("span, div").filter(
            has_text=re.compile(r"^\s*" + re.escape(title) + r"\s*$")
        ).last  # use last to prefer content panel item over any nav duplicate
        el.wait_for(state="visible", timeout=3000)
        el.scroll_into_view_if_needed()
        el.click()
        clicked = True
        logger.debug(f"  Clicked '{title}' via text locator")
    except Exception as e:
        logger.debug(f"  Text-locator click failed ({e}), trying pixel coords")

    # Strategy 2: pixel-based mouse click
    if not clicked:
        page.mouse.click(item["x"], item["y"])
        clicked = True
        logger.debug(f"  Clicked '{title}' at ({item['x']}, {item['y']})")

    # Wait for navigation or button appearance
    for _ in range(16):
        page.wait_for_timeout(500)
        cur = page.url
        if cur != before_url:
            uuid_count = len(UUID_RE.findall(cur))
            if uuid_count >= 3:
                logger.info(f"  Navigated to player URL ✅")
                return True
        for selector in ["button:has-text('Take Challenge')", "button:has-text('Activate')",
                         "a:has-text('Take Challenge')", "a:has-text('Activate')"]:
            try:
                el = page.locator(selector).first
                el.wait_for(state="visible", timeout=300)
                logger.info(f"  Challenge/Activate button visible ✅")
                return True
            except Exception:
                pass

    logger.warning(f"  No navigation detected after click — URL: {page.url}")
    return False


def mark_complete_and_next(page) -> bool:
    """Click 'Mark as Complete', handle optional confirm dialog, click Next Lesson."""
    for sel in ["button:has-text('Mark as Complete')", "a:has-text('Mark as Complete')"]:
        try:
            btn = page.locator(sel).first
            btn.wait_for(state="visible", timeout=8000)
            btn.click()
            logger.info("  'Mark as Complete' clicked")
            page.wait_for_timeout(1500)
            break
        except Exception:
            continue

    # Handle optional confirm dialog
    for sel in ["button:has-text('Confirm Completion')", "button:has-text('Confirm')"]:
        try:
            btn = page.locator(sel).first
            btn.wait_for(state="visible", timeout=3000)
            btn.click()
            logger.info("  Completion confirmed ✅")
            page.wait_for_timeout(1000)
            return True
        except Exception:
            continue

    # Next Lesson
    try:
        nxt = page.locator("button:has-text('Next Lesson'), a:has-text('Next Lesson')").first
        nxt.wait_for(state="visible", timeout=4000)
        nxt.click()
        page.wait_for_timeout(1000)
        logger.info("  Next Lesson clicked")
    except Exception:
        pass
    return True


def solve_problem(page, browser, item: dict, progress: ProgressTracker, leetcode: LeetCodeSolver) -> bool:
    """
    Full flow for one problem already navigated to (course player page).
    Activate → Take Challenge → Solve on LeetCode → Mark Complete.
    """
    title = item["title"]
    problem_id = _slugify(title)
    problem_url = page.url  # save for return trip

    # 1. Click Activate if present
    for sel in ["button:has-text('Activate')", "a:has-text('Activate')"]:
        try:
            btn = page.locator(sel).first
            btn.wait_for(state="visible", timeout=4000)
            btn.click()
            logger.info(f"  Activated ✅")
            page.wait_for_timeout(2000)
            break
        except Exception:
            pass

    # 2. Click Take Challenge
    challenge_clicked = False
    for sel in ["button:has-text('Take Challenge')", "a:has-text('Take Challenge')",
                "button:has-text('Start Challenge')"]:
        try:
            btn = page.locator(sel).first
            btn.wait_for(state="visible", timeout=8000)
            btn.click()
            logger.info(f"  'Take Challenge' clicked ✅")
            page.wait_for_timeout(1500)
            challenge_clicked = True
            break
        except Exception:
            pass

    if not challenge_clicked:
        # dump buttons
        try:
            btns = page.evaluate(
                "() => Array.from(document.querySelectorAll('button,a')).map(b=>(b.textContent||'').trim()).filter(t=>t&&t.length<60)"
            )
            logger.error(f"  'Take Challenge' not found. Visible: {btns[:15]}")
        except Exception:
            pass
        return False

    # 3. Handle contest dialog (Continue + checkbox + Start Contest)
    page.wait_for_timeout(2000)
    # Step A: Continue
    for sel in ["button:has-text('Continue')", "button:has-text('OK')"]:
        try:
            btn = page.locator(sel).first
            btn.wait_for(state="visible", timeout=4000)
            btn.click()
            page.wait_for_timeout(1500)
            break
        except Exception:
            pass
    # Step B: checkbox
    for sel in ["input[type='checkbox']", "[role='checkbox']"]:
        try:
            cb = page.locator(sel).first
            cb.wait_for(state="visible", timeout=3000)
            try:
                if not cb.is_checked():
                    cb.click()
            except Exception:
                cb.click()
            page.wait_for_timeout(700)
            break
        except Exception:
            pass
    # Step C: Start Contest
    started = False
    for sel in ["button:has-text('Start Contest')", "button:has-text('Start')"]:
        try:
            btn = page.locator(sel).first
            btn.wait_for(state="visible", timeout=5000)
            btn.click()
            logger.info("  Contest dialog confirmed ✅")
            page.wait_for_timeout(1500)
            started = True
            break
        except Exception:
            pass
    if not started:
        logger.error("  Contest dialog not confirmed")
        return False

    # 4. Wait for LeetCode tab
    logger.info("  Waiting for LeetCode tab …")
    lc_page = None
    for _ in range(40):
        page.wait_for_timeout(500)
        for p in browser._context.pages:
            if "leetcode.com" in p.url and "blank" not in p.url:
                lc_page = p
                break
        if lc_page:
            break

    if lc_page is None:
        logger.error("  LeetCode tab never opened")
        return False

    lc_page.wait_for_load_state("load")
    logger.info(f"  Switched to LeetCode: {lc_page.url}")

    # 5. Solve
    old_page = page
    leetcode.page = lc_page
    success = leetcode.solve_current_problem()

    lc_page.close()
    leetcode.page = old_page
    logger.info("  LeetCode tab closed")

    if not success:
        logger.error(f"  LeetCode solve failed for '{title}'")
        return False

    # 6. Return to problem page and mark complete
    old_page.goto(problem_url)
    old_page.wait_for_load_state("load")
    old_page.wait_for_timeout(1500)

    mark_complete_and_next(old_page)

    progress.mark_completed(COURSE_KEY, DAY_KEY, problem_id)
    logger.info(f"  ✅ '{title}' DONE — saved to progress")
    return True


def main():
    logger.info("=" * 60)
    logger.info("  Day 1 Completion Runner — Class Problems (9-3-2026)")
    logger.info("=" * 60)

    progress = ProgressTracker(settings.progress_file)

    with BrowserManager() as browser:
        page = browser.page

        # Ensure logins (retry up to 3x for transient network errors)
        for attempt in range(3):
            try:
                ok = ensure_bytesone_login(
                    page=page, bytesone_url=settings.bytesone_url,
                    email=settings.bytesone_email, login_wait_timeout=settings.login_wait_timeout,
                    first_run=False,
                )
                if ok:
                    break
            except Exception as e:
                logger.warning(f"BytsOne login attempt {attempt+1} failed: {e}")
                page.wait_for_timeout(3000)
        else:
            logger.error("BytsOne login failed after retries")
            sys.exit(1)

        for attempt in range(3):
            try:
                ok = ensure_leetcode_login(
                    page=page, leetcode_url="https://leetcode.com/problemset/",
                    email=settings.leetcode_email, login_wait_timeout=settings.login_wait_timeout,
                    first_run=False,
                )
                if ok:
                    break
            except Exception as e:
                logger.warning(f"LeetCode login attempt {attempt+1} failed: {e}")
                page.wait_for_timeout(3000)
        else:
            logger.error("LeetCode login failed after retries")
            sys.exit(1)
        browser.save_session()

        leetcode = LeetCodeSolver(page)
        solved = failed = skipped = 0

        # ── Main loop ──────────────────────────────────────────────────────────
        # We may need to iterate multiple times because clicking a problem
        # navigates away; after returning we re-fetch the problem list.

        MAX_ROUNDS = 8
        for round_num in range(1, MAX_ROUNDS + 1):
            problems = get_day1_problems(page)

            if not problems:
                logger.warning("No problems found on Day 1 module page — done or detection failed")
                break

            logger.info(f"\nRound {round_num} — found {len(problems)} items:")
            for p in problems:
                pid = _slugify(p["title"])
                done = progress.is_completed(COURSE_KEY, DAY_KEY, pid)
                logger.info(f"  {'✓' if done else '○'} {p['title']}")

            pending = [
                p for p in problems
                if not progress.is_completed(COURSE_KEY, DAY_KEY, _slugify(p["title"]))
            ]

            if not pending:
                logger.info("All Day 1 problems are done! 🎉")
                break

            # Process the first pending problem this round
            item = pending[0]
            title = item["title"]
            logger.info(f"\n── Processing: {title} ──")

            # Navigate to module page and click
            ok = click_problem_and_wait(page, item)
            if not ok:
                logger.warning(f"  Could not navigate into '{title}' — skipping")
                progress.mark_failed(COURSE_KEY, DAY_KEY, _slugify(title))
                failed += 1
                continue

            # Retry solve up to 2 times on network errors
            result = False
            for _solve_attempt in range(2):
                try:
                    result = solve_problem(page, browser, item, progress, leetcode)
                    break
                except Exception as e:
                    if "ERR_NETWORK" in str(e) or "SUSPENDED" in str(e) or "CHANGED" in str(e):
                        logger.warning(f"  Network error on attempt {_solve_attempt+1}, retrying in 5s: {e}")
                        page.wait_for_timeout(5000)
                    else:
                        logger.error(f"  Unexpected error: {e}")
                        break
            if result:
                solved += 1
            else:
                failed += 1

            time.sleep(1)

        logger.info(f"\n{'='*60}")
        logger.info(f"  DONE — solved: {solved}  skipped: {skipped}  failed: {failed}")
        logger.info(f"{'='*60}")


if __name__ == "__main__":
    main()
