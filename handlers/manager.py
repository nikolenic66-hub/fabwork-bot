from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)


def manager_chat_ids() -> list[int]:
    """Return configured manager chat IDs without duplicates."""
    ids: list[int] = []
    for key in ("MANAGER_CHAT_ID", "MANAGER_CHAT_ID_2"):
        raw = os.getenv(key, "").strip()
        if not raw:
            continue
        try:
            value = int(raw)
        except ValueError:
            log.error("Invalid %s", key)
            continue
        if value and value not in ids:
            ids.append(value)
    return ids
