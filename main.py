"""Entry point — BytsOne Automation Bot."""

import sys

from src.config.settings import settings
from src.utils.logger import setup_logger
from src.browser.manager import BrowserManager
from src.auth.session import (
    is_first_run,
    ensure_bytesone_login,
    ensure_leetcode_login,
)
from src.bytesone.navigator import BytesOneNavigator
from src.leetcode.solver import LeetCodeSolver
from src.ai.solver import LLMSolver
from src.state.progress import ProgressTracker
from src.config.constants import LEETCODE_BASE_URL

logger = setup_logger("main")


def main():
    logger.info("BytsOne Automation Bot starting …")

    # ── validate email config ──────────────────────────────────────────────────
    if not settings.bytesone_email or not settings.leetcode_email:
        logger.error(
            "BYTESONE_EMAIL and LEETCODE_EMAIL must be set in your .env file.\n"
            "  BYTESONE_EMAIL = your Karunya institutional email\n"
            "  LEETCODE_EMAIL = your personal Gmail"
        )
        sys.exit(1)

    first_run = is_first_run(settings.session_file)
    if first_run:
        logger.info(
            "\n" + "=" * 60 + "\n"
            "  FIRST RUN DETECTED\n"
            "  You will need to log in to both BytsOne and LeetCode\n"
            "  manually in the browser window that opens.\n"
            "  BytsOne  → use your Karunya email\n"
            "  LeetCode → use your personal Gmail\n"
            + "=" * 60
        )

    progress = ProgressTracker(settings.progress_file)
    llm = LLMSolver()

    with BrowserManager() as browser:
        page = browser.page

        # ── Step 1: BytsOne login ──────────────────────────────────────────────
        bytesone_ok = ensure_bytesone_login(
            page=page,
            bytesone_url=settings.bytesone_url,
            email=settings.bytesone_email,
            login_wait_timeout=settings.login_wait_timeout,
            first_run=first_run,
        )
        if not bytesone_ok:
            logger.error("Could not log in to BytsOne — aborting")
            sys.exit(1)

        # ── Step 2: LeetCode login ─────────────────────────────────────────────
        leetcode_ok = ensure_leetcode_login(
            page=page,
            leetcode_url=f"{LEETCODE_BASE_URL}/problemset/",
            email=settings.leetcode_email,
            login_wait_timeout=settings.login_wait_timeout,
            first_run=first_run,
        )
        if not leetcode_ok:
            logger.error("Could not log in to LeetCode — aborting")
            sys.exit(1)

        # ── Step 3: Save session after successful login ────────────────────────
        browser.save_session()

        # ── Step 4: Navigate to course ─────────────────────────────────────────
        bytesone_nav = BytesOneNavigator(page)
        if not bytesone_nav.navigate_to_course():
            logger.error("Failed to open the course. Check COURSE_NAME in .env.")
            sys.exit(1)

        problems = bytesone_nav.get_problem_links()
        if not problems:
            logger.warning("No LeetCode problem links found on the course page.")
            sys.exit(0)

        logger.info(f"Processing {len(problems)} problem(s) …")

        # ── Step 5: Solve loop ─────────────────────────────────────────────────
        leetcode_solver = LeetCodeSolver(page, llm)
        solved = skipped = failed = 0

        for i, problem in enumerate(problems, 1):
            url = problem["url"]
            problem_id = url.rstrip("/").split("/")[-1]

            if progress.is_completed(problem_id):
                logger.info(f"[{i}/{len(problems)}] Already done — skipping: {problem_id}")
                skipped += 1
                continue

            logger.info(f"[{i}/{len(problems)}] Starting: {problem['title']}")
            success = leetcode_solver.solve_problem(url)

            if success:
                progress.mark_completed(problem_id)
                # Go back to BytsOne and mark the challenge complete
                bytesone_nav.navigate_to_course()
                bytesone_nav.mark_completed()
                solved += 1
            else:
                # Check if this failure was a login wall — re-auth and retry once
                if _needs_relogin(page):
                    logger.info("LeetCode login expired mid-run — re-authenticating …")
                    reauth_ok = ensure_leetcode_login(
                        page=page,
                        leetcode_url=f"{LEETCODE_BASE_URL}/problemset/",
                        email=settings.leetcode_email,
                        login_wait_timeout=settings.login_wait_timeout,
                        first_run=False,
                    )
                    if reauth_ok:
                        browser.save_session()
                        # Retry the current problem once after re-login
                        success = leetcode_solver.solve_problem(url)
                        if success:
                            progress.mark_completed(problem_id)
                            bytesone_nav.navigate_to_course()
                            bytesone_nav.mark_completed()
                            solved += 1
                            continue

                progress.mark_failed(problem_id)
                failed += 1

    logger.info(
        f"\nDone!  Solved: {solved}  |  Skipped: {skipped}  |  Failed: {failed}"
    )


def _needs_relogin(page) -> bool:
    """Quick check if the current page is a login wall."""
    from src.config.constants import LEETCODE_SELECTORS
    for sel in LEETCODE_SELECTORS["login_wall"]:
        try:
            page.locator(sel).first.wait_for(state="visible", timeout=3_000)
            return True
        except Exception:
            continue
    return False


if __name__ == "__main__":
    main()
