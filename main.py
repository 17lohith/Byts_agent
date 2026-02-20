"""Entry point — BytsOne Automation Bot."""

import sys
import time

from src.config.settings import settings
from src.config.constants import COURSE_CLASS, COURSE_TASK
from src.utils.logger import setup_logger
from src.browser.manager import BrowserManager
from src.auth.session import (
    is_first_run,
    ensure_bytesone_login,
    ensure_leetcode_login,
)
from src.bytesone.navigator import BytesOneNavigator
from src.leetcode.solver import LeetCodeSolver
from src.state.progress import ProgressTracker

logger = setup_logger("main")

# ── helpers ────────────────────────────────────────────────────────────────────

def _slugify(title: str) -> str:
    """Convert a problem title to a URL-style slug for progress tracking."""
    import re
    slug = title.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug)
    return slug


def _day_key(day_num: int) -> str:
    return f"day_{day_num}"


def _reauth_leetcode(page, browser):
    """Re-authenticate LeetCode mid-run."""
    logger.info("LeetCode session expired — re-authenticating …")
    ok = ensure_leetcode_login(
        page=page,
        leetcode_url="https://leetcode.com/problemset/",
        email=settings.leetcode_email,
        login_wait_timeout=settings.login_wait_timeout,
        first_run=False,
    )
    if ok:
        browser.save_session()
    return ok


# ── core solver loop ───────────────────────────────────────────────────────────

def process_course(
    course_key: str,
    bytesone: BytesOneNavigator,
    leetcode: LeetCodeSolver,
    progress: ProgressTracker,
    browser: BrowserManager,
) -> dict:
    """
    Process all 6 days of a single course.
    Returns summary dict: solved / skipped / failed counts.
    """
    page = bytesone.page
    counts = {"solved": 0, "skipped": 0, "failed": 0}

    logger.info(f"\n{'='*60}")
    logger.info(f"  Starting course: {course_key.upper()}")
    logger.info(f"{'='*60}")

    # Open the course from the courses page
    if not bytesone.open_course(course_key):
        logger.error(f"Could not open course: {course_key}")
        return counts

    # Get chapter list (Day 1-6)
    chapters = bytesone.get_chapters()
    if not chapters:
        logger.error("No chapters found — check selectors")
        return counts

    for chapter in chapters:
        day_num = chapter["day_num"]
        day_key = _day_key(day_num)
        label   = chapter["label"]

        if chapter["locked"]:
            logger.warning(f"  [{label}] Locked 🔒 — skipping")
            continue

        logger.info(f"\n  ── {label} ({chapter['progress_pct']}%) ──")

        # Click the day to load its problem list
        bytesone.click_chapter(chapter)

        # Get problems for this day
        problems = bytesone.get_problems_in_chapter()
        if not problems:
            logger.warning(f"  [{label}] No problems found — skipping")
            continue

        for prob_idx, problem in enumerate(problems, 1):
            title      = problem["title"]
            problem_id = _slugify(title)
            label_str  = f"[{label} | {prob_idx}/{len(problems)}] {title}"

            # Skip if already tracked in progress.json
            if progress.is_completed(course_key, day_key, problem_id):
                logger.info(f"  {label_str} — already done ✅ skipping")
                counts["skipped"] += 1
                continue

            logger.info(f"  {label_str} — starting …")

            # Click the problem to open its detail page
            if not bytesone.click_problem(problem):
                logger.error(f"  {label_str} — could not open problem")
                counts["failed"] += 1
                continue

            # Check if BytsOne already shows it as completed (green check)
            if problem.get("completed"):
                logger.info(f"  {label_str} — already completed on BytsOne ✅")
                progress.mark_completed(course_key, day_key, problem_id)
                counts["skipped"] += 1
                continue

            # Click "Take Challenge"
            if not bytesone.click_take_challenge():
                logger.error(f"  {label_str} — 'Take Challenge' not found")
                progress.mark_failed(course_key, day_key, problem_id)
                counts["failed"] += 1
                continue

            # Handle the LeetCode contest confirmation dialog
            bytesone_url_before = page.url
            if not bytesone.handle_contest_dialog():
                logger.error(f"  {label_str} — could not confirm contest dialog")
                progress.mark_failed(course_key, day_key, problem_id)
                counts["failed"] += 1
                continue

            # Wait for LeetCode to load (redirect happens after dialog)
            try:
                page.wait_for_url("**/leetcode.com/**", timeout=30_000)
                page.wait_for_load_state("networkidle")
            except Exception:
                logger.warning("LeetCode URL wait timed out — checking current URL")

            # Check for login wall
            if leetcode._is_login_wall():
                if not _reauth_leetcode(page, browser):
                    logger.error("Re-auth failed — stopping")
                    sys.exit(1)

            # Solve the problem using Solutions tab
            success = leetcode.solve_current_problem()

            if not success:
                logger.error(f"  {label_str} — failed to solve")
                progress.mark_failed(course_key, day_key, problem_id)
                counts["failed"] += 1
                # Navigate back to BytsOne before continuing
                _return_to_bytesone(page, bytesone, course_key, bytesone_url_before)
                continue

            # ── Back to BytsOne: Mark as Complete ──────────────────────────────
            _return_to_bytesone(page, bytesone, course_key, bytesone_url_before)

            # Click Mark as Complete
            marked = bytesone.mark_complete()
            if not marked:
                logger.warning(f"  {label_str} — 'Mark as Complete' failed (continuing)")

            # Save progress
            progress.mark_completed(course_key, day_key, problem_id)
            counts["solved"] += 1
            logger.info(f"  {label_str} — SOLVED ✅")

            # Click Next Lesson to advance
            bytesone.click_next_lesson()
            time.sleep(0.5)

        logger.info(
            f"  [{label}] done — "
            f"solved: {counts['solved']}  skipped: {counts['skipped']}  failed: {counts['failed']}"
        )

        # Re-open the course page so the chapter sidebar is fresh for next day
        bytesone.open_course(course_key)
        chapters = bytesone.get_chapters()  # refresh chapter list after re-open

    return counts


def _return_to_bytesone(page, bytesone: BytesOneNavigator, course_key: str, fallback_url: str):
    """Navigate back to BytsOne problem page after LeetCode interaction."""
    # If we're still on LeetCode, go back
    if "leetcode.com" in page.url:
        page.go_back()
        page.wait_for_load_state("networkidle")

    # If that didn't work, go directly
    if "leetcode.com" in page.url or "bytsone.com" not in page.url:
        if fallback_url and "bytsone.com" in fallback_url:
            page.goto(fallback_url)
            page.wait_for_load_state("networkidle")
        else:
            bytesone.open_course(course_key)


# ── main ───────────────────────────────────────────────────────────────────────

def main():
    logger.info("BytsOne Automation Bot starting …")

    # Validate required config
    if not settings.bytesone_email or not settings.leetcode_email:
        logger.error(
            "BYTESONE_EMAIL and LEETCODE_EMAIL must be set in .env\n"
            "  BYTESONE_EMAIL = Karunya institutional email\n"
            "  LEETCODE_EMAIL = personal Gmail"
        )
        sys.exit(1)

    first_run = is_first_run(settings.session_file)
    if first_run:
        logger.info(
            "\n" + "=" * 60 + "\n"
            "  FIRST RUN — log in to both BytsOne and LeetCode\n"
            "  BytsOne  → Karunya email\n"
            "  LeetCode → personal Gmail\n"
            + "=" * 60
        )

    progress = ProgressTracker(settings.progress_file)

    with BrowserManager() as browser:
        page = browser.page

        # ── Auth ───────────────────────────────────────────────────────────────
        if not ensure_bytesone_login(
            page=page,
            bytesone_url=settings.bytesone_url,
            email=settings.bytesone_email,
            login_wait_timeout=settings.login_wait_timeout,
            first_run=first_run,
        ):
            logger.error("BytsOne login failed — aborting")
            sys.exit(1)

        if not ensure_leetcode_login(
            page=page,
            leetcode_url="https://leetcode.com/problemset/",
            email=settings.leetcode_email,
            login_wait_timeout=settings.login_wait_timeout,
            first_run=first_run,
        ):
            logger.error("LeetCode login failed — aborting")
            sys.exit(1)

        browser.save_session()

        # ── Solve ──────────────────────────────────────────────────────────────
        bytesone = BytesOneNavigator(page)
        leetcode = LeetCodeSolver(page)

        total = {"solved": 0, "skipped": 0, "failed": 0}

        for course_key in settings.courses_list:
            if course_key not in (COURSE_CLASS, COURSE_TASK):
                logger.warning(f"Unknown course key: {course_key} — skipping")
                continue

            result = process_course(
                course_key=course_key,
                bytesone=bytesone,
                leetcode=leetcode,
                progress=progress,
                browser=browser,
            )
            for k in total:
                total[k] += result[k]

        # ── Summary ────────────────────────────────────────────────────────────
        logger.info(
            f"\n{'='*60}\n"
            f"  DONE!\n"
            f"  Solved:  {total['solved']}\n"
            f"  Skipped: {total['skipped']}\n"
            f"  Failed:  {total['failed']}\n"
            f"{'='*60}"
        )


if __name__ == "__main__":
    main()
