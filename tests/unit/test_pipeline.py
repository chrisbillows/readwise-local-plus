from datetime import datetime
from typing import Any, Callable
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel

from readwise_local_plus.pipeline import (
    datetime_to_isoformat_str,
    fetch_books_with_highlights,
    flatten_books_with_highlights,
    run_pipeline_flattened_objects,
    update_database_flattened_objects,
    validate_flattened_objects,
    validate_nested_objects,
    validation_add_initial_validation_status,
    validation_ensure_field_is_a_list,
    validation_ensure_highlight_has_correct_book_id,
)
from tests.helpers import mock_api_response


@pytest.fixture()
def mock_run_pipeline_flattened_objs() -> tuple[dict, Any]:
    # Strings are used as simplified return values. They are not the real return types.
    mock_session = MagicMock()
    mocks = {
        "mock_get_session": MagicMock(return_value=mock_session),
        "mock_fetch_books_with_highlights": MagicMock(
            return_value=("raw_data", "start", "end")
        ),
        "mock_validate_nested_objects": MagicMock(
            return_value="nested_objs_with_validation_status"
        ),
        "mock_flatten_books_with_highlights": MagicMock(
            return_value={
                "books": "book_data_dicts",
                "book_tags": "book_tags_dicts",
                "highlights": "highlights_dicts",
                "highlight_tags": "highlight_tags_dicts",
            }
        ),
        "mock_validate_flattened_objects": MagicMock(
            return_value={"obj_name": "objs_with_final_validation_status"}
        ),
        "mock_update_database_flattened_objects": MagicMock(return_value="1"),
    }
    actual = run_pipeline_flattened_objects(
        user_config=MagicMock(DB="db"),
        get_session_func=mocks["mock_get_session"],
        fetch_func=mocks["mock_fetch_books_with_highlights"],
        validate_nested_objs_func=mocks["mock_validate_nested_objects"],
        flatten_func=mocks["mock_flatten_books_with_highlights"],
        validate_flat_objs_func=mocks["mock_validate_flattened_objects"],
        update_db_func=mocks["mock_update_database_flattened_objects"],
    )
    return mocks, actual


def test_datetime_to_iso_format_str():
    date_time = datetime(2025, 4, 14, 20, 28, 21, 589651)
    expected = "2025-04-14T20:28:21.589651"
    actual = datetime_to_isoformat_str(date_time)
    assert actual == expected


@patch("readwise_local_plus.pipeline.datetime")
@patch("readwise_local_plus.pipeline.fetch_from_export_api")
@patch("readwise_local_plus.pipeline.datetime_to_isoformat_str")
def test_fetch_books_with_highlights_no_last_fetch(
    mock_str_to_iso_format: MagicMock,
    mock_fetch_from_export_api: MagicMock,
    mock_datetime: MagicMock,
):
    mock_api_response = ["book_with_hl"]
    mock_fetch_from_export_api.return_value = mock_api_response

    mock_start_new_fetch = datetime(2025, 1, 1, 1, 1, 1)
    mock_end_new_fetch = datetime(2025, 1, 1, 2, 2, 2)
    mock_datetime.now.side_effect = [mock_start_new_fetch, mock_end_new_fetch]

    last_fetch = None
    actual = fetch_books_with_highlights(last_fetch)

    mock_str_to_iso_format.assert_not_called()
    mock_datetime.now.assert_called()
    mock_fetch_from_export_api.assert_called_once_with(last_fetch)
    assert actual == (mock_api_response, mock_start_new_fetch, mock_end_new_fetch)


@patch("readwise_local_plus.pipeline.datetime")
@patch("readwise_local_plus.pipeline.fetch_from_export_api")
def test_fetch_books_with_highlights_last_fetch_exists(
    mock_fetch_from_export_api: MagicMock,
    mock_datetime: MagicMock,
):
    mock_api_response = ["book_with_hl"]
    mock_fetch_from_export_api.return_value = mock_api_response

    mock_start_new_fetch = datetime(2025, 1, 1, 2, 2, 2)
    mock_end_new_fetch = datetime(2025, 1, 1, 3, 3, 3)
    mock_datetime.now.side_effect = [mock_start_new_fetch, mock_end_new_fetch]

    last_fetch = datetime(2025, 1, 1, 1, 1, 1)
    last_fetch_iso_string = "2025-01-01T01:01:01"

    actual = fetch_books_with_highlights(last_fetch)

    mock_datetime.now.assert_called()
    mock_fetch_from_export_api.assert_called_once_with(last_fetch_iso_string)

    assert actual == (mock_api_response, mock_start_new_fetch, mock_end_new_fetch)


@pytest.mark.parametrize(
    "mock_obj, expected",
    [
        (
            {"mock_field": [1, 2, 3], "validated": True, "validation_errors": {}},
            {"mock_field": [1, 2, 3], "validated": True, "validation_errors": {}},
        ),
        (
            {"validated": True, "validation_errors": {}},
            {
                "mock_field": [],
                "validated": False,
                "validation_errors": {
                    "mock_field": "Field not found in test_obj. (Empty list added instead)."
                },
            },
        ),
        (
            {"mock_field": 123, "validated": True, "validation_errors": {}},
            {
                "mock_field": [],
                "validated": False,
                "validation_errors": {
                    "mock_field": "Field not a list in test_obj. Passed value not stored. Value: "
                    "123. (Empty list added instead)."
                },
            },
        ),
    ],
)
def test_validation_ensure_field_is_a_list(
    mock_obj: dict[str, Any], expected: dict[str, Any]
):
    validation_ensure_field_is_a_list(mock_obj, "mock_field", "test_obj")
    assert mock_obj == expected


@pytest.mark.parametrize(
    "mock_highlight, expected",
    [
        (
            {"book_id": 1, "validation_errors": {}, "validated": True},
            {"book_id": 1, "validation_errors": {}, "validated": True},
        ),
        (
            {"book_id": 2, "validation_errors": {}, "validated": True},
            {
                "book_id": 1,
                "validated": False,
                "validation_errors": {
                    "book_id": "Highlight book_id 2 does not match book user_book_id 1"
                },
            },
        ),
    ],
)
def test_validation_ensure_highlight_has_correct_book_id(
    mock_highlight: dict[str, Any], expected: dict[str, Any]
):
    validation_ensure_highlight_has_correct_book_id(mock_highlight, 1)
    assert mock_highlight == expected


@pytest.mark.parametrize(
    "mock_obj, expected",
    [
        (
            {
                "title": "book_1",
                "highlights": [
                    {
                        "id": 2,
                        "tags": [{"id": 3}],
                    }
                ],
            },
            {
                "title": "book_1",
                "highlights": [
                    {
                        "id": 2,
                        "tags": [
                            {
                                "id": 3,
                                "validated": True,
                                "validation_errors": {},
                            }
                        ],
                        "validated": True,
                        "validation_errors": {},
                    }
                ],
                "validated": True,
                "validation_errors": {},
            },
        ),
        (
            {"id": 1, "tags": [{"id": 2}]},
            {
                "id": 1,
                "tags": [
                    {
                        "id": 2,
                        "validated": True,
                        "validation_errors": {},
                    }
                ],
                "validated": True,
                "validation_errors": {},
            },
        ),
        (
            {
                "title": "book_1",
                "book_tags": [{"id": 1}],
                "highlights": [
                    {
                        "id": 2,
                        "tags": [{"id": 3}],
                    }
                ],
            },
            {
                "title": "book_1",
                "book_tags": [
                    {
                        "id": 1,
                        "validated": True,
                        "validation_errors": {},
                    }
                ],
                "highlights": [
                    {
                        "id": 2,
                        "tags": [
                            {
                                "id": 3,
                                "validated": True,
                                "validation_errors": {},
                            }
                        ],
                        "validated": True,
                        "validation_errors": {},
                    }
                ],
                "validated": True,
                "validation_errors": {},
            },
        ),
    ],
    ids=["mock_book_and_hl", "single_mock_highlight", "mock_full_book"],
)
def test_validation_add_initial_validation_status(
    mock_obj: dict[str, Any], expected: dict[str, Any]
):
    actual = validation_add_initial_validation_status(mock_obj)
    assert actual == expected


def test_validate_nested_objects_for_all_valid_objects():
    mock_raw_books = [
        {
            "user_book_id": 123,
            "book_tags": [{"id": 1, "name": "tag1"}],
            "highlights": [{"book_id": 123, "tags": [{"id": 10, "name": "tag1"}]}],
        }
    ]

    expected = [
        {
            "user_book_id": 123,
            "book_tags": [
                {"id": 1, "name": "tag1", "validated": True, "validation_errors": {}}
            ],
            "highlights": [
                {
                    "book_id": 123,
                    "tags": [
                        {
                            "id": 10,
                            "name": "tag1",
                            "validated": True,
                            "validation_errors": {},
                        }
                    ],
                    "validated": True,
                    "validation_errors": {},
                }
            ],
            "validated": True,
            "validation_errors": {},
        }
    ]
    actual = validate_nested_objects(mock_raw_books)
    assert actual == expected


@pytest.mark.parametrize(
    "mock_raw_books, expected",
    [
        (
            [
                {
                    "user_book_id": 1,
                }
            ],
            [
                {
                    "user_book_id": 1,
                    "book_tags": [],
                    "highlights": [],
                    "validated": False,
                    "validation_errors": {
                        "highlights": "Field not found in book. (Empty list added instead).",
                        "book_tags": "Field not found in book. (Empty list added instead).",
                    },
                },
            ],
        ),
        (
            [
                {
                    "user_book_id": 1,
                    "highlights": [{"book_id": 2}],
                }
            ],
            [
                {
                    "user_book_id": 1,
                    "book_tags": [],
                    "highlights": [
                        {
                            "book_id": 1,
                            "tags": [],
                            "validated": False,
                            "validation_errors": {
                                "book_id": "Highlight book_id 2 does not "
                                "match book user_book_id 1",
                                "tags": "Field not found in highlight. (Empty list "
                                "added instead).",
                            },
                        }
                    ],
                    "validated": False,
                    "validation_errors": {
                        "book_tags": "Field not found in book. (Empty list added "
                        "instead).",
                    },
                },
            ],
        ),
        (
            [
                {
                    "user_book_id": 2,
                    "book_tags": "I am a string",
                    "highlights": [{"book_id": 2, "tags": [{"id": 1, "name": "tag"}]}],
                }
            ],
            [
                {
                    "user_book_id": 2,
                    "book_tags": [],
                    "highlights": [
                        {
                            "book_id": 2,
                            "tags": [
                                {
                                    "id": 1,
                                    "name": "tag",
                                    "validated": True,
                                    "validation_errors": {},
                                }
                            ],
                            "validated": True,
                            "validation_errors": {},
                        }
                    ],
                    "validated": False,
                    "validation_errors": {
                        "book_tags": "Field not a list in book. Passed value not stored. Value: "
                        "I am a string. (Empty list added instead).",
                    },
                },
            ],
        ),
    ],
)
def test_validate_nested_objects_for_sample_of_invalid_objects(
    mock_raw_books, expected
):
    actual = validate_nested_objects(mock_raw_books)
    assert actual == expected


@pytest.mark.parametrize("test_with_validated_keys_present", [True, False])
def test_flatten_books_with_highlights(test_with_validated_keys_present: bool):
    mock_api_response_data = mock_api_response()
    expected = {
        "books": [
            {
                "user_book_id": 12345,
                "title": "book title",
                "is_deleted": False,
                "author": "name surname",
                "readable_title": "Book Title",
                "source": "web_clipper",
                "cover_image_url": "https://link/to/image",
                "unique_url": "http://the.source.url.ai",
                "summary": None,
                "category": "books",
                "document_note": "A note added in Readwise Reader",
                "readwise_url": "https://readwise.io/bookreview/12345",
                "source_url": "http://the.source.url.ai",
                "asin": None,
                "external_id": None,
            }
        ],
        "book_tags": [{"id": 6969, "name": "arch_btw", "user_book_id": 12345}],
        "highlights": [
            {
                "id": 10,
                "text": "The highlight text",
                "location": 1000,
                "location_type": "location",
                "note": "document note",
                "color": "yellow",
                "highlighted_at": "2025-01-01T00:01:00Z",
                "created_at": "2025-01-01T00:01:10Z",
                "updated_at": "2025-01-01T00:01:20Z",
                "external_id": None,
                "end_location": None,
                "url": None,
                "book_id": 12345,
                "is_favorite": False,
                "is_discard": True,
                "is_deleted": False,
                "readwise_url": "https://readwise.io/open/10",
            }
        ],
        "highlight_tags": [{"id": 97654, "name": "favorite", "highlight_id": 10}],
    }

    # Add validated keys to input and expected data. Function not expected to care if
    # the data has validation keys or not.
    if test_with_validated_keys_present:

        def add_validation_fields_recursive(obj):
            if isinstance(obj, dict):
                obj["validated"] = True
                obj["validation_errors"] = []
                for value in obj.values():
                    add_validation_fields_recursive(value)
            elif isinstance(obj, list):
                for item in obj:
                    add_validation_fields_recursive(item)

        add_validation_fields_recursive(mock_api_response_data)
        add_validation_fields_recursive(expected)
        # Remove unneeded keys.
        del expected["validated"]
        del expected["validation_errors"]

    actual = flatten_books_with_highlights(mock_api_response_data)

    assert actual == expected


def test_validate_flattened_objects():
    class MockUnnestedSchema(BaseModel, extra="forbid", strict=True):
        id: int
        title: str

    schemas = {"mock_obj": MockUnnestedSchema}

    # --- The test isn't parametrized to test multiple simultaneous values ---
    # id 1 is valid.
    # id 2 has an invalid id type.
    # id 3 was previously invalid, but has no issue in this validation layer.
    # id 4 was previously invalid, and also has an invalid id type.
    mock_flattened_api_data = {
        "mock_obj": [
            {"id": 1, "title": "title_1", "validated": True, "validation_errors": {}},
            {"id": "2", "title": "title_2", "validated": True, "validation_errors": {}},
            {
                "id": 3,
                "title": "invalid_1",
                "validated": False,
                "validation_errors": {"title": "title is invalid"},
            },
            {
                "id": "4",
                "title": "invalid_2",
                "validated": False,
                "validation_errors": {"title": "title is invalid"},
            },
        ]
    }
    actual = validate_flattened_objects(mock_flattened_api_data, schemas)
    expected = {
        "mock_obj": [
            {"id": 1, "title": "title_1", "validated": True, "validation_errors": {}},
            {
                "id": "2",
                "title": "title_2",
                "validated": False,
                "validation_errors": {"id": "Input should be a valid integer"},
            },
            {
                "id": 3,
                "title": "invalid_1",
                "validated": False,
                "validation_errors": {"title": "title is invalid"},
            },
            {
                "id": "4",
                "title": "invalid_2",
                "validated": False,
                "validation_errors": {
                    "title": "title is invalid",
                    "id": "Input should be a valid integer",
                },
            },
        ]
    }
    assert actual == expected


@patch("readwise_local_plus.pipeline.DatabasePopulaterFlattenedData")
def test_update_database_flattened_objects(mock_db_populater_flattened_data: MagicMock):
    mock_instance = mock_db_populater_flattened_data.return_value

    update_database_flattened_objects("session", "data", "start", "end")

    mock_db_populater_flattened_data.assert_called_once_with(
        "session", "data", "start", "end"
    )
    mock_instance.populate_database.assert_called_once_with()


@pytest.mark.parametrize(
    "mock_name, assertion",
    [
        ("mock_get_session", lambda m: m.assert_called_once()),
        # `Any` avoids passing in mock_user_config from mock_run_pipeline fixture.
        (
            "mock_fetch_books_with_highlights",
            lambda m: m.assert_called_once_with(None),
        ),
        (
            "mock_validate_nested_objects",
            lambda m: m.assert_called_once_with("raw_data"),
        ),
        (
            "mock_flatten_books_with_highlights",
            lambda m: m.assert_called_once_with("nested_objs_with_validation_status"),
        ),
        (
            "mock_validate_flattened_objects",
            lambda m: m.assert_called_once_with(
                {
                    "books": "book_data_dicts",
                    "book_tags": "book_tags_dicts",
                    "highlights": "highlights_dicts",
                    "highlight_tags": "highlight_tags_dicts",
                }
            ),
        ),
        ("mock_update_database_flattened_objects", lambda m: m.assert_called_once()),
    ],
)
def test_run_pipeline_flattened_objects_function_calls(
    mock_name: str,
    assertion: Callable,
    mock_run_pipeline_flattened_objs: tuple[dict, Any],
):
    mocks, run_pipeline_return_value = mock_run_pipeline_flattened_objs
    assertion(mocks[mock_name])


def test_run_pipeline_flattened_objects_return_value(
    mock_run_pipeline_flattened_objs: tuple[dict, Any],
):
    mocks, run_pipeline_return_value = mock_run_pipeline_flattened_objs
    assert run_pipeline_return_value == "1"
