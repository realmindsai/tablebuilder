# ABOUTME: Background worker thread that processes TableBuilder fetch jobs.
# ABOUTME: Calls the existing pipeline (login -> open dataset -> build table -> download).

import json
import sys
import threading
import traceback
import time
from pathlib import Path

from tablebuilder.browser import TableBuilderSession
from tablebuilder.config import Config
from tablebuilder.downloader import queue_and_download
from tablebuilder.knowledge import KnowledgeBase
from tablebuilder.logging_config import get_logger
from tablebuilder.models import TableRequest
from tablebuilder.navigator import open_dataset, SessionExpiredError
from tablebuilder.service.auth import decrypt_credentials
from tablebuilder.service.db import ServiceDB
from tablebuilder.service.job_logger import JobLogger
from tablebuilder.table_builder import build_table

logger = get_logger("tablebuilder.service.worker")


class Worker(threading.Thread):
    """Background thread that polls for queued jobs and runs them."""

    def __init__(
        self,
        db: ServiceDB,
        results_dir: Path,
        encryption_key: str,
        poll_interval: float = 5.0,
    ):
        super().__init__(daemon=True, name="tablebuilder-worker")
        self.db = db
        self.results_dir = results_dir
        self.encryption_key = encryption_key
        self.poll_interval = poll_interval
        self.knowledge = KnowledgeBase()
        self._stop_event = threading.Event()

    def run(self) -> None:
        logger.info("Worker started")
        while not self._stop_event.is_set():
            try:
                if not self.process_one_job():
                    self._stop_event.wait(self.poll_interval)
            except Exception:
                logger.exception("Unexpected worker error")
                self._stop_event.wait(self.poll_interval)
        logger.info("Worker stopped")

    def stop(self) -> None:
        self._stop_event.set()

    def is_alive(self) -> bool:
        return super().is_alive()

    def process_one_job(self) -> bool:
        """Process one queued job. Returns True if a job was found, False otherwise."""
        job = self.db.fetch_next_queued_job()
        if job is None:
            return False

        job_id = job["id"]
        jl = JobLogger(db=self.db, job_id=job_id, results_dir=self.results_dir)

        result_path = self.results_dir / job_id / "output.csv"
        result_path.parent.mkdir(parents=True, exist_ok=True)

        user_id, password = decrypt_credentials(
            self.encryption_key, job["abs_credentials_encrypted"]
        )
        config = Config(user_id=user_id, password=password)
        request = TableRequest(**json.loads(job["request_json"]))
        job_timeout = job["timeout_seconds"] or 600

        page = None
        session = None
        try:
            jl.log_progress("Logging in...")
            session = TableBuilderSession(config, headless=True, knowledge=self.knowledge)
            page = session.__enter__()
            jl.capture_screenshot(page, "after_login")

            jl.log_progress("Opening dataset...")
            open_dataset(page, request.dataset, knowledge=self.knowledge)
            jl.capture_screenshot(page, "dataset_opened")

            jl.log_progress("Building table...")
            build_table(page, request, knowledge=self.knowledge)
            jl.capture_screenshot(page, "table_built")

            jl.log_progress("Queuing download...")
            queue_and_download(
                page, str(result_path), timeout=job_timeout, knowledge=self.knowledge
            )
            jl.capture_screenshot(page, "download_complete")
            jl.log_progress("Download complete")

            session.__exit__(None, None, None)
            session = None
            self.db.mark_completed(job_id, str(result_path))
            self.knowledge.save()

        except SessionExpiredError:
            jl.log_warning("Session expired, attempting relogin...")
            if session:
                try:
                    session.relogin()
                    jl.log_progress("Relogin successful, but job needs manual retry")
                except Exception:
                    pass
                session.__exit__(None, None, None)
                session = None
            self.db.mark_failed(
                job_id, error_message="Session expired during job execution"
            )

        except Exception as e:
            tb = traceback.format_exc()
            screenshot_path = ""
            page_html_path = ""
            page_url = ""
            if page:
                screenshot_path = jl.capture_screenshot(page, "failure")
                page_html_path = jl.save_page_state(page)
                page_url = page.url
            jl.log_error(str(e), detail=tb)
            if session:
                session.__exit__(*sys.exc_info())
                session = None
            self.db.mark_failed(
                job_id,
                error_message=str(e),
                error_detail=tb,
                page_url=page_url,
                page_html_path=page_html_path,
                screenshot_path=screenshot_path,
            )
            self.knowledge.save()

        return True
