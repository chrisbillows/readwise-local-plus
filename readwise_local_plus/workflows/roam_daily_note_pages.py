"""Utilities for ensuring Roam daily note pages exist."""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

from sqlalchemy.orm import Session

from readwise_local_plus.config import fetch_user_config
from readwise_local_plus.db_operations import get_session
from readwise_local_plus.integrations.roam import RoamAPIError, RoamClient
from readwise_local_plus.models import RoamKnownPage

logger = logging.getLogger(__name__)


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _format_daily_note_title(target_date: date) -> str:
    return f"{target_date:%B} {_ordinal(target_date.day)}, {target_date:%Y}"


def create_daily_note_page(
    target_date: Optional[date] = None,
    *,
    session: Session | None = None,
    roam_client: RoamClient | None = None,
) -> str:
    """Ensure the Roam daily note page for ``target_date`` exists."""
    owns_session = False
    if session is None:
        config = fetch_user_config()
        session = get_session(config.db_path)
        owns_session = True

    client = roam_client or RoamClient()
    try:
        target = target_date or date.today()
        page_uid = client.date_to_roam_daily_note(target)

        if session.get(RoamKnownPage, page_uid):
            return page_uid

        payload = {
            "action": "batch-actions",
            "actions": [
                {
                    "action": "create-block",
                    "location": {"parent-uid": "Daily Notes", "order": 0},
                    "block": {
                        "string": _format_daily_note_title(target),
                        "uid": page_uid,
                    },
                }
            ],
        }

        try:
            client._write(payload)
        except RoamAPIError as exc:  # pragma: no cover - exercised in tests via mock
            message = str(exc).lower()
            if "already" not in message and "duplicate" not in message:
                raise
            logger.debug("Daily note page %s already exists: %s", page_uid, exc)

        now = datetime.now()
        known_page = session.get(RoamKnownPage, page_uid)
        if known_page is None:
            session.add(RoamKnownPage(page_uid=page_uid, last_verified_at=now))
        else:
            known_page.last_verified_at = now
        session.flush()
        return page_uid
    finally:
        if owns_session:
            session.close()


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    import argparse

    parser = argparse.ArgumentParser(description="Ensure a Roam daily note page exists")
    parser.add_argument(
        "--date",
        type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
        help="Target date in YYYY-MM-DD format (defaults to today)",
    )
    args = parser.parse_args()
    create_daily_note_page(args.date)
