import argparse
import sys
from unittest.mock import MagicMock, Mock, patch

import pytest

from readwise_local_plus.cli import main, parse_args


@pytest.mark.parametrize(
    "passed_args, expected_datetime_str, expected_log",
    [
        ("rw rw-api --datetime 2024-01-01T00:00Z", "2024-01-01T00:00Z", False),
        ("rw rw-api -d 2024-01-01T00:00Z", "2024-01-01T00:00Z", False),
        ("rw rw-api -d 2024-01-01T00:00Z --log-output", "2024-01-01T00:00Z", True),
        ("rw rw-api -d 2024-01-01T00:00Z -l", "2024-01-01T00:00Z", True),
    ],
)
def test_parse_args_for_readwise_api_subparser(
    passed_args, expected_datetime_str, expected_log
):
    sys.argv = passed_args.split(" ")
    actual = parse_args()
    assert actual.command == "rw-api"
    assert actual.datetime == expected_datetime_str
    assert actual.log_output is expected_log


def test_parse_args_default_value_for_sync():
    sys.argv = ["rw", "sync"]
    actual = parse_args()
    assert actual.command == "sync"
    # This will result in --delta being called.
    assert actual.all is False


def test_version_flag_exits_and_prints_version(capsys):
    with pytest.raises(SystemExit):
        sys.argv = ["", "--version"]
        parse_args()

    captured = capsys.readouterr()
    assert "Readwise Local Plus" in captured.out


@pytest.mark.parametrize(
    "passed_sub_arg, expected_delta, expected_all",
    [
        ("rw sync --delta", True, False),
        ("rw sync --all", False, True),
        ("rw sync", False, False),
    ],
)
def test_parse_args_sync_subparser(passed_sub_arg, expected_delta, expected_all):
    sys.argv = passed_sub_arg.split(" ")
    actual = parse_args()
    assert actual.delta is expected_delta
    assert actual.all is expected_all


@pytest.mark.parametrize(
    "passed_args, expected_command",
    [
        (["rw", "sync"], "sync"),
        (["rw", "list-invalids"], "list-invalids"),
        (["rw", "e2e-data"], "e2e-data"),
    ],
)
def test_parse_args_main_command(passed_args, expected_command):
    sys.argv = passed_args
    actual = parse_args()
    assert isinstance(actual, argparse.Namespace)
    assert actual.command == expected_command


@pytest.mark.parametrize(
    "command, expected_value",
    [
        # (True, None),
        (False, "ISO 8601 datetime string")
    ],
)
@patch("readwise_local_plus.cli.check_database")
@patch("readwise_local_plus.cli.parse_args")
@patch("readwise_local_plus.cli.run_pipeline_flattened_objects")
def test_cli_main_sync(
    mock_run_pipeline: MagicMock,
    mock_parse_args: MagicMock,
    mock_check_database: MagicMock,
    command: bool,
    expected_value: bool,
):
    mock_user_config = Mock()

    mocked_parsed_args = Mock()
    mocked_parsed_args.command = "sync"
    mocked_parsed_args.all = command
    mock_parse_args.return_value = mocked_parsed_args

    breakpoint()

    mock_check_database.return_value = expected_value

    main(mock_user_config)

    mock_parse_args.assert_called_once()

    if not command:
        mock_check_database.assert_called_once_with(mock_user_config)
    else:
        mock_check_database.assert_not_called()

    mock_run_pipeline.assert_called_once_with(
        mock_user_config, last_fetch=expected_value
    )


@patch("readwise_local_plus.cli.parse_args")
@patch("readwise_local_plus.cli.list_invalid_db_objects")
def test_cli_main_list_invalids(mock_func: MagicMock, mock_parse_args: MagicMock):
    mocked_parsed_args = Mock()
    # Mock the sync command with either --delta or None defaulting to --delta.
    mocked_parsed_args.command = "list-invalids"
    mock_parse_args.return_value = mocked_parsed_args

    mock_user_config = Mock()

    main(mock_user_config)

    mock_func.assert_called_once_with(mock_user_config)
