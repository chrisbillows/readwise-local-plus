"""Utilities for ensuring Roam daily note pages exist."""

from __future__ import annotations

import logging
from datetime import date, datetime

from sqlalchemy.orm import Session

from readwise_local_plus.integrations.roam import RoamClient
from readwise_local_plus.models import RoamKnownPage

logger = logging.getLogger(__name__)


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _format_daily_note_title_long_format(target_date: date) -> str:
    return f"{target_date:%B} {_ordinal(target_date.day)}, {target_date:%Y}"


def create_daily_note_page(
    target_date: date,
    session: Session,
    roam_client: RoamClient,
) -> str:
    """
    Ensure the Roam daily note page for ``target_date`` exists.

    Parameters
    ----------
    target_date : date
        The date for which to ensure the daily note page exists.
    session : Session
        SQLAlchemy session for database operations.
    roam_client : RoamClient
        An instance of RoamClient to interact with the Roam API.

    Returns
    -------
    bool
        True if the daily note page was created, False if it already existed.
    """
    target = target_date
    page_uid = roam_client.date_to_roam_daily_note(target)

    if session.get(RoamKnownPage, page_uid):
        return False

    title = _format_daily_note_title_long_format(target)

    roam_client.create_page(title)

    now = datetime.now()
    known_page = session.get(RoamKnownPage, page_uid)
    if known_page is None:
        session.add(RoamKnownPage(page_uid=page_uid, last_verified_at=now))
    else:
        known_page.last_verified_at = now
    session.flush()
    return page_uid


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
