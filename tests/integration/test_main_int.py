from typing import Any

import pytest

from readwise_local_plus.pipeline import validate_nested_objects
from tests.helpers import mock_api_response


def mock_api_with_initial_validation_status() -> dict[str, Any]:
    """
    Return a mock valid book with initial validation fields added.

    Each nested object is a mock Readwise object and all objects have the validation
    fields added e.g. `"validated": True, "validation_errors": {}`

    Returns
    -------
    dict[str, Any]
        A mock readwise book with nested objects, with each object having had validation
        fields added.
    """
    added_validation_fields = mock_api_response()[0]
    added_validation_fields["validated"] = True
    added_validation_fields["validation_errors"] = {}

    added_validation_fields["book_tags"][0]["validated"] = True
    added_validation_fields["book_tags"][0]["validation_errors"] = {}

    added_validation_fields["highlights"][0]["validated"] = True
    added_validation_fields["highlights"][0]["validation_errors"] = {}

    added_validation_fields["highlights"][0]["tags"][0]["validated"] = True
    added_validation_fields["highlights"][0]["tags"][0]["validation_errors"] = {}

    return added_validation_fields


def create_invalid_readwise_objects_for_testing() -> dict[
    str, tuple[list[dict[str, Any]], list[dict[str, Any]]]
]:
    """
    Create a list of nested objects to test the validation functions.

    Each object is a dictionary with the following structure:
    ```
    {
        "reason_obj_is_invalid" :
            (
                {mock obj that is invalid in some way},
                {mock obj 'expected' result after validation}
            )
    }
    ```
    The mock object is created by a function that mutates the mock_api_response book
    dict.  The 'expected' result is created by a function that mutates the
    mock_api_response after it has had initial validation fields manually added. (It is
    decoupled from any other validation functionality).

    Returns
    -------
    dict[str, dict[str, tuple[list[dict[str, Any]]], list[dict[str, Any]]]
        A dictionary where each key is a descriptor of the test object and each value is
        a tuple containing the mock object and the expected post validation result.
    """

    def modify_mock_api_response(modify: callable):
        """
        Modify the mock_api_response book.

        Use to create invalid objects for testing.

        Parameters
        ----------
        modify: Callable
            A function to mutate the mock_api_response book.
            E.g `lambda b: `b['field'] = "some value"
        """
        obj = mock_api_response()[0]
        modify(obj)
        return obj

    def modify_mock_api_response_with_initial_validation_status(modify):
        """
        Modify the mock_api_response book to which validated fields are already added.

        Use to create 'expected' post-validation values.

        Parameters
        ----------
        modify: Callable
            A function to mutate the mock_api_response book.
            E.g `lambda b: `b['field'] = "some value"
        """
        obj = mock_api_with_initial_validation_status()
        modify(obj)
        return obj

    return {
        "valid_everything": (
            [modify_mock_api_response(lambda b: None)],
            [mock_api_with_initial_validation_status()],
        ),
        "missing_highlights": (
            [modify_mock_api_response(lambda b: b.pop("highlights"))],
            [
                modify_mock_api_response_with_initial_validation_status(
                    lambda b: b.update(
                        {
                            "highlights": [],
                            "validated": False,
                            "validation_errors": {
                                "highlights": "Field not found in book. (Empty list added "
                                "instead)."
                            },
                        }
                    )
                )
            ],
        ),
        "missing_book_tags": (
            [modify_mock_api_response(lambda b: b.pop("book_tags"))],
            [
                modify_mock_api_response_with_initial_validation_status(
                    lambda b: b.update(
                        {
                            "book_tags": [],
                            "validated": False,
                            "validation_errors": {
                                "book_tags": "Field not found in book. (Empty list added "
                                "instead)."
                            },
                        }
                    )
                )
            ],
        ),
        "missing_book_tags_and_highlights": (
            [
                modify_mock_api_response(
                    lambda b: b.pop("book_tags", b.pop("highlights"))
                )
            ],
            [
                modify_mock_api_response_with_initial_validation_status(
                    lambda b: b.update(
                        {
                            "book_tags": [],
                            "highlights": [],
                            "validated": False,
                            "validation_errors": {
                                "book_tags": "Field not found in book. (Empty list added "
                                "instead).",
                                "highlights": "Field not found in book. (Empty list added "
                                "instead).",
                            },
                        }
                    )
                )
            ],
        ),
        "invalid_highlight_tags": (
            [modify_mock_api_response(lambda b: b["highlights"][0].pop("tags"))],
            [
                modify_mock_api_response_with_initial_validation_status(
                    lambda b: b["highlights"][0].update(
                        {
                            "tags": [],
                            "validated": False,
                            "validation_errors": {
                                "tags": "Field not found in highlight. (Empty list added "
                                "instead).",
                            },
                        }
                    )
                )
            ],
        ),
        "invalid_book_id": (
            [
                modify_mock_api_response(
                    lambda b: b["highlights"][0].update({"book_id": 99999})
                )
            ],
            [
                modify_mock_api_response_with_initial_validation_status(
                    lambda b: b["highlights"][0].update(
                        {
                            "validated": False,
                            "validation_errors": {
                                "book_id": "Highlight book_id 99999 does not match book"
                                " user_book_id 12345",
                            },
                        }
                    )
                )
            ],
        ),
    }


@pytest.mark.parametrize(
    "mock_obj, expected",
    create_invalid_readwise_objects_for_testing().values(),
    ids=create_invalid_readwise_objects_for_testing().keys(),
)
def test_integration_of_nested_obj_validation_functions(
    mock_obj: dict[str, Any], expected: dict[str, Any]
):
    actual = validate_nested_objects(mock_obj)
    assert actual == expected
