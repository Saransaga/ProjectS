"""Always-on entrypoint (its own docker-compose service, see
docker-compose.yml's telegram-listener) — long-polls Telegram's getUpdates
and dispatches every inbound message via commands.handle_update. Kept as a
separate process from the daily scheduler.py/Airflow batch jobs since
long-polling is a permanent blocking loop, not a cron tick; TelegramAlertsJob
(Domain 8's other Telegram piece) is the batch side that pushes proactive
alerts — this is the reactive side that answers incoming chat messages.

A ReadTimeout/ConnectionError from get_updates during an idle long-poll
window is expected steady-state behavior (see telegram_client.py's module
docstring), not a failure — caught here and the loop just re-polls.
"""

import logging
import time

import requests

from .. import telegram_client
from ..config import config
from ..db import get_conn
from .commands import handle_update

logger = logging.getLogger(__name__)

_POLL_TIMEOUT_SECONDS = 30
_ERROR_BACKOFF_SECONDS = 5


def run() -> None:
    if not config.TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is not set — telegram_listener has nothing to do, exiting")
        return

    logger.info("telegram_listener starting: %s", telegram_client.get_me())
    offset = None
    while True:
        try:
            updates = telegram_client.get_updates(offset=offset, timeout=_POLL_TIMEOUT_SECONDS)
        except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError):
            continue  # expected on an idle long-poll window, see module docstring
        except telegram_client.TelegramApiError:
            logger.exception("get_updates failed")
            time.sleep(_ERROR_BACKOFF_SECONDS)
            continue

        for update in updates:
            offset = update["update_id"] + 1
            try:
                with get_conn() as conn:
                    handle_update(conn, update)
            except Exception:
                logger.exception("handle_update failed for update_id=%s", update.get("update_id"))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    run()
