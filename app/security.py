import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Security, status
from fastapi.security import APIKeyHeader

from app.config import Settings, get_settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False, description="Warehouse / admin API key")


def is_valid_api_key(key: str | None, settings: Settings) -> bool:
    if not key:
        return False
    # Check every key so timing doesn't reveal which one matched.
    return any([secrets.compare_digest(key.encode(), valid.encode()) for valid in settings.api_key_list])


async def require_api_key(
    key: Annotated[str | None, Security(api_key_header)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> str:
    if not is_valid_api_key(key, settings):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key. Send it in the 'X-API-Key' header.",
            headers={"WWW-Authenticate": "APIKey"},
        )
    return key  # type: ignore[return-value]


def worker_id(x_worker_id: Annotated[str | None, Header(max_length=100)] = None) -> str:
    """Who performed the action, recorded in status_history.changed_by."""
    return (x_worker_id or "").strip() or "warehouse"
