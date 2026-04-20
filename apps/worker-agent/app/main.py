import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger("encodr.worker_agent")


def main() -> None:
    logger.info("worker-agent placeholder started")
    logger.info("remote worker registration is not implemented yet")


if __name__ == "__main__":
    main()

