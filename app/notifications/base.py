from typing import Protocol

from app.services.parcels import StatusChangeEvent


class Notifier(Protocol):
    name: str

    async def notify(self, event: StatusChangeEvent) -> None:
        """Deliver the event; raise on failure so the dispatcher can log it."""
        ...
