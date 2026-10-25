import asyncio
import logging
from collections.abc import Sequence

from app.notifications.base import Notifier
from app.services.parcels import StatusChangeEvent

logger = logging.getLogger(__name__)


class NotificationDispatcher:
    """Fans a status change out to every configured channel. One channel failing never blocks the others.

    Runs as a FastAPI background task after the DB commit, so a crash between commit and send loses the
    notification (acceptable for the MVP; see README for the outbox upgrade path).
    """

    def __init__(self, notifiers: Sequence[Notifier]) -> None:
        self.notifiers = list(notifiers)

    async def dispatch(self, event: StatusChangeEvent) -> None:
        if not self.notifiers:
            logger.info("No notification channels configured; skipping %s", event.tracking_code)
            return
        results = await asyncio.gather(*(n.notify(event) for n in self.notifiers), return_exceptions=True)
        for notifier, result in zip(self.notifiers, results):
            if isinstance(result, BaseException):
                logger.error(
                    "%s notification failed for %s (%s): %s",
                    notifier.name, event.tracking_code, event.new_status.value, result,
                )
            else:
                logger.info("%s notified for %s → %s", notifier.name, event.tracking_code, event.new_status.value)
