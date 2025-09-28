"""Integration tests for roam.py integration module."""

from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from readwise_local_plus.config import UserConfig
from readwise_local_plus.integrations.roam import (
    RoamBatchAction,
    RoamClient,
)


@pytest.fixture
def mock_roam_config(tmp_path: Path) -> UserConfig:
    """
    Create a temporary user configuration for Roam tests.

    This fixture creates a temporary directory structure and .env file
    with Roam-specific configuration for integration testing.
    """
    temp_application_dir = tmp_path / "readwise-local-plus"
    temp_application_dir.mkdir()
    temp_config_dir = temp_application_dir / ".config" / "readwise-local-plus"
    temp_config_dir.mkdir(parents=True)

    temp_env_file = temp_config_dir / ".env"
    temp_env_file.touch()
    temp_env_file.write_text(
        "READWISE_API_TOKEN=test_readwise_token\nROAM_API_TOKEN=test_roam_token\n"
    )

    user_config = UserConfig(temp_application_dir)
    return user_config


class TestRoamIntegration:
    """Integration tests for the Roam classes working together."""

    def test_temp_uid_generator_with_roam_client(self, mock_roam_config):
        """Test that TempUidGenerator works correctly integrated with RoamClient."""
        with patch(
            "readwise_local_plus.integrations.roam.fetch_user_config"
        ) as mock_fetch:
            mock_fetch.return_value = mock_roam_config

            client = RoamClient()

            # Get several temp UIDs to verify they're sequential
            uid1 = client._get_temp_uid()
            uid2 = client._get_temp_uid()
            uid3 = client._get_temp_uid()

            # Should be sequential negative integers starting from -1
            assert uid1 == -1
            assert uid2 == -2
            assert uid3 == -3

            # Verify the generator state persists
            uid4 = client._get_temp_uid()
            assert uid4 == -4

    def test_roam_client_and_batch_action_integration(self, mock_roam_config):
        """Test RoamClient and RoamBatchAction working together in a real workflow."""
        with (
            patch(
                "readwise_local_plus.integrations.roam.fetch_user_config"
            ) as mock_fetch,
            patch("requests.post") as mock_post,
        ):
            # Setup configuration
            mock_fetch.return_value = mock_roam_config

            # Mock successful Roam API response
            mock_response = Mock()
            mock_response.ok = True
            mock_response.json.return_value = {
                "tempids-to-uids": {"-1": "real-uid-abc123", "-2": "real-uid-def456"}
            }
            mock_post.return_value = mock_response

            # Create client and batch action
            client = RoamClient()
            batch_action = RoamBatchAction()

            # Ensure the client picked up the mocked config
            assert client.graph_name == mock_roam_config.roam_graph_name
            assert client.token == mock_roam_config.roam_api_token

            # Verify they share the same client instance
            assert (
                batch_action.roam_client.graph_name == mock_roam_config.roam_graph_name
            )
            assert batch_action.roam_client.token == mock_roam_config.roam_api_token

            # Add multiple blocks to the batch
            temp_uid1 = batch_action.append_a_child_block_action(
                "parent-uid", "First block content"
            )
            temp_uid2 = batch_action.append_a_child_block_action(
                "parent-uid", "Second block content", heading=2
            )

            # Verify temp UIDs are negative and sequential
            assert temp_uid1 < 0
            assert temp_uid2 < 0
            assert temp_uid2 == temp_uid1 - 1

            # Execute the batch
            result = batch_action.execute_batch_action()

            # Verify the API was called correctly
            mock_post.assert_called_once()
            call_args = mock_post.call_args

            # Check URL (first positional argument)
            expected_url = f"https://api.roamresearch.com/api/graph/{mock_roam_config.roam_graph_name}/write"
            assert call_args[0][0] == expected_url

            # Check headers (keyword arguments)
            headers = call_args.kwargs["headers"]
            assert (
                headers["Authorization"] == f"Bearer {mock_roam_config.roam_api_token}"
            )
            assert (
                headers["x-authorization"]
                == f"Bearer {mock_roam_config.roam_api_token}"
            )

            # Check payload structure
            payload = call_args.kwargs["json"]
            assert payload["action"] == "batch-actions"
            assert len(payload["actions"]) == 2

            # Verify first action
            action1 = payload["actions"][0]
            assert action1["action"] == "create-block"
            assert action1["block"]["string"] == "First block content"
            assert action1["block"]["uid"] == temp_uid1

            # Verify second action
            action2 = payload["actions"][1]
            assert action2["action"] == "create-block"
            assert action2["block"]["string"] == "Second block content"
            assert action2["block"]["heading"] == 2
            assert action2["block"]["uid"] == temp_uid2

            # Verify result mapping
            assert result[str(temp_uid1)] == "real-uid-abc123"
            assert result[str(temp_uid2)] == "real-uid-def456"

    def test_roam_client_individual_write_integration(self, mock_roam_config):
        """Test RoamClient individual write_child_block integration."""
        with (
            patch(
                "readwise_local_plus.integrations.roam.fetch_user_config"
            ) as mock_fetch,
            patch("requests.post") as mock_post,
        ):
            mock_fetch.return_value = mock_roam_config

            # Mock successful response for individual write
            mock_response = Mock()
            mock_response.ok = True
            mock_response.json.return_value = {
                "tempids-to-uids": {"-1": "individual-block-uid"}
            }
            mock_post.return_value = mock_response

            client = RoamClient()

            # Write a single child block
            result_uid = client.write_child_block(
                "parent-block-uid", ["Line 1", "Line 2"], heading=1, open=True
            )

            # Verify the result
            assert result_uid == "individual-block-uid"

            # Verify the API call
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            payload = call_args.kwargs["json"]

            # Check the payload structure for individual write
            assert payload["action"] == "batch-actions"
            assert len(payload["actions"]) == 1

            action = payload["actions"][0]
            assert action["action"] == "create-block"
            assert action["block"]["string"] == ["Line 1", "Line 2"]
            assert action["block"]["heading"] == 1
            assert action["block"]["open"] is True
            assert action["location"]["parent-uid"] == "parent-block-uid"

    def test_roam_client_query_operations_integration(self, mock_roam_config):
        """Test RoamClient query operations in an integrated scenario."""
        with (
            patch(
                "readwise_local_plus.integrations.roam.fetch_user_config"
            ) as mock_fetch,
            patch("requests.post") as mock_post,
        ):
            mock_fetch.return_value = mock_roam_config
            client = RoamClient()

            # Test date conversion utility
            test_date = date(2023, 9, 15)
            daily_note_uid = client.date_to_roam_daily_note(test_date)
            assert daily_note_uid == "09-15-2023"

            # Mock response for page lookup
            mock_response = Mock()
            mock_response.ok = True
            mock_response.json.return_value = {"result": [["daily-note-uid-12345"]]}
            mock_post.return_value = mock_response

            # Test fetching page UID
            page_uid = client.fetch_page_uid_from_title("Test Page")
            assert page_uid == "daily-note-uid-12345"

            # Verify the query was constructed correctly
            call_args = mock_post.call_args
            payload = call_args.kwargs["json"]
            assert "query" in payload
            assert "args" in payload
            assert payload["args"] == ["Test Page"]

    def test_uid_generator_persistence_across_operations(self, mock_roam_config):
        """Test that UID generator maintains state across multiple operations."""
        with patch(
            "readwise_local_plus.integrations.roam.fetch_user_config"
        ) as mock_fetch:
            mock_fetch.return_value = mock_roam_config

            # Create client and batch action
            client = RoamClient()
            batch_action = RoamBatchAction()

            # Both should share the same underlying UID generator through the client
            assert batch_action.roam_client is not client  # Different instances

            # But each maintains its own generator state
            uid_from_client = client._get_temp_uid()  # Should be -1
            uid_from_batch = (
                batch_action.roam_client._get_temp_uid()
            )  # Should be -1 (separate generator)

            assert uid_from_client == -1
            assert uid_from_batch == -1

            # Next calls should increment independently
            assert client._get_temp_uid() == -2
            assert batch_action.roam_client._get_temp_uid() == -2

    def test_error_handling_integration(self, mock_roam_config):
        """Test integrated error handling across Roam components."""
        with (
            patch(
                "readwise_local_plus.integrations.roam.fetch_user_config"
            ) as mock_fetch,
            patch("requests.post") as mock_post,
        ):
            mock_fetch.return_value = mock_roam_config

            # Test various error scenarios
            from readwise_local_plus.integrations.roam import (
                RoamAPIError,
                RoamRateLimitError,
                RoamUnauthorizedError,
                RoamUnavailableError,
            )

            client = RoamClient()

            # Test 401 unauthorized
            mock_response = Mock()
            mock_response.ok = False
            mock_response.status_code = 401
            mock_post.return_value = mock_response

            with pytest.raises(RoamUnauthorizedError):
                client.fetch_page_uid_from_title("Test Page")

            # Test 429 rate limit
            mock_response.status_code = 429
            with pytest.raises(RoamRateLimitError):
                client.fetch_page_uid_from_title("Test Page")

            # Test 503 unavailable
            mock_response.status_code = 503
            with pytest.raises(RoamUnavailableError):
                client.fetch_page_uid_from_title("Test Page")

            # Test other errors
            mock_response.status_code = 500
            mock_response.json.return_value = {"error": "Internal server error"}
            with pytest.raises(RoamAPIError, match="500"):
                client.fetch_page_uid_from_title("Test Page")
