"""Tests for roam_daily_note_pages utilities."""

from datetime import date
from unittest.mock import Mock, patch

import pytest

from readwise_local_plus.integrations.roam import RoamAPIError
from readwise_local_plus.models import RoamKnownPage
from readwise_local_plus.workflows.roam_daily_note_pages import create_daily_note_page


@pytest.mark.usefixtures("mem_db")
def test_create_daily_note_page_creates_when_missing(mem_db):
    session = mem_db.session

    with patch(
        "readwise_local_plus.workflows.roam_daily_note_pages.RoamClient"
    ) as mock_client_cls:
        mock_client = Mock()
        mock_client.date_to_roam_daily_note.return_value = "01-15-2023"
        mock_client._write.return_value = {"tempids-to-uids": {}}
        mock_client_cls.return_value = mock_client

        page_uid = create_daily_note_page(date(2023, 1, 15), session=session)

    assert page_uid == "01-15-2023"
    assert session.get(RoamKnownPage, "01-15-2023") is not None
    mock_client._write.assert_called_once()


@pytest.mark.usefixtures("mem_db")
def test_create_daily_note_page_skips_when_known(mem_db):
    session = mem_db.session
    session.add(RoamKnownPage(page_uid="01-15-2023"))
    session.commit()

    with patch(
        "readwise_local_plus.workflows.roam_daily_note_pages.RoamClient"
    ) as mock_client_cls:
        mock_client = Mock()
        mock_client.date_to_roam_daily_note.return_value = "01-15-2023"
        mock_client_cls.return_value = mock_client

        page_uid = create_daily_note_page(date(2023, 1, 15), session=session)

    assert page_uid == "01-15-2023"
    mock_client._write.assert_not_called()


@pytest.mark.usefixtures("mem_db")
def test_create_daily_note_page_handles_existing_page(mem_db):
    session = mem_db.session

    with patch(
        "readwise_local_plus.workflows.roam_daily_note_pages.RoamClient"
    ) as mock_client_cls:
        mock_client = Mock()
        mock_client.date_to_roam_daily_note.return_value = "01-15-2023"
        mock_client._write.side_effect = RoamAPIError("UID already exists")
        mock_client_cls.return_value = mock_client

        with patch(
            "readwise_local_plus.workflows.roam_daily_note_pages.logger"
        ) as mock_logger:
            page_uid = create_daily_note_page(date(2023, 1, 15), session=session)

    assert page_uid == "01-15-2023"
    mock_logger.debug.assert_called()
    known_page = session.get(RoamKnownPage, "01-15-2023")
    assert known_page is not None
