from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.notifications.dispatcher import NotificationDispatcher
from app.security import worker_id

SessionDep = Annotated[AsyncSession, Depends(get_session)]
WorkerDep = Annotated[str, Depends(worker_id)]


def get_dispatcher(request: Request) -> NotificationDispatcher:
    return request.app.state.dispatcher


DispatcherDep = Annotated[NotificationDispatcher, Depends(get_dispatcher)]
