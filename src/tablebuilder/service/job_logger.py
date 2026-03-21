# ABOUTME: Job event logger with screenshot capture for production debugging.
# ABOUTME: Records every state transition and captures browser screenshots at each step.

from pathlib import Path

from tablebuilder.logging_config import get_logger
from tablebuilder.service.db import ServiceDB

logger = get_logger("tablebuilder.service.job_logger")


class JobLogger:
    """Logs job events and captures screenshots for a single job run."""

    def __init__(self, db: ServiceDB, job_id: str, results_dir: Path):
        self.db = db
        self.job_id = job_id
        self.results_dir = results_dir
        self._screenshot_counter = 0

    def _screenshots_dir(self) -> Path:
        d = self.results_dir / self.job_id / "screenshots"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def log_progress(self, message: str) -> None:
        self.db.add_event(self.job_id, event_type="progress", message=message)
        self.db.update_progress(self.job_id, message)
        logger.info("Job %s: %s", self.job_id[:8], message)

    def log_warning(self, message: str, detail: str = "") -> None:
        self.db.add_event(
            self.job_id, event_type="warning", message=message, detail=detail
        )
        logger.warning("Job %s: %s", self.job_id[:8], message)

    def log_error(self, message: str, detail: str = "") -> None:
        self.db.add_event(
            self.job_id, event_type="error", message=message, detail=detail
        )
        logger.error("Job %s: %s", self.job_id[:8], message)

    def capture_screenshot(self, page, label: str) -> str:
        """Take a screenshot and log it. Returns the file path, or empty string on error."""
        self._screenshot_counter += 1
        filename = f"{self._screenshot_counter:03d}_{label}.png"
        filepath = self._screenshots_dir() / filename
        try:
            page.screenshot(path=str(filepath))
            self.db.add_event(
                self.job_id,
                event_type="screenshot",
                message=f"Screenshot: {label}",
                screenshot_path=str(filepath),
            )
            return str(filepath)
        except Exception as e:
            self.log_warning(
                f"Failed to capture screenshot '{label}': {e}"
            )
            return ""

    def save_page_state(self, page) -> str:
        """Save page HTML and URL for debugging. Returns HTML file path, or empty string on error."""
        try:
            html_content = page.content()
            url = page.url
            html_path = self.results_dir / self.job_id / "page_state.html"
            html_path.parent.mkdir(parents=True, exist_ok=True)
            html_path.write_text(
                f"<!-- URL: {url} -->\n{html_content}"
            )
            self.db.add_event(
                self.job_id,
                event_type="error",
                message=f"Page state saved (URL: {url})",
                detail=str(html_path),
            )
            return str(html_path)
        except Exception as e:
            logger.error("Failed to save page state for job %s: %s", self.job_id[:8], e)
            return ""
