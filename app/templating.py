from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.notifications.messages import STATUS_LABELS_RU

templates = Jinja2Templates(directory=Path(__file__).resolve().parent / "templates")
templates.env.globals["status_labels"] = STATUS_LABELS_RU


def blank_to_none(value: str | None) -> str | None:
    return value.strip() if value and value.strip() else None
