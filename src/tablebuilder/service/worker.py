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
            from tablebuilder.http_catalogue import find_database, open_database, get_schema, find_variable
            from tablebuilder.http_table import (
                select_all_categories, add_to_axis, retrieve_data,
                select_csv_format, download_table,
            )

            jl.log_progress("Logging in...")
            session = TableBuilderHTTPSession(config, knowledge=self.knowledge)
            session.login()

            jl.log_progress("Finding dataset...")
            tree = session.rest_get("/rest/catalogue/databases/tree")
            result = find_database(tree, request.dataset)
            if not result:
                raise RuntimeError(f"Database not found: {request.dataset}")
            path, db_node = result
            db_name = db_node["data"]["name"]

            jl.log_progress(f"Opening {db_name}...")
            open_database(session, path)

            jl.log_progress("Loading variables...")
            schema = get_schema(session)

            for var_name, axis in request.variable_axes().items():
                jl.log_progress(f"Adding {var_name} to {axis.value}...")
                var_info = find_variable(schema, var_name)
                if not var_info:
                    raise RuntimeError(f"Variable not found: {var_name}")
                select_all_categories(session, schema, var_info)
                add_to_axis(session, axis.value)

            jl.log_progress("Retrieving data...")
            retrieve_data(session)
            select_csv_format(session)

            jl.log_progress("Downloading CSV...")
            try:
                download_table(session, str(result_path))
            except RuntimeError:
                # HTTP download failed — table needs Playwright.
                # Use the original CLI pipeline which does everything in browser.
                jl.log_progress("Using browser for download...")
                session._session.close()
                from tablebuilder.http_table import _playwright_full_fetch
                _playwright_full_fetch(config, request, str(result_path), jl)

            session._session.close()
            jl.log_progress("Complete!")
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
