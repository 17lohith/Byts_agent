"""Progress tracking — nested per course / day / problem."""

import json
import os
from typing import Dict, Any, List

from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class ProgressTracker:
    """
    Tracks completed problems with structure:
    {
      "class_problems": {
        "day_1": ["two-sum", "best-time-to-buy-and-sell-stock"],
        "day_2": [...]
      },
      "task_problems": {
        "day_1": [...],
        ...
      },
      "failed": {
        "class_problems": {"day_1": ["problem-id"]},
        "task_problems": {}
      }
    }
    """

    def __init__(self, filepath: str):
        self.filepath = filepath
        self.data: Dict[str, Any] = self._load()

    # ── persistence ────────────────────────────────────────────────────────────

    def _load(self) -> Dict[str, Any]:
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                logger.warning(f"Could not read {self.filepath} — starting fresh")
        return {"class_problems": {}, "task_problems": {}, "failed": {"class_problems": {}, "task_problems": {}}}

    def save(self):
        with open(self.filepath, "w") as f:
            json.dump(self.data, f, indent=2)

    # ── completion checks ───────────────────────────────────────────────────────

    def is_completed(self, course: str, day: str, problem_id: str) -> bool:
        """Return True if this problem was already solved and marked complete."""
        return problem_id in self.data.get(course, {}).get(day, [])

    def get_completed_problems(self, course: str, day: str) -> List[str]:
        return self.data.get(course, {}).get(day, [])

    def is_day_complete(self, course: str, day: str, total_problems: int) -> bool:
        return len(self.get_completed_problems(course, day)) >= total_problems

    # ── state mutations ─────────────────────────────────────────────────────────

    def mark_completed(self, course: str, day: str, problem_id: str):
        if course not in self.data:
            self.data[course] = {}
        if day not in self.data[course]:
            self.data[course][day] = []
        if problem_id not in self.data[course][day]:
            self.data[course][day].append(problem_id)
        # Remove from failed if it was there
        failed = self.data.get("failed", {}).get(course, {}).get(day, [])
        if problem_id in failed:
            failed.remove(problem_id)
        self.save()
        logger.info(f"Progress saved: {course} / {day} / {problem_id}")

    def mark_failed(self, course: str, day: str, problem_id: str):
        failed = self.data.setdefault("failed", {})
        failed.setdefault(course, {}).setdefault(day, [])
        if problem_id not in failed[course][day]:
            failed[course][day].append(problem_id)
        self.save()

    # ── stats ───────────────────────────────────────────────────────────────────

    @property
    def stats(self) -> Dict[str, int]:
        total = sum(
            len(problems)
            for course in ("class_problems", "task_problems")
            for problems in self.data.get(course, {}).values()
        )
        failed = sum(
            len(problems)
            for course_dict in self.data.get("failed", {}).values()
            for problems in course_dict.values()
        )
        return {"completed": total, "failed": failed}
