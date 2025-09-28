"""Unit tests for roam.py integration module."""

from datetime import date
from unittest.mock import Mock, patch

import pytest

from readwise_local_plus.integrations.roam import (
    RoamAPIError,
    RoamBatchAction,
    RoamClient,
    RoamRateLimitError,
    RoamUnauthorizedError,
    RoamUnavailableError,
    TempUidGenerator,
)


class TestTempUidGenerator:
    """Test the TempUidGenerator class."""

    def test_init_default(self):
        """Test initialization with default start value."""
        generator = TempUidGenerator()
        assert generator._next == -1

    def test_init_custom_start(self):
        """Test initialization with custom start value."""
        generator = TempUidGenerator(-5)
        assert generator._next == -5

    def test_init_positive_start_raises_error(self):
        """Test that positive start value raises ValueError."""
        with pytest.raises(
            ValueError, match="TempUidGenerator must start with a negative integer"
        ):
            TempUidGenerator(1)

    def test_init_zero_start_raises_error(self):
        """Test that zero start value raises ValueError."""
        with pytest.raises(
            ValueError, match="TempUidGenerator must start with a negative integer"
        ):
            TempUidGenerator(0)

    def test_next_returns_current_and_decrements(self):
        """Test that next() returns current value and decrements."""
        generator = TempUidGenerator(-1)

        assert generator.next() == -1
        assert generator._next == -2

        assert generator.next() == -2
        assert generator._next == -3

        assert generator.next() == -3
        assert generator._next == -4

    def test_next_sequence_with_custom_start(self):
        """Test next() sequence with custom start value."""
        generator = TempUidGenerator(-10)

        assert generator.next() == -10
        assert generator.next() == -11
        assert generator.next() == -12

    def test_reset_default(self):
        """Test reset with default value."""
        generator = TempUidGenerator(-5)
        generator.next()  # Should be at -6

        generator.reset()
        assert generator._next == -1

    def test_reset_custom_value(self):
        """Test reset with custom value."""
        generator = TempUidGenerator(-1)
        generator.next()  # Should be at -2

        generator.reset(-10)
        assert generator._next == -10

    def test_reset_positive_value_raises_error(self):
        """Test that reset with positive value raises ValueError."""
        generator = TempUidGenerator()

        with pytest.raises(
            ValueError, match="TempUidGenerator must start with a negative integer"
        ):
            generator.reset(5)

    def test_reset_zero_raises_error(self):
        """Test that reset with zero raises ValueError."""
        generator = TempUidGenerator()

        with pytest.raises(
            ValueError, match="TempUidGenerator must start with a negative integer"
        ):
            generator.reset(0)


class TestRoamClient:
    """Test the RoamClient class."""

    @patch("readwise_local_plus.integrations.roam.fetch_user_config")
    def test_init(self, mock_fetch_config):
        """Test RoamClient initialization."""
        mock_config = Mock()
        mock_config.roam_graph_name = "test-graph"
        mock_config.roam_api_token = "test-token"
        mock_fetch_config.return_value = mock_config

        client = RoamClient()

        assert client.graph_name == "test-graph"
        assert client.token == "test-token"
        assert isinstance(client.uid_generator, TempUidGenerator)

    def test_get_temp_uid(self):
        """Test _get_temp_uid method."""
        with patch("readwise_local_plus.integrations.roam.fetch_user_config"):
            client = RoamClient()

            # Mock the uid_generator
            client.uid_generator = Mock()
            client.uid_generator.next.return_value = -1

            assert client._get_temp_uid() == -1
            client.uid_generator.next.assert_called_once()

    def test_headers(self):
        """Test _headers method."""
        with patch(
            "readwise_local_plus.integrations.roam.fetch_user_config"
        ) as mock_config:
            mock_config.return_value.roam_api_token = "test-token"
            client = RoamClient()

            headers = client._headers()

            expected_headers = {
                "accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": "Bearer test-token",
                "x-authorization": "Bearer test-token",
            }
            assert headers == expected_headers

    def test_handle_response_success(self):
        """Test _handle_response with successful response."""
        with patch("readwise_local_plus.integrations.roam.fetch_user_config"):
            client = RoamClient()

            mock_response = Mock()
            mock_response.ok = True
            mock_response.json.return_value = {"result": "success"}

            result = client._handle_response(mock_response)
            assert result == {"result": "success"}

    def test_handle_response_unauthorized(self):
        """Test _handle_response with 401 unauthorized."""
        with patch("readwise_local_plus.integrations.roam.fetch_user_config"):
            client = RoamClient()

            mock_response = Mock()
            mock_response.ok = False
            mock_response.status_code = 401

            with pytest.raises(
                RoamUnauthorizedError, match="Invalid or unauthorized token"
            ):
                client._handle_response(mock_response)

    def test_handle_response_rate_limit(self):
        """Test _handle_response with 429 rate limit."""
        with patch("readwise_local_plus.integrations.roam.fetch_user_config"):
            client = RoamClient()

            mock_response = Mock()
            mock_response.ok = False
            mock_response.status_code = 429

            with pytest.raises(RoamRateLimitError, match="Rate limit exceeded"):
                client._handle_response(mock_response)

    def test_handle_response_unavailable(self):
        """Test _handle_response with 503 unavailable."""
        with patch("readwise_local_plus.integrations.roam.fetch_user_config"):
            client = RoamClient()

            mock_response = Mock()
            mock_response.ok = False
            mock_response.status_code = 503

            with pytest.raises(
                RoamUnavailableError, match="Graph is unavailable or not ready"
            ):
                client._handle_response(mock_response)

    def test_handle_response_other_error_with_json(self):
        """Test _handle_response with other error that has JSON response."""
        with patch("readwise_local_plus.integrations.roam.fetch_user_config"):
            client = RoamClient()

            mock_response = Mock()
            mock_response.ok = False
            mock_response.status_code = 500
            mock_response.json.return_value = {"error": "Server error"}

            with pytest.raises(RoamAPIError, match="500: {'error': 'Server error'}"):
                client._handle_response(mock_response)

    def test_handle_response_other_error_with_text(self):
        """Test _handle_response with other error that has text response."""
        with patch("readwise_local_plus.integrations.roam.fetch_user_config"):
            client = RoamClient()

            mock_response = Mock()
            mock_response.ok = False
            mock_response.status_code = 500
            mock_response.json.side_effect = Exception("Not JSON")
            mock_response.text = "Server error"

            with pytest.raises(RoamAPIError, match="500: Server error"):
                client._handle_response(mock_response)

    @patch("requests.post")
    def test_post(self, mock_post):
        """Test _post method."""
        with patch(
            "readwise_local_plus.integrations.roam.fetch_user_config"
        ) as mock_config:
            mock_config.return_value.roam_graph_name = "test-graph"
            mock_config.return_value.roam_api_token = "test-token"
            client = RoamClient()

            mock_response = Mock()
            mock_response.ok = True
            mock_response.json.return_value = {"result": "success"}
            mock_post.return_value = mock_response

            result = client._post("test-endpoint", {"key": "value"})

            mock_post.assert_called_once_with(
                "https://api.roamresearch.com/api/graph/test-graph/test-endpoint",
                headers={
                    "accept": "application/json",
                    "Content-Type": "application/json",
                    "Authorization": "Bearer test-token",
                    "x-authorization": "Bearer test-token",
                },
                json={"key": "value"},
            )
            assert result == {"result": "success"}

    def test_query(self):
        """Test _query method."""
        with patch("readwise_local_plus.integrations.roam.fetch_user_config"):
            client = RoamClient()
            client._post = Mock(return_value={"result": "query_result"})

            result = client._query("test_datalog", ["arg1", "arg2"])

            client._post.assert_called_once_with(
                "q", {"query": "test_datalog", "args": ["arg1", "arg2"]}
            )
            assert result == {"result": "query_result"}

    def test_write(self):
        """Test _write method."""
        with patch("readwise_local_plus.integrations.roam.fetch_user_config"):
            client = RoamClient()
            client._post = Mock(return_value={"result": "write_result"})

            result = client._write({"action": "create-block"})

            client._post.assert_called_once_with("write", {"action": "create-block"})
            assert result == {"result": "write_result"}

    def test_pull(self):
        """Test _pull method."""
        with patch("readwise_local_plus.integrations.roam.fetch_user_config"):
            client = RoamClient()
            client._post = Mock(return_value={"result": "pull_result"})

            result = client._pull({"eid": "test-uid"})

            client._post.assert_called_once_with("pull", {"eid": "test-uid"})
            assert result == {"result": "pull_result"}

    def test_date_to_roam_daily_note(self):
        """Test date_to_roam_daily_note static method."""
        test_date = date(2023, 7, 15)
        result = RoamClient.date_to_roam_daily_note(test_date)
        assert result == "07-15-2023"

        test_date = date(2023, 12, 31)
        result = RoamClient.date_to_roam_daily_note(test_date)
        assert result == "12-31-2023"

    def test_fetch_block_subtree(self):
        """Test fetch_block_subtree method."""
        with patch("readwise_local_plus.integrations.roam.fetch_user_config"):
            client = RoamClient()

            mock_result = {
                "result": [
                    [
                        {
                            ":block/uid": "test-uid",
                            ":block/string": "test content",
                            ":block/children": [],
                        }
                    ]
                ]
            }
            client._query = Mock(return_value=mock_result)

            result = client.fetch_block_subtree("test-uid")

            expected_result = {
                "uid": "test-uid",
                "text": "test content",
                "order": None,
                "children": [],
            }
            assert result == expected_result

    def test_fetch_block_subtree_no_result(self):
        """Test fetch_block_subtree with no result."""
        with patch("readwise_local_plus.integrations.roam.fetch_user_config"):
            client = RoamClient()
            client._query = Mock(return_value={"result": []})

            result = client.fetch_block_subtree("nonexistent-uid")
            assert result == {}

    def test_fetch_block_subtrees(self):
        """Test fetch_block_subtrees method."""
        with patch("readwise_local_plus.integrations.roam.fetch_user_config"):
            client = RoamClient()

            mock_result = {
                "result": [
                    [
                        {
                            ":block/uid": "uid1",
                            ":block/string": "content1",
                            ":block/children": [],
                        }
                    ],
                    [
                        {
                            ":block/uid": "uid2",
                            ":block/string": "content2",
                            ":block/children": [],
                        }
                    ],
                ]
            }
            client._query = Mock(return_value=mock_result)

            result = client.fetch_block_subtrees(["uid1", "uid2"])

            expected_result = {
                "uid1": {
                    "uid": "uid1",
                    "text": "content1",
                    "order": None,
                    "children": [],
                },
                "uid2": {
                    "uid": "uid2",
                    "text": "content2",
                    "order": None,
                    "children": [],
                },
            }
            assert result == expected_result

    def test_fetch_child_blocks(self):
        """Test fetch_child_blocks method."""
        with patch("readwise_local_plus.integrations.roam.fetch_user_config"):
            client = RoamClient()

            mock_result = {
                ":block/children": [
                    {":block/string": "child1", ":block/uid": "uid1"},
                    {":block/string": "child2", ":block/uid": "uid2"},
                ]
            }
            client.fetch_block_attributes = Mock(return_value=mock_result)

            result = client.fetch_child_blocks("parent-uid")

            expected_result = [{"child1": "uid1"}, {"child2": "uid2"}]
            assert result == expected_result

    def test_fetch_child_blocks_no_result(self):
        """Test fetch_child_blocks with no result."""
        with patch("readwise_local_plus.integrations.roam.fetch_user_config"):
            client = RoamClient()
            client.fetch_block_attributes = Mock(return_value=None)

            result = client.fetch_child_blocks("nonexistent-uid")
            assert result is None

    def test_fetch_child_blocks_with_none_values(self):
        """Test fetch_child_blocks with None values in children."""
        with patch("readwise_local_plus.integrations.roam.fetch_user_config"):
            client = RoamClient()

            mock_result = {
                ":block/children": [
                    {":block/string": "child1", ":block/uid": "uid1"},
                    {":block/string": None, ":block/uid": "uid2"},  # None string
                    {":block/string": "child3", ":block/uid": None},  # None uid
                    {":block/string": "child4", ":block/uid": "uid4"},
                ]
            }
            client.fetch_block_attributes = Mock(return_value=mock_result)

            result = client.fetch_child_blocks("parent-uid")

            # Should only include valid entries
            expected_result = [{"child1": "uid1"}, {"child4": "uid4"}]
            assert result == expected_result

    def test_fetch_page_uid_from_title(self):
        """Test fetch_page_uid_from_title method."""
        with patch("readwise_local_plus.integrations.roam.fetch_user_config"):
            client = RoamClient()

            mock_result = {"result": [["page-uid-123"]]}
            client._query = Mock(return_value=mock_result)

            result = client.fetch_page_uid_from_title("Test Page")
            assert result == "page-uid-123"

    def test_fetch_page_uid_from_title_no_result(self):
        """Test fetch_page_uid_from_title with no result."""
        with patch("readwise_local_plus.integrations.roam.fetch_user_config"):
            client = RoamClient()

            mock_result = {"result": []}
            client._query = Mock(return_value=mock_result)

            result = client.fetch_page_uid_from_title("Nonexistent Page")
            assert result is None

    def test_fetch_block_attributes(self):
        """Test fetch_block_attributes method."""
        with patch("readwise_local_plus.integrations.roam.fetch_user_config"):
            client = RoamClient()

            mock_result = {
                "result": {":block/uid": "test-uid", ":block/string": "test"}
            }
            client._post = Mock(return_value=mock_result)

            result = client.fetch_block_attributes("test-uid", [":block/string"])

            expected_payload = {
                "eid": '[:block/uid "test-uid"]',
                "selector": "[:block/string]",
            }
            client._post.assert_called_once_with("pull", expected_payload)
            assert result == {":block/uid": "test-uid", ":block/string": "test"}

    def test_write_child_block(self):
        """Test write_child_block method."""
        with patch("readwise_local_plus.integrations.roam.fetch_user_config"):
            client = RoamClient()
            client._get_temp_uid = Mock(return_value=-1)
            client._write = Mock(
                return_value={"tempids-to-uids": {"-1": "real-uid-123"}}
            )

            result = client.write_child_block("parent-uid", ["Line 1", "Line 2"])

            assert result == "real-uid-123"

            # Verify the write was called with correct payload
            expected_payload = {
                "action": "batch-actions",
                "actions": [
                    {
                        "action": "create-block",
                        "location": {"order": "last", "parent-uid": "parent-uid"},
                        "block": {"string": ["Line 1", "Line 2"], "uid": -1},
                    }
                ],
            }
            client._write.assert_called_once_with(expected_payload)

    def test_write_child_block_with_heading(self):
        """Test write_child_block with heading parameter."""
        with patch("readwise_local_plus.integrations.roam.fetch_user_config"):
            client = RoamClient()
            client._get_temp_uid = Mock(return_value=-1)
            client._write = Mock(
                return_value={"tempids-to-uids": {"-1": "real-uid-123"}}
            )

            result = client.write_child_block("parent-uid", ["Header"], heading=2)

            assert result == "real-uid-123"

            # Verify the heading was included
            call_args = client._write.call_args[0][0]
            assert call_args["actions"][0]["block"]["heading"] == 2

    def test_write_child_block_with_open(self):
        """Test write_child_block with open parameter."""
        with patch("readwise_local_plus.integrations.roam.fetch_user_config"):
            client = RoamClient()
            client._get_temp_uid = Mock(return_value=-1)
            client._write = Mock(
                return_value={"tempids-to-uids": {"-1": "real-uid-123"}}
            )

            result = client.write_child_block("parent-uid", ["Content"], open=True)

            assert result == "real-uid-123"

            # Verify the open parameter was included
            call_args = client._write.call_args[0][0]
            assert call_args["actions"][0]["block"]["open"] is True

    def test_write_child_block_invalid_heading(self):
        """Test write_child_block with invalid heading raises ValueError."""
        with patch("readwise_local_plus.integrations.roam.fetch_user_config"):
            client = RoamClient()

            with pytest.raises(ValueError, match="Roam heading must be 1, 2, or 3"):
                client.write_child_block("parent-uid", ["Content"], heading=4)


class TestRoamBatchAction:
    """Test the RoamBatchAction class."""

    @patch("readwise_local_plus.integrations.roam.RoamClient")
    def test_init(self, mock_roam_client):
        """Test RoamBatchAction initialization."""
        batch_action = RoamBatchAction()

        assert hasattr(batch_action, "roam_client")
        assert hasattr(batch_action, "batch_action_body")
        assert batch_action.batch_action_body == {
            "action": "batch-actions",
            "actions": [],
        }

    def test_create_batch_action_body(self):
        """Test create_batch_action_body method."""
        with patch("readwise_local_plus.integrations.roam.RoamClient"):
            batch_action = RoamBatchAction()

            result = batch_action.create_batch_action_body()
            expected = {"action": "batch-actions", "actions": []}
            assert result == expected

    def test_append_a_child_block_action(self):
        """Test append_a_child_block_action method."""
        with patch("readwise_local_plus.integrations.roam.RoamClient"):
            batch_action = RoamBatchAction()
            batch_action.roam_client._get_temp_uid = Mock(return_value=-1)

            temp_uid = batch_action.append_a_child_block_action("parent-uid", "Content")

            assert temp_uid == -1
            assert len(batch_action.batch_action_body["actions"]) == 1

            action = batch_action.batch_action_body["actions"][0]
            expected_action = {
                "action": "create-block",
                "location": {"order": "last", "parent-uid": "parent-uid"},
                "block": {"string": "Content", "uid": -1},
            }
            assert action == expected_action

    def test_append_a_child_block_action_with_heading(self):
        """Test append_a_child_block_action with heading."""
        with patch("readwise_local_plus.integrations.roam.RoamClient"):
            batch_action = RoamBatchAction()
            batch_action.roam_client._get_temp_uid = Mock(return_value=-2)

            temp_uid = batch_action.append_a_child_block_action(
                "parent-uid", "Header", heading=1
            )

            assert temp_uid == -2

            action = batch_action.batch_action_body["actions"][0]
            assert action["block"]["heading"] == 1

    def test_append_a_child_block_action_with_open(self):
        """Test append_a_child_block_action with open parameter."""
        with patch("readwise_local_plus.integrations.roam.RoamClient"):
            batch_action = RoamBatchAction()
            batch_action.roam_client._get_temp_uid = Mock(return_value=-3)

            temp_uid = batch_action.append_a_child_block_action(
                "parent-uid", "Content", open=True
            )

            assert temp_uid == -3

            action = batch_action.batch_action_body["actions"][0]
            assert action["block"]["open"] is True

    def test_append_a_child_block_action_invalid_heading(self):
        """Test append_a_child_block_action with invalid heading."""
        with patch("readwise_local_plus.integrations.roam.RoamClient"):
            batch_action = RoamBatchAction()

            with pytest.raises(ValueError, match="Roam heading must be 1, 2, or 3"):
                batch_action.append_a_child_block_action(
                    "parent-uid", "Content", heading=5
                )

    def test_append_multiple_actions(self):
        """Test appending multiple actions."""
        with patch("readwise_local_plus.integrations.roam.RoamClient"):
            batch_action = RoamBatchAction()
            batch_action.roam_client._get_temp_uid = Mock(side_effect=[-1, -2, -3])

            uid1 = batch_action.append_a_child_block_action("parent1", "Content1")
            uid2 = batch_action.append_a_child_block_action("parent2", "Content2")
            uid3 = batch_action.append_a_child_block_action("parent3", "Content3")

            assert uid1 == -1
            assert uid2 == -2
            assert uid3 == -3
            assert len(batch_action.batch_action_body["actions"]) == 3

    def test_execute_batch_action(self):
        """Test execute_batch_action method."""
        with patch("readwise_local_plus.integrations.roam.RoamClient"):
            batch_action = RoamBatchAction()

            mock_response = {
                "tempids-to-uids": {"-1": "real-uid-1", "-2": "real-uid-2"}
            }
            batch_action.roam_client._write = Mock(return_value=mock_response)

            result = batch_action.execute_batch_action()

            batch_action.roam_client._write.assert_called_once_with(
                batch_action.batch_action_body
            )
            assert result == {"-1": "real-uid-1", "-2": "real-uid-2"}

    def test_execute_batch_action_no_response(self):
        """Test execute_batch_action with no response."""
        with patch("readwise_local_plus.integrations.roam.RoamClient"):
            batch_action = RoamBatchAction()
            batch_action.roam_client._write = Mock(return_value=None)

            result = batch_action.execute_batch_action()
            assert result is None
