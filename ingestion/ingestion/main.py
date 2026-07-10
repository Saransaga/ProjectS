import logging

from .scheduler import build_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def main():
    scheduler = build_scheduler()
    logger.info("starting scheduler")
    scheduler.start()


if __name__ == "__main__":
    main()
