"""Unit tests for roam_daily_note.py workflow module."""

import hashlib
import json
from collections import defaultdict
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

from readwise_local_plus.models import (
    Book,
    Highlight,
    RoamBookExport,
    RoamHighlightExport,
    RoamPage,
)
from readwise_local_plus.workflows.roam_daily_note import RoamDailyNoteHighlightWriter


class TestRoamDailyNoteHighlightWriter:
    """Test the RoamDailyNoteHighlightWriter class."""

    @patch("readwise_local_plus.workflows.roam_daily_note.RoamClient")
    def test_init(self, mock_roam_client):
        """Test initialization of RoamDailyNoteHighlightWriter."""
        writer = RoamDailyNoteHighlightWriter(123)

        assert writer.highlights_header == "[[Readwise highlights]]"
        assert isinstance(writer.highlights, defaultdict)
        assert len(writer.highlights) == 0
        mock_roam_client.assert_called_once()

    def test_stable_hash(self):
        """Test stable_hash static method."""
        # Test with simple dict
        obj1 = {"key": "value", "number": 42}
        obj2 = {"number": 42, "key": "value"}  # Different order

        hash1 = RoamDailyNoteHighlightWriter.stable_hash(obj1)
        hash2 = RoamDailyNoteHighlightWriter.stable_hash(obj2)

        # Should be identical despite different order
        assert hash1 == hash2

        # Should be valid SHA256 hex string
        assert len(hash1) == 64
        assert all(c in "0123456789abcdef" for c in hash1)

        # Test with different objects
        obj3 = {"key": "different", "number": 42}
        hash3 = RoamDailyNoteHighlightWriter.stable_hash(obj3)
        assert hash1 != hash3

    def test_stable_hash_reproducible(self):
        """Test that stable_hash produces consistent results."""
        obj = {"nested": {"list": [1, 2, 3]}, "string": "test"}

        hash1 = RoamDailyNoteHighlightWriter.stable_hash(obj)
        hash2 = RoamDailyNoteHighlightWriter.stable_hash(obj)

        assert hash1 == hash2

    def test_stable_hash_complex_object(self):
        """Test stable_hash with complex nested objects."""
        complex_obj = {
            "block_tree": {
                "uid": "test-uid",
                "text": "test text",
                "children": [
                    {"uid": "child1", "text": "child1 text"},
                    {"uid": "child2", "text": "child2 text"},
                ],
            },
            "metadata": {"version": 1, "created_at": "2023-01-01T00:00:00Z"},
        }

        hash_result = RoamDailyNoteHighlightWriter.stable_hash(complex_obj)

        # Verify it's a valid SHA256
        assert len(hash_result) == 64
        assert isinstance(hash_result, str)

        # Verify reproducibility
        expected_hash = hashlib.sha256(
            json.dumps(complex_obj, sort_keys=True).encode("utf-8")
        ).hexdigest()
        assert hash_result == expected_hash

    @patch("readwise_local_plus.workflows.roam_daily_note.get_session")
    @patch("readwise_local_plus.workflows.roam_daily_note.RoamClient")
    def test_write_batch_to_daily_notes(self, mock_roam_client, mock_get_session):
        """Test write_batch_to_daily_notes method."""
        # Setup mocks
        mock_session = Mock()
        mock_get_session.return_value = mock_session

        writer = RoamDailyNoteHighlightWriter(123)
        writer.fetch_highlights = Mock()
        writer._write_highlights = Mock()

        # Call method
        writer.write_batch_to_daily_notes()

        # Verify calls
        writer.fetch_highlights.assert_called_once()
        writer._write_highlights.assert_called_once()
        mock_session.close.assert_called_once()

    @patch("readwise_local_plus.workflows.roam_daily_note.select")
    @patch("readwise_local_plus.workflows.roam_daily_note.selectinload")
    @patch("readwise_local_plus.workflows.roam_daily_note.RoamClient")
    def test_fetch_highlights(self, mock_roam_client, mock_selectinload, mock_select):
        """Test fetch_highlights method."""
        # Setup mocks
        mock_session = Mock()

        # Create mock highlights with books
        mock_book1 = Mock(spec=Book)
        mock_book1.user_book_id = 1
        mock_book1.title = "Test Book 1"
        mock_book1.category = "articles"

        mock_book2 = Mock(spec=Book)
        mock_book2.user_book_id = 2
        mock_book2.title = "Test Book 2"
        mock_book2.category = "tweets"

        mock_highlight1 = Mock(spec=Highlight)
        mock_highlight1.id = 1
        mock_highlight1.book_id = 1
        mock_highlight1.book = mock_book1
        mock_highlight1.location = 100
        mock_highlight1.created_at = datetime(2023, 1, 15, 10, 0, 0)
        mock_highlight1.text = "Test highlight 1"

        mock_highlight2 = Mock(spec=Highlight)
        mock_highlight2.id = 2
        mock_highlight2.book_id = 1
        mock_highlight2.book = mock_book1
        mock_highlight2.location = 200
        mock_highlight2.created_at = datetime(2023, 1, 15, 11, 0, 0)
        mock_highlight2.text = "Test highlight 2"

        mock_highlight3 = Mock(spec=Highlight)
        mock_highlight3.id = 3
        mock_highlight3.book_id = 2
        mock_highlight3.book = mock_book2
        mock_highlight3.location = None  # Tweet without location
        mock_highlight3.created_at = datetime(2023, 1, 16, 12, 0, 0)
        mock_highlight3.text = "Test tweet"

        highlights = [mock_highlight1, mock_highlight2, mock_highlight3]

        # Setup SQLAlchemy mock chain
        mock_stmt = Mock()
        mock_select.return_value = mock_stmt
        mock_stmt.join.return_value = mock_stmt
        mock_stmt.where.return_value = mock_stmt
        mock_stmt.options.return_value = mock_stmt
        mock_stmt.order_by.return_value = mock_stmt

        mock_result = Mock()
        mock_result.scalars.return_value.all.return_value = highlights
        mock_session.execute.return_value = mock_result

        writer = RoamDailyNoteHighlightWriter(123)
        writer._session = mock_session  # Set session directly for unit test
        writer.fetch_highlights()

        # Verify the highlights were grouped correctly
        assert len(writer.highlights) == 2  # Two different dates

        # Check first date (from highlight2 - latest from book1)
        first_date = date(2023, 1, 15)
        assert first_date in writer.highlights
        assert mock_book1 in writer.highlights[first_date]
        book1_highlights = writer.highlights[first_date][mock_book1]
        assert len(book1_highlights) == 2
        # Should be sorted by location
        assert book1_highlights[0].location == 100
        assert book1_highlights[1].location == 200

        # Check second date (from highlight3)
        second_date = date(2023, 1, 16)
        assert second_date in writer.highlights
        assert mock_book2 in writer.highlights[second_date]
        book2_highlights = writer.highlights[second_date][mock_book2]
        assert len(book2_highlights) == 1
        assert book2_highlights[0].text == "Test tweet"

    @patch("readwise_local_plus.workflows.roam_daily_note.select")
    @patch("readwise_local_plus.workflows.roam_daily_note.RoamClient")
    def test_fetch_highlights_empty_result(self, mock_roam_client, mock_select):
        """Test fetch_highlights with no highlights returned."""
        mock_session = Mock()

        # Setup empty result
        mock_stmt = Mock()
        mock_select.return_value = mock_stmt
        mock_stmt.join.return_value = mock_stmt
        mock_stmt.where.return_value = mock_stmt
        mock_stmt.options.return_value = mock_stmt
        mock_stmt.order_by.return_value = mock_stmt

        mock_result = Mock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        writer = RoamDailyNoteHighlightWriter(123)
        writer._session = mock_session  # Set session directly for unit test
        writer.fetch_highlights()

        # Should have no highlights
        assert len(writer.highlights) == 0

    @patch("readwise_local_plus.workflows.roam_daily_note.RoamBatchAction")
    @patch("readwise_local_plus.workflows.roam_daily_note.RoamExportBatch")
    @patch("readwise_local_plus.workflows.roam_daily_note.datetime")
    @patch("readwise_local_plus.workflows.roam_daily_note.RoamClient")
    def test_write_highlights_empty(
        self,
        mock_roam_client,
        mock_datetime,
        mock_export_batch_class,
        mock_batch_action_class,
    ):
        """Test _write_highlights with no highlights."""
        writer = RoamDailyNoteHighlightWriter("Test Header")
        writer._session = Mock()

        # Call with empty highlights
        writer._write_highlights()

        # Should return early without creating export batch
        mock_export_batch_class.assert_not_called()
        writer._session.add.assert_not_called()

    @patch("readwise_local_plus.workflows.roam_daily_note.RoamBatchAction")
    @patch("readwise_local_plus.workflows.roam_daily_note.RoamExportBatch")
    @patch("readwise_local_plus.workflows.roam_daily_note.datetime")
    @patch("readwise_local_plus.workflows.roam_daily_note.RoamClient")
    def test_write_highlights_with_data(
        self,
        mock_roam_client,
        mock_datetime,
        mock_export_batch_class,
        mock_batch_action_class,
    ):
        """Test _write_highlights with actual highlight data."""
        # Setup datetime mock
        fixed_datetime = datetime(2023, 1, 15, 10, 0, 0)
        mock_datetime.now.return_value = fixed_datetime

        # Setup writer with test data
        writer = RoamDailyNoteHighlightWriter(123)
        writer._session = Mock()

        # Create mock roam client
        mock_client = Mock()
        mock_client.date_to_roam_daily_note.return_value = "01-15-2023"
        mock_client.fetch_block_subtree.return_value = {
            "uid": "real-header-uid",
            "children": [],
        }
        writer.roam_client = mock_client

        # Create test book and highlights
        class DummyBook:
            pass

        mock_book = DummyBook()
        mock_book.user_book_id = 1
        mock_book.title = "Test Book"
        mock_book.category = "articles"
        mock_book.author = "Author Example"

        mock_highlight = SimpleNamespace(
            id=1,
            text="Test highlight text",
            location=None,
        )

        test_date = date(2023, 1, 15)
        writer.highlights = {test_date: {mock_book: [mock_highlight]}}

        # Setup mocks for database queries
        writer._session.get.return_value = None  # No existing page

        # Mock snapshot query chain
        mock_snapshot_query = Mock()
        mock_snapshot_query.filter_by.return_value.order_by.return_value.first.return_value = None

        # Mock other query chains
        mock_other_query = Mock()
        mock_other_query.filter_by.return_value.first.return_value = None

        def mock_query_side_effect(model):
            # Use string representation to avoid __name__ issues with mocks
            model_str = str(model)
            if "RoamHighlightSnapshot" in model_str:
                return mock_snapshot_query
            else:
                return mock_other_query

        writer._session.query.side_effect = mock_query_side_effect

        # Setup batch action mock
        mock_batch_action = Mock()
        mock_batch_action.append_a_child_block_action.side_effect = [
            -1,
            -2,
            -3,
        ]  # temp UIDs
        mock_batch_action.execute_batch_action.return_value = {
            "-1": "real-header-uid",
            "-2": "real-book-uid",
            "-3": "real-highlight-uid",
        }
        mock_batch_action.batch_action_body = {"actions": ["mock_action"]}
        mock_batch_action_class.return_value = mock_batch_action

        # Setup export batch mock
        mock_export_batch = Mock()
        mock_export_batch_class.return_value = mock_export_batch

        # Mock model creation to avoid SQLAlchemy issues
        with (
            patch("readwise_local_plus.workflows.roam_daily_note.RoamPage"),
            patch("readwise_local_plus.workflows.roam_daily_note.RoamBookExport"),
            patch("readwise_local_plus.workflows.roam_daily_note.RoamHighlightExport"),
            patch(
                "readwise_local_plus.workflows.roam_daily_note.RoamHighlightSnapshot"
            ),
            patch("readwise_local_plus.workflows.roam_daily_note.RoamPageSnapshot"),
        ):
            # Call the method
            writer._write_highlights()

        # Verify export batch was created and added
        mock_export_batch_class.assert_called_once_with(
            database_write_time=fixed_datetime
        )
        writer._session.add.assert_any_call(mock_export_batch)

        # Verify roam client was called
        mock_client.date_to_roam_daily_note.assert_called_once_with(test_date)

        # Verify batch actions were created
        assert mock_batch_action.append_a_child_block_action.call_count == 3

        # Verify header creation call
        header_call = mock_batch_action.append_a_child_block_action.call_args_list[0]
        assert header_call[0] == ("01-15-2023", "[[Readwise highlights]]")
        assert header_call[1] == {"heading": 1, "open": True}

        # Verify book creation call
        book_call = mock_batch_action.append_a_child_block_action.call_args_list[1]
        assert book_call[0] == (-1, "Test Book")
        assert book_call[1] == {"heading": 3}

        # Verify highlight creation call
        highlight_call = mock_batch_action.append_a_child_block_action.call_args_list[2]
        assert highlight_call[0] == (-2, "Test highlight text")

        # Verify batch execution
        mock_batch_action.execute_batch_action.assert_called_once()

        # Verify session commit
        writer._session.commit.assert_called_once()

    @patch("readwise_local_plus.workflows.roam_daily_note.RoamClient")
    def test_write_highlights_with_existing_page(self, mock_roam_client):
        """Test _write_highlights when page already exists."""
        writer = RoamDailyNoteHighlightWriter("Test Header")
        writer._session = Mock()

        # Create test data
        class DummyBook:
            pass

        mock_book = DummyBook()
        mock_book.user_book_id = 1
        mock_book.title = "Test Book"
        mock_book.category = "articles"
        mock_book.author = "Author Example"

        mock_highlight = SimpleNamespace(
            id=1,
            text="Test highlight",
            location=None,
        )

        test_date = date(2023, 1, 15)
        writer.highlights = {test_date: {mock_book: [mock_highlight]}}

        # Setup existing page
        mock_existing_page = Mock(spec=RoamPage)
        mock_existing_page.highlights_header_uid = "existing-header-uid"
        mock_existing_page.snapshots = []  # Empty snapshots list

        # Mock snapshot query for existing page scenario
        mock_snapshot_query = Mock()
        mock_snapshot_query.filter_by.return_value.order_by.return_value.first.return_value = None

        writer._session.get.return_value = mock_existing_page

        def mock_query_side_effect(model):
            # Use string representation to avoid __name__ issues with mocks
            model_str = str(model)
            if "RoamHighlightSnapshot" in model_str:
                return mock_snapshot_query
            else:
                query = Mock()
                query.filter_by.return_value.first.return_value = None
                return query

        writer._session.query.side_effect = mock_query_side_effect

        with (
            patch(
                "readwise_local_plus.workflows.roam_daily_note.RoamBatchAction"
            ) as mock_batch_action_class,
            patch("readwise_local_plus.workflows.roam_daily_note.RoamExportBatch"),
            patch(
                "readwise_local_plus.workflows.roam_daily_note.datetime"
            ) as mock_datetime,
        ):
            mock_datetime.now.return_value = datetime(2023, 1, 15, 10, 0, 0)
            mock_batch_action = Mock()
            mock_batch_action.append_a_child_block_action.side_effect = [-1, -2]
            mock_batch_action.execute_batch_action.return_value = {
                "-1": "real-book-uid",
                "-2": "real-highlight-uid",
            }
            mock_batch_action.batch_action_body = {"actions": ["mock_action"]}
            mock_batch_action_class.return_value = mock_batch_action

            mock_client = Mock()
            mock_client.date_to_roam_daily_note.return_value = "01-15-2023"
            mock_client.fetch_block_subtree.return_value = {
                "uid": "header-uid",
                "children": [],
            }
            writer.roam_client = mock_client

            with (
                patch("readwise_local_plus.workflows.roam_daily_note.RoamBookExport"),
                patch(
                    "readwise_local_plus.workflows.roam_daily_note.RoamHighlightExport"
                ),
                patch(
                    "readwise_local_plus.workflows.roam_daily_note.RoamHighlightSnapshot"
                ),
                patch("readwise_local_plus.workflows.roam_daily_note.RoamPageSnapshot"),
            ):
                writer._write_highlights()

                # Should use existing header UID instead of creating new one
                book_call = (
                    mock_batch_action.append_a_child_block_action.call_args_list[0]
                )
                assert book_call[0] == ("existing-header-uid", "Test Book")

    @patch("readwise_local_plus.workflows.roam_daily_note.RoamClient")
    def test_write_highlights_with_existing_book_export(self, mock_roam_client):
        """Test _write_highlights when book export already exists."""
        writer = RoamDailyNoteHighlightWriter("Test Header")
        writer._session = Mock()

        # Create test data
        mock_book = Mock(spec=Book)
        mock_book.user_book_id = 1
        mock_book.title = "Test Book"

        mock_highlight = Mock(spec=Highlight)
        mock_highlight.id = 1
        mock_highlight.text = "Test highlight"

        test_date = date(2023, 1, 15)
        writer.highlights = {test_date: {mock_book: [mock_highlight]}}

        # Setup existing book export
        mock_existing_book_export = Mock(spec=RoamBookExport)
        mock_existing_book_export.parent_block_uid = "existing-book-uid"

        # Mock query chain for book export
        mock_book_query = Mock()
        mock_book_query.filter_by.return_value.first.return_value = (
            mock_existing_book_export
        )

        # Mock query chain for highlight export (should return None)
        mock_highlight_query = Mock()
        mock_highlight_query.filter_by.return_value.first.return_value = None

        # Setup session.query to return different mocks based on the model
        def mock_query_side_effect(model):
            model_str = str(model)
            if "RoamBookExport" in model_str:
                return mock_book_query
            elif "RoamHighlightExport" in model_str:
                return mock_highlight_query
            elif "RoamHighlightSnapshot" in model_str:
                snapshot_query = Mock()
                snapshot_query.filter_by.return_value.order_by.return_value.first.return_value = None
                return snapshot_query
            else:
                return Mock()

        writer._session.query.side_effect = mock_query_side_effect
        writer._session.get.return_value = None  # No existing page

        with (
            patch(
                "readwise_local_plus.workflows.roam_daily_note.RoamBatchAction"
            ) as mock_batch_action_class,
            patch("readwise_local_plus.workflows.roam_daily_note.RoamExportBatch"),
            patch(
                "readwise_local_plus.workflows.roam_daily_note.datetime"
            ) as mock_datetime,
        ):
            mock_datetime.now.return_value = datetime(2023, 1, 15, 10, 0, 0)
            mock_batch_action = Mock()
            mock_batch_action.append_a_child_block_action.side_effect = [
                -1,
                -2,
            ]  # header, highlight
            mock_batch_action.execute_batch_action.return_value = {
                "-1": "real-header-uid",
                "-2": "real-highlight-uid",
            }
            mock_batch_action.batch_action_body = {"actions": ["mock_action"]}
            mock_batch_action_class.return_value = mock_batch_action

            mock_client = Mock()
            mock_client.date_to_roam_daily_note.return_value = "01-15-2023"
            mock_client.fetch_block_subtree.return_value = {
                "uid": "header-uid",
                "children": [],
            }
            writer.roam_client = mock_client

            writer._write_highlights()

            # Should only create header and highlight, not book (since book export exists)
            assert mock_batch_action.append_a_child_block_action.call_count == 2

            # Verify highlight is created under existing book UID
            highlight_call = (
                mock_batch_action.append_a_child_block_action.call_args_list[1]
            )
            assert highlight_call[0] == ("existing-book-uid", "Test highlight")

    @patch("readwise_local_plus.workflows.roam_daily_note.RoamClient")
    def test_write_highlights_skips_existing_highlight_export(self, mock_roam_client):
        """Test _write_highlights skips highlights that already exist."""
        writer = RoamDailyNoteHighlightWriter("Test Header")
        writer._session = Mock()

        # Create test data
        mock_book = Mock(spec=Book)
        mock_book.user_book_id = 1
        mock_book.title = "Test Book"

        mock_highlight = Mock(spec=Highlight)
        mock_highlight.id = 1
        mock_highlight.text = "Test highlight"

        test_date = date(2023, 1, 15)
        writer.highlights = {test_date: {mock_book: [mock_highlight]}}

        # Setup existing highlight export
        mock_existing_highlight_export = Mock(spec=RoamHighlightExport)

        # Mock queries
        def mock_query_side_effect(model):
            model_str = str(model)
            if "RoamBookExport" in model_str:
                query = Mock()
                query.filter_by.return_value.first.return_value = None
                return query
            elif "RoamHighlightExport" in model_str:
                query = Mock()
                query.filter_by.return_value.first.return_value = (
                    mock_existing_highlight_export
                )
                return query
            else:
                return Mock()

        writer._session.query.side_effect = mock_query_side_effect
        writer._session.get.return_value = None  # No existing page

        with (
            patch(
                "readwise_local_plus.workflows.roam_daily_note.RoamBatchAction"
            ) as mock_batch_action_class,
            patch("readwise_local_plus.workflows.roam_daily_note.RoamExportBatch"),
            patch(
                "readwise_local_plus.workflows.roam_daily_note.datetime"
            ) as mock_datetime,
        ):
            mock_datetime.now.return_value = datetime(2023, 1, 15, 10, 0, 0)
            mock_batch_action = Mock()
            mock_batch_action.append_a_child_block_action.side_effect = [
                -1,
                -2,
            ]  # header, book only
            mock_batch_action.execute_batch_action.return_value = {
                "-1": "real-header-uid",
                "-2": "real-book-uid",
            }
            mock_batch_action.batch_action_body = {"actions": ["mock_action"]}
            mock_batch_action_class.return_value = mock_batch_action

            mock_client = Mock()
            mock_client.date_to_roam_daily_note.return_value = "01-15-2023"
            mock_client.fetch_block_subtree.return_value = {
                "uid": "header-uid",
                "children": [],
            }
            writer.roam_client = mock_client

            writer._write_highlights()

            # Should only create header and book, not highlight (since highlight export exists)
            assert mock_batch_action.append_a_child_block_action.call_count == 2

    @patch("readwise_local_plus.workflows.roam_daily_note.RoamClient")
    def test_write_highlights_book_without_title(self, mock_roam_client):
        """Test _write_highlights handles books without titles."""
        writer = RoamDailyNoteHighlightWriter("Test Header")
        writer._session = Mock()

        # Create book without title
        mock_book = Mock(spec=Book)
        mock_book.user_book_id = 1
        mock_book.title = None  # No title

        mock_highlight = Mock(spec=Highlight)
        mock_highlight.id = 1
        mock_highlight.text = "Test highlight"

        test_date = date(2023, 1, 15)
        writer.highlights = {test_date: {mock_book: [mock_highlight]}}

        writer._session.get.return_value = None

        # Mock snapshot query chain
        mock_snapshot_query = Mock()
        mock_snapshot_query.filter_by.return_value.order_by.return_value.first.return_value = None

        # Mock other query chains
        mock_other_query = Mock()
        mock_other_query.filter_by.return_value.first.return_value = None

        def mock_query_side_effect(model):
            # Use string representation to avoid __name__ issues with mocks
            model_str = str(model)
            if "RoamHighlightSnapshot" in model_str:
                return mock_snapshot_query
            else:
                return mock_other_query

        writer._session.query.side_effect = mock_query_side_effect

        with (
            patch(
                "readwise_local_plus.workflows.roam_daily_note.RoamBatchAction"
            ) as mock_batch_action_class,
            patch("readwise_local_plus.workflows.roam_daily_note.RoamExportBatch"),
            patch(
                "readwise_local_plus.workflows.roam_daily_note.datetime"
            ) as mock_datetime,
        ):
            mock_datetime.now.return_value = datetime(2023, 1, 15, 10, 0, 0)
            mock_batch_action = Mock()
            mock_batch_action.append_a_child_block_action.side_effect = [-1, -2, -3]
            mock_batch_action.execute_batch_action.return_value = {
                "-1": "header",
                "-2": "book",
                "-3": "highlight",
            }
            mock_batch_action.batch_action_body = {"actions": ["mock_action"]}
            mock_batch_action_class.return_value = mock_batch_action

            mock_client = Mock()
            mock_client.date_to_roam_daily_note.return_value = "01-15-2023"
            mock_client.fetch_block_subtree.return_value = {
                "uid": "header-uid",
                "children": [],
            }
            writer.roam_client = mock_client

            writer._write_highlights()

            # Check that error message is used for book title
            book_call = mock_batch_action.append_a_child_block_action.call_args_list[1]
            assert book_call[0] == (-1, "[ERROR]: Missing title")
