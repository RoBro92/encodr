import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.executor import LocalWorkerLoop
from encodr_core.config import load_config_bundle

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger("encodr.worker")


def main() -> None:
    config_bundle = load_config_bundle()
    engine = create_engine(config_bundle.app.database.dsn, future=True)
    session_factory = sessionmaker(engine, future=True)

    logger.info("worker loop started")
    loop = LocalWorkerLoop(session_factory, config_bundle)
    loop.run_forever()


if __name__ == "__main__":
    main()
