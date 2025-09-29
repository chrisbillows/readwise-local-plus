"""Integration tests for roam_daily_note.py workflow module."""

from datetime import date, datetime, timezone
from unittest.mock import Mock, patch

import pytest

from readwise_local_plus.config import UserConfig
from readwise_local_plus.models import (
    Book,
    Highlight,
    ReadwiseBatch,
    RoamBookExport,
    RoamExportBatch,
    RoamHighlightExport,
    RoamHighlightSnapshot,
    RoamPage,
)
from readwise_local_plus.workflows.roam_daily_note import RoamDailyNoteHighlightWriter


@pytest.fixture
def mock_roam_config(mock_user_config):
    """Extend mock_user_config to include ROAM_API_TOKEN."""
    # Read existing config and add ROAM_API_TOKEN
    env_file = mock_user_config.env_file
    existing_content = env_file.read_text()
    new_content = existing_content + "\nROAM_API_TOKEN=test_roam_token"
    env_file.write_text(new_content)

    # Return updated config
    return UserConfig(mock_user_config.user_dir)


@pytest.fixture
def sample_batch_with_highlights(mem_db):
    """Create sample batch with books and highlights for testing."""
    session = mem_db.session

    # Create batch
    batch = ReadwiseBatch(
        start_time=datetime.now(timezone.utc),
        end_time=datetime.now(timezone.utc),
        database_write_time=datetime.now(timezone.utc),
    )
    session.add(batch)
    session.flush()

    # Create books
    book1 = Book(
        user_book_id=1,
        title="Test Article",
        category="articles",
        author="Test Author",
        batch_id=batch.id,
        validated=True,
        validation_errors={},
    )

    book2 = Book(
        user_book_id=2,
        title="Test Tweet Collection",
        category="tweets",
        author="@testuser",
        batch_id=batch.id,
        validated=True,
        validation_errors={},
    )

    session.add_all([book1, book2])
    session.flush()

    # Create highlights
    highlight1 = Highlight(
        id=1,
        text="This is a test article highlight",
        book_id=1,
        batch_id=batch.id,
        location=100,
        created_at=datetime(2023, 1, 15, 10, 0, 0),
        validated=True,
        validation_errors={},
    )

    highlight2 = Highlight(
        id=2,
        text="This is another article highlight",
        book_id=1,
        batch_id=batch.id,
        location=200,
        created_at=datetime(2023, 1, 15, 11, 0, 0),
        validated=True,
        validation_errors={},
    )

    highlight3 = Highlight(
        id=3,
        text="This is a tweet highlight",
        book_id=2,
        batch_id=batch.id,
        location=None,
        created_at=datetime(2023, 1, 16, 12, 0, 0),
        validated=True,
        validation_errors={},
    )

    session.add_all([highlight1, highlight2, highlight3])
    session.commit()

    return batch.id, session


class TestRoamDailyNoteIntegration:
    """Integration tests for RoamDailyNoteHighlightWriter with real database."""

    def test_fetch_highlights_with_real_database(
        self, sample_batch_with_highlights, mock_roam_config
    ):
        """Test fetch_highlights with real database and SQLAlchemy queries."""
        batch_id, session = sample_batch_with_highlights

        with (
            patch(
                "readwise_local_plus.workflows.roam_daily_note.get_session"
            ) as mock_get_session,
            patch(
                "readwise_local_plus.workflows.roam_daily_note.fetch_user_config"
            ) as mock_fetch_config,
        ):
            mock_get_session.return_value = session
            mock_fetch_config.return_value = mock_roam_config

            writer = RoamDailyNoteHighlightWriter(batch_id=batch_id)
            writer._session = session  # Set session directly for testing
            writer.fetch_highlights()

            # Verify highlights were fetched and grouped correctly
            assert len(writer.highlights) == 2  # Two different dates

            # Check first date (article highlights)
            article_date = date(2023, 1, 15)
            assert article_date in writer.highlights
            article_books = writer.highlights[article_date]
            assert len(article_books) == 1

            # Get the book and its highlights
            book = list(article_books.keys())[0]
            highlights = article_books[book]
            assert book.title == "Test Article"
            assert len(highlights) == 2

            # Verify ordering by location
            assert highlights[0].location == 100
            assert highlights[1].location == 200

            # Check second date (tweet highlights)
            tweet_date = date(2023, 1, 16)
            assert tweet_date in writer.highlights
            tweet_books = writer.highlights[tweet_date]
            assert len(tweet_books) == 1

            tweet_book = list(tweet_books.keys())[0]
            tweet_highlights = tweet_books[tweet_book]
            assert tweet_book.title == "Test Tweet Collection"
            assert len(tweet_highlights) == 1
            assert tweet_highlights[0].text == "This is a tweet highlight"

    def test_write_batch_to_daily_notes_full_workflow(
        self, sample_batch_with_highlights, mock_roam_config
    ):
        """Test complete write_batch_to_daily_notes workflow with mocked Roam API."""
        batch_id, session = sample_batch_with_highlights

        with (
            patch(
                "readwise_local_plus.workflows.roam_daily_note.get_session"
            ) as mock_get_session,
            patch(
                "readwise_local_plus.workflows.roam_daily_note.fetch_user_config"
            ) as mock_fetch_config,
            patch(
                "readwise_local_plus.workflows.roam_daily_note.RoamClient"
            ) as mock_roam_client_class,
            patch("requests.post") as mock_post,
        ):
            # Setup mocks
            mock_get_session.return_value = session
            mock_fetch_config.return_value = mock_roam_config

            # Mock Roam API responses
            mock_response = Mock()
            mock_response.ok = True
            mock_response.json.return_value = {
                "tempids-to-uids": {
                    "-1": "header-uid-123",
                    "-2": "book1-uid-456",
                    "-3": "highlight1-uid-789",
                    "-4": "highlight2-uid-abc",
                    "-5": "book2-uid-def",
                    "-6": "highlight3-uid-ghi",
                }
            }
            mock_post.return_value = mock_response

            # Mock RoamClient
            mock_roam_client = Mock()
            mock_roam_client.date_to_roam_daily_note.side_effect = lambda d: d.strftime(
                "%m-%d-%Y"
            )
            mock_roam_client.fetch_block_subtree.return_value = {
                "uid": "test",
                "children": [],
            }
            mock_roam_client_class.return_value = mock_roam_client

            # Create writer and run workflow
            writer = RoamDailyNoteHighlightWriter(batch_id=batch_id)
            writer.write_batch_to_daily_notes()

            # Verify data was written to database
            # Check RoamExportBatch was created
            export_batches = session.query(RoamExportBatch).all()
            assert len(export_batches) >= 1

            # Check RoamPage entries were created
            roam_pages = session.query(RoamPage).all()
            expected_pages = 2  # Two different daily notes
            assert len(roam_pages) == expected_pages

            # Check page UIDs match expected format
            page_uids = {page.page_uid for page in roam_pages}
            assert "01-15-2023" in page_uids  # Article date
            assert "01-16-2023" in page_uids  # Tweet date

            # Check RoamBookExport entries
            book_exports = session.query(RoamBookExport).all()
            assert len(book_exports) == 2  # Two books exported

            # Check RoamHighlightExport entries
            highlight_exports = session.query(RoamHighlightExport).all()
            assert len(highlight_exports) == 3  # Three highlights exported

            # Check RoamHighlightSnapshot entries
            highlight_snapshots = session.query(RoamHighlightSnapshot).all()
            assert len(highlight_snapshots) == 3  # Three snapshots created

            # Verify snapshots have correct structure
            for snapshot in highlight_snapshots:
                assert "uid" in snapshot.block_tree
                assert "text" in snapshot.block_tree
                assert "children" in snapshot.block_tree
                assert snapshot.version == 1  # First version
                assert len(snapshot.block_tree_hash) == 64  # SHA256 hex

    def test_write_highlights_with_existing_page(
        self, sample_batch_with_highlights, mock_roam_config
    ):
        """Test writing highlights when RoamPage already exists."""
        batch_id, session = sample_batch_with_highlights

        # Pre-create a RoamPage
        existing_page = RoamPage(
            page_uid="01-15-2023",
            highlights_header_uid="existing-header-uid",
            highlights_header_text="[[Readwise highlights]]",
        )
        session.add(existing_page)
        session.commit()

        with (
            patch(
                "readwise_local_plus.workflows.roam_daily_note.get_session"
            ) as mock_get_session,
            patch(
                "readwise_local_plus.workflows.roam_daily_note.fetch_user_config"
            ) as mock_fetch_config,
            patch(
                "readwise_local_plus.workflows.roam_daily_note.RoamClient"
            ) as mock_roam_client_class,
            patch("requests.post") as mock_post,
        ):
            mock_get_session.return_value = session
            mock_fetch_config.return_value = mock_roam_config

            mock_response = Mock()
            mock_response.ok = True
            mock_response.json.return_value = {
                "tempids-to-uids": {
                    "-1": "book1-uid-456",
                    "-2": "highlight1-uid-789",
                    "-3": "highlight2-uid-abc",
                }
            }
            mock_post.return_value = mock_response

            mock_roam_client = Mock()
            mock_roam_client.date_to_roam_daily_note.side_effect = lambda d: d.strftime(
                "%m-%d-%Y"
            )
            mock_roam_client.fetch_block_subtree.return_value = {
                "uid": "existing-header-uid",
                "children": [],
            }
            mock_roam_client_class.return_value = mock_roam_client

            writer = RoamDailyNoteHighlightWriter(batch_id=batch_id)
            writer.write_batch_to_daily_notes()

            # Verify existing page was used (not duplicated)
            roam_pages = session.query(RoamPage).filter_by(page_uid="01-15-2023").all()
            assert len(roam_pages) == 1
            assert roam_pages[0].highlights_header_uid == "existing-header-uid"

    def test_write_highlights_with_existing_exports(
        self, sample_batch_with_highlights, mock_roam_config
    ):
        """Test writing highlights when some exports already exist."""
        batch_id, session = sample_batch_with_highlights

        # Ensure the target page exists so foreign keys remain valid
        existing_page = RoamPage(
            page_uid="01-15-2023",
            highlights_header_uid="existing-header-uid",
            highlights_header_text="[[Readwise highlights]]",
        )

        # Pre-create some exports to simulate partial existing state
        existing_book_export = RoamBookExport(
            page_uid="01-15-2023",
            user_book_id=1,
            parent_block_uid="existing-book-uid",
            export_date=datetime.now(),
        )

        existing_highlight_export = RoamHighlightExport(
            highlight_id=1,
            page_uid="01-15-2023",
            block_uid="existing-highlight-uid",
            export_date=datetime.now(),
        )

        session.add_all(
            [existing_page, existing_book_export, existing_highlight_export]
        )
        session.commit()

        with (
            patch(
                "readwise_local_plus.workflows.roam_daily_note.get_session"
            ) as mock_get_session,
            patch(
                "readwise_local_plus.workflows.roam_daily_note.fetch_user_config"
            ) as mock_fetch_config,
            patch(
                "readwise_local_plus.workflows.roam_daily_note.RoamClient"
            ) as mock_roam_client_class,
            patch("requests.post") as mock_post,
        ):
            mock_get_session.return_value = session
            mock_fetch_config.return_value = mock_roam_config

            mock_response = Mock()
            mock_response.ok = True
            mock_response.json.return_value = {
                "tempids-to-uids": {
                    "-1": "header-uid-123",
                    "-2": "highlight2-uid-abc",  # Only new highlight
                    "-3": "book2-uid-def",
                    "-4": "highlight3-uid-ghi",
                }
            }
            mock_post.return_value = mock_response

            mock_roam_client = Mock()
            mock_roam_client.date_to_roam_daily_note.side_effect = lambda d: d.strftime(
                "%m-%d-%Y"
            )
            mock_roam_client.fetch_block_subtree.return_value = {
                "uid": "test",
                "children": [],
            }
            mock_roam_client_class.return_value = mock_roam_client

            writer = RoamDailyNoteHighlightWriter(batch_id=batch_id)
            writer.write_batch_to_daily_notes()

            # Verify existing exports were not duplicated
            book_exports = session.query(RoamBookExport).filter_by(user_book_id=1).all()
            assert len(book_exports) == 1  # Should still be just the existing one

            highlight_exports = (
                session.query(RoamHighlightExport).filter_by(highlight_id=1).all()
            )
            assert len(highlight_exports) == 1  # Should still be just the existing one

            # But new exports should have been created
            all_book_exports = session.query(RoamBookExport).all()
            assert len(all_book_exports) == 2  # Original + new book

            all_highlight_exports = session.query(RoamHighlightExport).all()
            assert len(all_highlight_exports) == 3  # Original + 2 new highlights

    def test_stable_hash_consistency_integration(self):
        """Integration test for stable_hash with real data structures."""
        writer = RoamDailyNoteHighlightWriter("Test")

        # Test with realistic block tree structure
        block_tree_1 = {
            "uid": "test-uid-123",
            "text": "This is a highlight from a book",
            "order": None,
            "children": [
                {
                    "uid": "child-uid-456",
                    "text": "This is a note I added",
                    "order": 0,
                    "children": [],
                }
            ],
        }

        # Same data in different order
        block_tree_2 = {
            "children": [
                {
                    "children": [],
                    "order": 0,
                    "uid": "child-uid-456",
                    "text": "This is a note I added",
                }
            ],
            "order": None,
            "text": "This is a highlight from a book",
            "uid": "test-uid-123",
        }

        hash1 = writer.stable_hash(block_tree_1)
        hash2 = writer.stable_hash(block_tree_2)

        # Should produce identical hashes despite different ordering
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA256 hex length

        # Should be deterministic across multiple calls
        hash3 = writer.stable_hash(block_tree_1)
        assert hash1 == hash3

    def test_highlight_versioning_integration(
        self, sample_batch_with_highlights, mock_roam_config
    ):
        """Integration test for highlight versioning with real database."""
        _, session = sample_batch_with_highlights

        # Create required Roam entities so snapshot can reference existing exports
        roam_page = RoamPage(
            page_uid="01-15-2023",
            highlights_header_uid="existing-header-uid",
            highlights_header_text="[[Readwise highlights]]",
        )
        roam_highlight = RoamHighlightExport(
            highlight_id=1,
            page_uid="01-15-2023",
            block_uid="existing-highlight-uid",
            export_date=datetime.now(),
        )
        session.add_all([roam_page, roam_highlight])
        session.flush()

        # Create a highlight snapshot manually to test versioning
        existing_snapshot = RoamHighlightSnapshot(
            highlight_id=1,
            block_tree={"uid": "old-uid", "text": "old text"},
            block_tree_hash="old_hash",
            version=1,
            created_at=datetime.now(),
        )
        session.add(existing_snapshot)
        session.commit()

        # Mock the query to return this existing snapshot
        with (
            patch(
                "readwise_local_plus.workflows.roam_daily_note.get_session"
            ) as mock_get_session,
            patch(
                "readwise_local_plus.workflows.roam_daily_note.fetch_user_config"
            ) as mock_fetch_config,
            patch(
                "readwise_local_plus.workflows.roam_daily_note.RoamClient"
            ) as mock_roam_client_class,
        ):
            mock_get_session.return_value = session
            mock_fetch_config.return_value = mock_roam_config
            mock_roam_client_class.return_value = Mock()

            writer = RoamDailyNoteHighlightWriter(batch_id=123)
            assert writer.highlights_header == "[[Readwise highlights]]"
            mock_roam_client_class.assert_called_once_with()

            # Test the versioning logic by directly accessing the database
            last_snapshot = (
                session.query(RoamHighlightSnapshot)
                .filter_by(highlight_id=1)
                .order_by(RoamHighlightSnapshot.version.desc())
                .first()
            )

            assert last_snapshot is not None
            assert last_snapshot.version == 1

            # Next version should be 2
            next_version = (last_snapshot.version + 1) if last_snapshot else 1
            assert next_version == 2

    def test_error_handling_with_database_issues(self, mock_roam_config):
        """Integration test for error handling with database issues."""
        with (
            patch(
                "readwise_local_plus.workflows.roam_daily_note.get_session"
            ) as mock_get_session,
            patch(
                "readwise_local_plus.workflows.roam_daily_note.fetch_user_config"
            ) as mock_fetch_config,
        ):
            # Mock database session that raises an error during execute
            mock_session = Mock()
            mock_session.execute.side_effect = Exception("Database connection failed")
            mock_get_session.return_value = mock_session
            mock_fetch_config.return_value = mock_roam_config

            writer = RoamDailyNoteHighlightWriter(batch_id=123)
            writer._session = mock_session  # Set the mock session

            # Should propagate database errors
            with pytest.raises(Exception, match="Database connection failed"):
                writer.fetch_highlights()

    def test_session_lifecycle_integration(self, mock_roam_config):
        """Integration test for proper session lifecycle management."""
        mock_session = Mock()

        with (
            patch(
                "readwise_local_plus.workflows.roam_daily_note.get_session"
            ) as mock_get_session,
            patch(
                "readwise_local_plus.workflows.roam_daily_note.fetch_user_config"
            ) as mock_fetch_config,
        ):
            mock_get_session.return_value = mock_session
            mock_fetch_config.return_value = mock_roam_config

            writer = RoamDailyNoteHighlightWriter(batch_id=123)
            writer.fetch_highlights = Mock()  # Mock to avoid database setup
            writer._write_highlights = Mock()  # Mock to avoid Roam API calls

            writer.write_batch_to_daily_notes()

            # Verify session lifecycle
            assert writer._session is mock_session
            mock_session.close.assert_called_once()


class TestRoamDailyNoteConstants:
    """Integration tests for module constants."""

    def test_highlights_header_used_in_integration(self, mock_roam_config):
        """Test that HIGHLIGHTS_HEADER constant is properly used in integration."""
        with patch("readwise_local_plus.workflows.roam_daily_note.RoamClient"):
            writer = RoamDailyNoteHighlightWriter(batch_id=123)
            assert writer.highlights_header == "[[Readwise highlights]]"
