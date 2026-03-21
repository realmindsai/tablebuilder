# ABOUTME: Background worker thread that processes TableBuilder fetch jobs.
# ABOUTME: Calls the existing pipeline (login -> open dataset -> build table -> download).

import json
import sys
import threading
import traceback
import time
from pathlib import Path

from tablebuilder.config import Config
from tablebuilder.http_session import TableBuilderHTTPSession
from tablebuilder.http_table import http_fetch_table
from tablebuilder.knowledge import KnowledgeBase
from tablebuilder.logging_config import get_logger
from tablebuilder.models import TableRequest
from tablebuilder.service.auth import decrypt_credentials
from tablebuilder.service.db import ServiceDB
from tablebuilder.service.job_logger import JobLogger

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

        try:
            jl.log_progress("Logging in via HTTP...")
            with TableBuilderHTTPSession(config, knowledge=self.knowledge) as session:
                jl.log_progress("Finding dataset and building table...")
                http_fetch_table(session, request, str(result_path))

            jl.log_progress("Download complete")
            self.db.mark_completed(job_id, str(result_path))
            self.knowledge.save()

        except Exception as e:
            tb = traceback.format_exc()
            jl.log_error(str(e), detail=tb)
            self.db.mark_failed(
                job_id,
                error_message=str(e),
                error_detail=tb,
            )
            self.knowledge.save()

        return True
