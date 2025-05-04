# Файл models.py добавлен — он описывает структуру PendingSync через Pydantic.
# Содержимое models.py

from pydantic import BaseModel
from typing import Any

class PendingSync(BaseModel):
    order_id: int
    order_payload: dict[str, Any]
    retry_count: int = 0
    last_attempt: str | None = None
    error_message: str | None = None
    created_at: str | None = None