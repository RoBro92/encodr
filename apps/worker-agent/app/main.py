from __future__ import annotations

import logging
import sys
import time

from app.client import WorkerApiClient
from app.config import load_settings
from app.service import WorkerAgentService

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger("encodr.worker_agent")


def main(argv: list[str] | None = None) -> None:
    args = argv or sys.argv[1:]
    command = args[0] if args else "heartbeat"

    try:
        settings = load_settings()
    except ValueError as error:
        raise SystemExit(str(error)) from error

    service = WorkerAgentService(
        settings=settings,
        api_client=WorkerApiClient(base_url=settings.api_base_url),
    )

    if command == "register":
        session = service.register()
        logger.info("registered remote worker %s", session.worker_key)
        return

    if command == "heartbeat":
        response = service.heartbeat()
        logger.info(
            "heartbeat acknowledged for %s (%s)",
            response["worker_key"],
            response["health_status"],
        )
        return

    if command == "run-once":
        response = service.process_once()
        if response is None:
            logger.info("no remote job available")
        else:
            logger.info(
                "completed remote job %s with status %s",
                response["job_id"],
                response["final_status"],
            )
        return

    if command == "loop":
        iterations = int(args[1]) if len(args) > 1 else 1
        for _ in range(iterations):
            response = service.process_once()
            if response is None:
                logger.info("no remote job available")
            else:
                logger.info(
                    "completed remote job %s with status %s",
                    response["job_id"],
                    response["final_status"],
                )
            time.sleep(settings.heartbeat_interval_seconds)
        return

    raise SystemExit(f"Unsupported command '{command}'. Use register, heartbeat, run-once, or loop.")


if __name__ == "__main__":
    main()
