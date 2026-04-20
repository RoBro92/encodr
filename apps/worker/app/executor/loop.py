from __future__ import annotations

import logging
import time
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from encodr_core.config import ConfigBundle
from encodr_core.media.models import MediaFile
from encodr_core.planning import ProcessingPlan
from encodr_db.repositories import JobRepository

from app.executor.service import WorkerExecutionService

logger = logging.getLogger("encodr.worker.loop")


class LocalWorkerLoop:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        config_bundle: ConfigBundle,
        *,
        worker_name: str = "worker-local",
        poll_interval_seconds: float = 2.0,
        execution_service: WorkerExecutionService | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.config_bundle = config_bundle
        self.worker_name = worker_name
        self.poll_interval_seconds = poll_interval_seconds
        self.execution_service = execution_service or WorkerExecutionService()

    def run_forever(self) -> None:
        while True:
            processed = self.run_once()
            if not processed:
                time.sleep(self.poll_interval_seconds)

    def run_once(self) -> bool:
        with self.session_factory() as session:
            jobs = JobRepository(session)
            job = jobs.fetch_next_pending_job()
            if job is None:
                return False

            jobs.mark_running(job, worker_name=self.worker_name)
            plan = ProcessingPlan.model_validate(job.plan_snapshot.payload)
            media_file = MediaFile.model_validate(job.plan_snapshot.probe_snapshot.payload)

            logger.info("processing job %s for %s", job.id, media_file.file_name)
            self.execution_service.execute_job(
                session,
                job_id=job.id,
                plan=plan,
                media_file=media_file,
                ffmpeg_path=self.config_bundle.app.media.ffmpeg_path,
                scratch_dir=self.config_bundle.app.scratch_dir,
            )
            session.commit()
            return True
