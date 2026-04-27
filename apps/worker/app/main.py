import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.executor import LocalWorkerLoop
from encodr_core.config import load_config_bundle
from encodr_shared import configure_component_logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger("encodr.worker")


def main() -> None:
    config_bundle = load_config_bundle()
    configure_component_logging(
        component="worker",
        log_dir=config_bundle.app.data_dir / "logs",
        level=config_bundle.app.log_level.value,
        retention_days=config_bundle.app.diagnostics.retention_days,
    )
    engine = create_engine(config_bundle.app.database.dsn, future=True)
    session_factory = sessionmaker(engine, future=True)

    logger.info("worker loop started")
    loop = LocalWorkerLoop(session_factory, config_bundle)
    loop.run_forever()


if __name__ == "__main__":
    main()
