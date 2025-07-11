from datetime import datetime
from typing import Any, Union

import pytest
from pydantic import ValidationError

from readwise_local_plus.pipeline import SCHEMAS_BY_OBJECT
from readwise_local_plus.schemas import (
    BookSchemaUnnested,
    BookTagsSchema,
    HighlightSchemaUnnested,
    HighlightTagsSchema,
)
from tests.helpers import flat_mock_api_response_nested_validated

# ----------------
# Helper Functions
# ----------------


def flat_objects_api_fields_only() -> dict[str, list[dict[str, Any]]]:
    """
    Extract only the API fields from an flattened API response that is nested validated.

    Pydantic validation is only carried out on the API fields. Replicate that content
    for testing pydantic schema.

    Returns
    -------
    dict[str, list[dict[str, Any]]]
        A dictionary where keys are object types and values are lists of objects: one
        object per object type.
    """
    flattened_nested_validated_data = flat_mock_api_response_nested_validated()
    objs_with_only_api_fields = {}
    for obj_type, objs in flattened_nested_validated_data.items():
        obj_schema = SCHEMAS_BY_OBJECT[obj_type]
        for obj in objs:
            obj_with_api_fields_only = {
                k: v for k, v in obj.items() if k in obj_schema.model_fields.keys()
            }
            objs_with_only_api_fields[obj_type] = obj_with_api_fields_only
    return objs_with_only_api_fields


def expected_type_per_schema_field() -> dict[str, dict[str, list[str]]]:
    """
    A dictionary grouping schema fields by expected type and by schema object.

    Used for dynamically generating test cases. Use a function rather than a constant
    to ensure test isolation.

    Returns
    -------
    dict[str, dict[str, list[str]]]
        Nested dictionary in the form ``{"object_name": {"expected_type": [field,
        field ...]}}``.
    """
    return {
        "books": {
            "string": [
                "title",
                "author",
                "readable_title",
                "source",
                "summary",
                "document_note",
                "cover_image_url",
                "readwise_url",
                "source_url",
                "unique_url",
            ],
            "int": ["user_book_id"],
            "choice_category": ["category"],
            "asin": ["asin"],
            "bool": ["is_deleted"],
        },
        "highlights": {
            "string": [
                "text",
                "location_type",
                "note",
                "external_id",
                "url",
                "readwise_url",
            ],
            "int": ["id", "location", "end_location", "book_id"],
            "bool": ["is_favorite", "is_discard", "is_deleted"],
            "iso_string": ["highlighted_at", "created_at", "updated_at"],
            "choice_color": ["color"],
        },
        "book_tags": {"int": ["id"], "string": ["name"]},
        "highlight_tags": {"int": ["id"], "string": ["name"]},
    }


def generate_invalid_types_test_cases() -> list[tuple[str, Union[str, int], str]]:
    """
    Generate parametrized test cases to check the configuration of invalid values.

    Returns
    -------
    list[tuple[str, Union[str, int], str]]
        A list of test cases where each test case is a tuple in the form ``(obj, field,
        invalid_value)``.
    """
    invalid_values = {
        "string": [123, [123], [], ["a"], {}],
        "int": ["a", "123", [], ["a", "b"], {}],
        "choice_category": [],
        "asin": ["a", 1, "1a2b3c4d"],
        "choice_color": [123, [123], [], ["a"], {}],
        "iso_string": [],
        "bool": [0, 1, "a", [], ["a"], {}],
        "list_of_tags": [123, "abc", [{"a": 1, "b": 2}]],
        "list_of_highlights": [123, "abc", [{"a": 1, "b": 2}]],
    }

    test_cases = []
    for obj, field_group in expected_type_per_schema_field().items():
        for expected_type, fields in field_group.items():
            for field in fields:
                for invalid_value in invalid_values[expected_type]:
                    test_cases.append((obj, field, invalid_value))
    return test_cases


def generate_field_nullability_test_cases() -> dict[str, list[tuple]]:
    """
    Generate parametrized test cases to check field nullability configurations.

    Returns
    -------
    dict[str[list[tuple]]]
        A dictionary with the keys ``error`` and ``pass``. The values for each are a
        list of test cases in the form ``(obj, field)``.
    """
    non_nullable_fields = {
        "books": [
            "user_book_id",
            "title",
            "readable_title",
            "category",
            "readwise_url",
            "highlights",
        ],
        "highlights": ["id", "text", "book_id"],
        "highlight_tags": [],
        "book_tags": [],
    }
    nullable_test_cases = {"pass": [], "error": []}
    for obj, schema in SCHEMAS_BY_OBJECT.items():
        for field in schema.model_fields.keys():
            if field in non_nullable_fields[obj]:
                nullable_test_cases["error"].append((obj, field))
            else:
                nullable_test_cases["pass"].append((obj, field))
    return nullable_test_cases


# --------------------------
# Tests for Helper Functions
# --------------------------


@pytest.mark.parametrize(
    "object_type", ["books", "book_tags", "highlights", "highlight_tags"]
)
def test_fields_in_expected_type_per_schema_match_object_schema(object_type: str):
    book_fields = SCHEMAS_BY_OBJECT[object_type].model_fields
    book_fields_expected_types_dict = []
    for list_of_fields in expected_type_per_schema_field()[object_type].values():
        book_fields_expected_types_dict.extend(list_of_fields)
    assert sorted(book_fields) == sorted(book_fields_expected_types_dict)


def test_generate_invalid_field_values_test_cases():
    test_cases = generate_invalid_types_test_cases()
    assert test_cases[0] == ("books", "title", 123)


def test_generate_field_nullability_test_cases():
    test_cases = generate_field_nullability_test_cases()
    assert list(test_cases.keys()) == ["pass", "error"]
    assert test_cases["pass"][0] == ("books", "is_deleted")
    assert test_cases["pass"][1] == ("books", "author")
    assert test_cases["error"][0] == ("books", "user_book_id")


# -----
# Tests
# -----


@pytest.mark.parametrize(
    "object_type", ["books", "book_tags", "highlights", "highlight_tags"]
)
def test_flat_schema_configuration_by_object(object_type: str):
    schema = SCHEMAS_BY_OBJECT[object_type]
    test_object = flat_objects_api_fields_only()[object_type]
    assert schema(**test_object)


@pytest.mark.parametrize(
    "object_type, expected",
    [
        (
            "books",
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
            },
        ),
        ("book_tags", {"id": 6969, "name": "arch_btw"}),
        (
            "highlights",
            {
                "id": 10,
                "text": "The highlight text",
                "location": 1000,
                "location_type": "location",
                "note": "document note",
                "color": "yellow",
                "highlighted_at": datetime(2025, 1, 1, 0, 1),
                "created_at": datetime(2025, 1, 1, 0, 1, 10),
                "updated_at": datetime(2025, 1, 1, 0, 1, 20),
                "external_id": None,
                "end_location": None,
                "url": None,
                "book_id": 12345,
                "is_favorite": False,
                "is_discard": True,
                "is_deleted": False,
                "readwise_url": "https://readwise.io/open/10",
            },
        ),
        ("highlight_tags", {"id": 97654, "name": "favorite"}),
    ],
)
def test_flat_schema_model_dump_output(object_type: str, expected: dict[str, Any]):
    schema = SCHEMAS_BY_OBJECT[object_type]
    test_object = flat_objects_api_fields_only()[object_type]
    test_object_as_schema = schema(**test_object)
    model_dump = test_object_as_schema.model_dump()
    assert model_dump == expected


@pytest.mark.parametrize(
    "object_type, target_field, invalid_value",
    generate_invalid_types_test_cases(),
)
def test_flat_schema_configuration_with_invalid_values(
    object_type: str,
    target_field: str,
    invalid_value: Any,
):
    object_under_test = flat_objects_api_fields_only()[object_type]
    object_under_test[target_field] = invalid_value
    schema = SCHEMAS_BY_OBJECT[object_type]
    with pytest.raises(ValidationError):
        schema(**object_under_test)


@pytest.mark.parametrize(
    "object_type, field_to_null", generate_field_nullability_test_cases()["pass"]
)
def test_flat_schema_configuration_fields_allow_null(
    object_type: str,
    field_to_null: str,
):
    object_under_test = flat_objects_api_fields_only()[object_type]
    object_under_test[field_to_null] = None
    schema = SCHEMAS_BY_OBJECT[object_type]
    assert schema(**object_under_test)


@pytest.mark.parametrize(
    "object_type, field_to_null", generate_field_nullability_test_cases()["error"]
)
def test_flat_schema_configuration_fields_error_for_null(
    object_type: str,
    field_to_null: str,
):
    object_under_test = flat_objects_api_fields_only()[object_type]
    object_under_test[field_to_null] = None
    schema = SCHEMAS_BY_OBJECT[object_type]
    with pytest.raises(ValidationError):
        schema(**object_under_test)


@pytest.mark.parametrize(
    "field_to_remove", flat_objects_api_fields_only()["books"].keys()
)
def test_missing_book_fields_raise_errors(field_to_remove: str):
    mock_book = flat_objects_api_fields_only()["books"]
    del mock_book[field_to_remove]
    with pytest.raises(ValidationError):
        BookSchemaUnnested(**mock_book)


@pytest.mark.parametrize(
    "field_to_remove", flat_objects_api_fields_only()["highlights"].keys()
)
def test_missing_highlight_fields_raise_errors(field_to_remove: str):
    mock_highlight = flat_objects_api_fields_only()["highlights"]
    del mock_highlight[field_to_remove]
    with pytest.raises(ValidationError):
        HighlightSchemaUnnested(**mock_highlight)


@pytest.mark.parametrize(
    "field_to_remove", flat_objects_api_fields_only()["book_tags"].keys()
)
def test_missing_book_tag_fields_do_not_raise_errors(field_to_remove: str):
    mock_book_tags = flat_objects_api_fields_only()["book_tags"]
    del mock_book_tags[field_to_remove]
    BookTagsSchema(**mock_book_tags)


@pytest.mark.parametrize(
    "field_to_remove",
    flat_objects_api_fields_only()["highlight_tags"].keys(),
)
def test_missing_highlight_tag_fields_do_not_raise_errors(field_to_remove: str):
    mock_highlight_tags = flat_objects_api_fields_only()["book_tags"]
    del mock_highlight_tags[field_to_remove]
    HighlightTagsSchema(**mock_highlight_tags)


@pytest.mark.parametrize("object_under_test", flat_objects_api_fields_only().keys())
def test_additional_object_field_raises_error(object_under_test: str):
    mock_obj = flat_objects_api_fields_only()[object_under_test]
    mock_obj["extra_field"] = None
    schema = SCHEMAS_BY_OBJECT[object_under_test]
    with pytest.raises(ValidationError):
        schema(**mock_obj)
