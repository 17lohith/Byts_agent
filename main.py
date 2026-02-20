"""Entry point — BytsOne Automation Bot."""

from src.config.settings import settings
from src.utils.logger import setup_logger
from src.browser.manager import BrowserManager
from src.bytesone.navigator import BytesOneNavigator
from src.leetcode.solver import LeetCodeSolver
from src.ai.solver import LLMSolver
from src.state.progress import ProgressTracker

logger = setup_logger("main")


def main():
    logger.info("🤖 BytsOne Automation Bot starting…")

    progress = ProgressTracker(settings.progress_file)
    llm = LLMSolver()

    with BrowserManager() as browser:
        bytesone = BytesOneNavigator(browser.page)
        leetcode = LeetCodeSolver(browser.page, llm)

        if not bytesone.navigate_to_course():
            logger.error("Failed to open the course. Check COURSE_NAME in .env.")
            return

        problems = bytesone.get_problem_links()
        if not problems:
            logger.warning("No LeetCode problem links found on the course page.")
            return

        logger.info(f"Processing {len(problems)} problem(s)…")
        solved = skipped = failed = 0

        for i, problem in enumerate(problems, 1):
            url = problem["url"]
            problem_id = url.rstrip("/").split("/")[-1]

            if progress.is_completed(problem_id):
                logger.info(f"[{i}/{len(problems)}] Already done — skipping: {problem_id}")
                skipped += 1
                continue

            logger.info(f"[{i}/{len(problems)}] Starting: {problem['title']}")
            success = leetcode.solve_problem(url)

            if success:
                progress.mark_completed(problem_id)
                # Go back to BytsOne and mark the challenge complete
                bytesone.navigate_to_course()
                bytesone.mark_completed()
                solved += 1
            else:
                progress.mark_failed(problem_id)
                failed += 1

    logger.info(
        f"\n📊 Done!  Solved: {solved}  |  Skipped: {skipped}  |  Failed: {failed}"
    )


if __name__ == "__main__":
    main()
