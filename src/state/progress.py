"""Progress tracking — persists solved/failed problems across runs."""

import json
import os
from typing import Dict, Any

from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class ProgressTracker:
    def __init__(self, filepath: str):
        self.filepath = filepath
        self.data: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                logger.warning(f"Could not read {self.filepath}, starting fresh")
        return {"completed": [], "failed": []}

    def save(self):
        with open(self.filepath, "w") as f:
            json.dump(self.data, f, indent=2)

    def is_completed(self, problem_id: str) -> bool:
        return problem_id in self.data["completed"]

    def mark_completed(self, problem_id: str):
        if problem_id not in self.data["completed"]:
            self.data["completed"].append(problem_id)
        # Remove from failed if it was there
        self.data["failed"] = [p for p in self.data["failed"] if p != problem_id]
        self.save()
        logger.info(f"Progress saved — completed: {problem_id}")

    def mark_failed(self, problem_id: str):
        if problem_id not in self.data["failed"]:
            self.data["failed"].append(problem_id)
        self.save()

    @property
    def stats(self) -> Dict[str, int]:
        return {
            "completed": len(self.data["completed"]),
            "failed": len(self.data["failed"]),
        }
