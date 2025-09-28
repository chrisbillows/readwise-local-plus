import logging
from datetime import datetime, timezone
from typing import Any, cast

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from readwise_local_plus.config import UserConfig
from readwise_local_plus.db_operations import (
    DatabasePopulaterFlattenedData,
    get_session,
    update_readwise_last_fetch,
)
from readwise_local_plus.integrations.readwise import fetch_from_export_api
from readwise_local_plus.models import ReadwiseBatch
from readwise_local_plus.schemas import (
    BookSchemaUnnested,
    BookTagsSchema,
    HighlightSchemaUnnested,
    HighlightTagsSchema,
)
from readwise_local_plus.types import (
    FetchFn,
    FlattenFn,
    SessionFn,
    UpdateDbFlatObjFn,
    ValidateFlatObjFn,
    ValidateNestedObjFn,
)

logger = logging.getLogger(__name__)


SCHEMAS_BY_OBJECT: dict[str, type[BaseModel]] = {
    "books": BookSchemaUnnested,
    "book_tags": BookTagsSchema,
    "highlights": HighlightSchemaUnnested,
    "highlight_tags": HighlightTagsSchema,
}


def datetime_to_isoformat_str(dt: datetime) -> str:
    """
    Convert a datetime object to an ISO 8601 string.

    This functions wraps the Pathlib method call for testability and to easily assess
    compatibility with Readwise Highlight Export API.

    Parameters
    ----------
    dt: datetime
        A valid datetime object.

    Returns
    -------
    str
        An ISO 8601 formatted datetime string E.g. '2024-11-09T10:15:38.428687'.
    """
    return dt.isoformat()


def fetch_books_with_highlights(
    last_fetch: None | datetime,
) -> tuple[list[dict[str, Any]], datetime, datetime]:
    """
    Runner for fetching Readwise Highlights from the Readwise API.

    Parameters
    ----------
    last_fetch: None | datetime
        A datetime object indicating the time highlights have previously been fetched
        up to.

    Returns
    -------
    tuple[list[dict[str, Any]], datetime, datetime]
        A tuple consisting of:
            - data: a list of dictionaries where each item is a book with highlights
            - start_new_fetch: start of the most recent fetch as a datetime
            - end_new_fetch: end of the most recent fetch as a datetime
    """
    last_fetch_str: str | None = None

    if last_fetch:
        last_fetch_str = datetime_to_isoformat_str(last_fetch)

    start_new_fetch = datetime.now(tz=timezone.utc)
    data = fetch_from_export_api(last_fetch_str)
    end_new_fetch = datetime.now(tz=timezone.utc)
    logger.info(f"Fetch contains highlights for {len(data)} books/articles/tweets etc.")
    return (data, start_new_fetch, end_new_fetch)


def validation_ensure_field_is_a_list(
    obj: dict[str, Any], field: str, parent_label: str
) -> None:
    """
    Ensure a field is a list. Fix if needed.

    If the field is missing or the field value is not a list, an empty list is added,
    "validation" is set to False and the field and an error are added to the
    "validation_errors" dict. The object is mutated in place.

    Parameters
    ----------
    obj: dict
        A dictionary-like object. Expected to have the field "validated" and the field
        "validation_errors" with a dict as it's value.
    field: str
        The field to check.
    parent_label: str
        A label for the parent object for error messages. E.g. "book" or "highlight".
    """
    if obj.get(field) is None:
        obj[field] = []
        obj["validation_errors"][field] = (
            f"Field not found in {parent_label}. (Empty list added instead)."
        )
        obj["validated"] = False
    elif not isinstance(obj[field], list):
        obj["validation_errors"][field] = (
            f"Field not a list in {parent_label}. Passed value not stored. Value: "
            f"{obj[field]}. (Empty list added instead)."
        )
        obj["validated"] = False
        obj[field] = []


def validation_ensure_highlight_has_correct_book_id(
    highlight: dict[str, Any], book_user_book_id: Any
) -> None:
    """
    Ensure highlight.book_id matches its parent book.user_book_id.

    If not, fix add "validation_errors" dict to highlight.

    Parameters
    --------
    highlight: dict[str, Any]
        A highlight obj.
    book_user_id: Any
        A book user id. It's expected to be an int but a value of any type is accepted.
    """
    if highlight.get("book_id") != book_user_book_id:
        highlight["validation_errors"]["book_id"] = (
            f"Highlight book_id {highlight.get('book_id')} does not match book "
            f"user_book_id {book_user_book_id}"
        )
        highlight["validated"] = False
        highlight["book_id"] = book_user_book_id


def validation_add_initial_validation_status(
    obj: dict[str, Any] | list[dict[str, Any]],
) -> dict[str, Any] | list[dict[str, Any]]:
    """
    Add initial validation fields to all objects nested in a given object.

    Ensure objects have consistent fields for mutation through validation checks.
    Validation checks are assumed to overwrite the "validated" field to False. Works on
    any level of nested or unnested objects.

    The method assumes the only dict-like objects are 'books', 'book_tags',
    'highlights', and 'highlight_tags' - all of which require validation fields. Lists
    are assumed to be lists of these objects.

    Parameters
    ----------
    obj: list | dict
        A list or dictionary-like object.

    Returns
    -------
    obj: list | dict
        The original object with the validation fields added to any dict-like objects,
        inside and including the original object.
    """
    if isinstance(obj, list):
        for item in obj:
            validation_add_initial_validation_status(item)
    elif isinstance(obj, dict):
        for value in obj.values():
            validation_add_initial_validation_status(value)
        obj["validated"] = True
        obj["validation_errors"] = {}
    else:
        pass
    return obj


def validate_nested_objects(
    raw_books: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    First validation layer: validate nested Readwise objects.

    Check and fix essential aspects of nested objects to avoid downstream errors once
    the API data is flattened. All books are assumed to have a "user_book_id" field.

    Each object has the following fields added
    - `validated`: True or False
    - `validation_errors`: a dict of fields and errors (empty if valid)

    Notes
    -----
    - The validation checks:
        - Each book has a list of highlights and book_tags. If the field is missing, or
          the field has a value that isn't a list, set to an empty list.
        - Each highlight's `book_id` matches the book's `user_book_id`.
        - Each highlight has a list of tags. If the field is missing, or the field has a
          value that isn't a list, set to an empty list.
    - There are current no nested checks for:
        - Book tags
        - Highlight tags
    - The validation checks are not strict. They are designed to ensure that the data
      is in a format that can be processed downstream. The checks are not exhaustive
      and do not cover all possible edge cases. The goal is to include as much data as
      possible while still being able to promise type safety when using data from the
      database.

    Parameters
    ----------
    raw_books : list[dict]
        A list of raw dicts from the Readwise API.

    Returns
    -------
    raw_books : list[dict]
        A list of raw dicts from the Readwise API. Each object now has a `validated`
        field set to True or False, and a `validation_errors` field containing a list of
        errors (empty if the object is valid). False will indicate the object failed
        validation in any validation layer. (i.e. including later layers).
    """
    raw_books_with_initial_validation_status = cast(
        list[dict[str, Any]], validation_add_initial_validation_status(raw_books)
    )
    for book in raw_books_with_initial_validation_status:
        validation_ensure_field_is_a_list(book, "highlights", "book")
        validation_ensure_field_is_a_list(book, "book_tags", "book")
        for highlight in book["highlights"]:
            validation_ensure_highlight_has_correct_book_id(
                highlight, book["user_book_id"]
            )
            validation_ensure_field_is_a_list(highlight, "tags", "highlight")
    return raw_books


def flatten_books_with_highlights(
    raw_books: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """
    Flatten the nested API response from the Readwise Highlight EXPORT endpoint.

    Split "highlights" and "book_tags" from a book.  Split "tags" from "highlights".

    Note
    ----
    This function works regardless of objects having additional "validated" and
    "validation_error" fields.

    Parameters
    ----------
    raw_books: list[dict[str, Any]]
        A list of dicts where each dict represents a "book". Nested within each book
        are "book_tags" and "highlights".  Nested within "highlights" are "tags".

    Returns
    -------
    dict[str, list[dict[str, Any]]
        A dictionary with the keys "books", "book_tags", "highlights", "highlight_tags".
        The values are the unnested keys and values for the object.
    """
    books = []
    book_tags = []
    highlights = []
    highlight_tags = []

    for raw_book in raw_books:
        books.append(
            {k: v for k, v in raw_book.items() if k not in ("book_tags", "highlights")}
        )

        for book_tag in raw_book.get("book_tags", []):
            book_tag["user_book_id"] = raw_book["user_book_id"]
            book_tags.append(book_tag)

        for highlight in raw_book.get("highlights", []):
            for tag in highlight.get("tags", []):
                tag["highlight_id"] = highlight["id"]
                highlight_tags.append(tag)

            highlight = {k: v for k, v in highlight.items() if k != "tags"}
            highlight["book_id"] = raw_book["user_book_id"]
            highlights.append(highlight)

    return {
        "books": books,
        "book_tags": book_tags,
        "highlights": highlights,
        "highlight_tags": highlight_tags,
    }


def validate_flattened_objects(
    flattened_api_data: dict[str, list[dict[str, Any]]],
    schemas: dict[str, type[BaseModel]] = SCHEMAS_BY_OBJECT,
) -> dict[str, list[dict[str, Any]]]:
    """
    Second validation layer: validate the fields in flattened Readwise objects.

    Validate by casting an object dict to a Pydantic schema. "validated" is either True
    or, if invalid, a dict of fields and errors. E.g.
    ```python
    "validated" {
         'asin': 'String should have at least 10 characters',
         'author': 'Field required',
        ...
    }
    ```
    Parameters
    ----------
    flattened_api_data: dict[str, list[dict[str, Any]]]
        The flattened API data in the form:
        ```
        {
            "books": [<books>],
            "book_tags": [<book_tags>],
            "highlights": [<highlights>],
            "highlight_tags": [<highlight_tags>],
        }
        ```
    Returns
    -------
    dict[str, list[dict[str, Any]]]
        The flattened API data in it's original form, with each individual object -
        book, book tag, highlight, highlight_tag - given a "validated" field.
    """
    processed_objects_by_type = {}
    for object_type, objects in flattened_api_data.items():
        processed_objects = []
        for object in objects:
            try:
                schema = schemas[object_type]
                api_fields: dict[str, Any] = {}
                non_api_fields: dict[str, Any] = {}
                for field, value in object.items():
                    (api_fields if field in schema.model_fields else non_api_fields)[
                        field
                    ] = value
                item_as_schema = schema(**api_fields)
                # Capture any data integrity transformation's done by the schema.
                # Reattach validation data.
                item_as_schema_dumped = item_as_schema.model_dump()
                # Reattach non API fields including validation fields. NOTE: If this try
                # branch succeeds, an item's validation status doesn't change. If it
                # was true from earlier validation, it stays true. If it was false -
                # invalid on early checks - it remains invalid.
                item_as_schema_dumped.update(non_api_fields)
                processed_objects.append(item_as_schema_dumped)
            except ValidationError as err:
                object["validated"] = False
                validation_errors = {}
                for detail in err.errors():
                    validation_errors[".".join(str(part) for part in detail["loc"])] = (
                        detail["msg"]
                    )
                object["validation_errors"].update(validation_errors)
                processed_objects.append(object)
        processed_objects_by_type[object_type] = processed_objects
    return processed_objects_by_type


def update_database_flattened_objects(
    session: Session,
    flattened_validated_objs: dict[str, list[dict[str, Any]]],
    start_fetch: datetime,
    end_fetch: datetime,
) -> ReadwiseBatch:
    """
    Update the database. Expects flattened Readwise objects.

    Parameters
    ----------
    session: Session
        A SQL alchemy session connected to a database.
    validated_objs: dict[str, list[dict[str, Any]]]
        The flattened API data in it's original form, with each individual object -
        book, book tag, highlight, highlight_tag - given a "validated" field.
    start_fetch: datetime
        The time the fetch was called.
    end_fetch: datetime
        The time the fetch was completed.

    Returns
    -------
    int | None
        The batch id of all the highlights and objects written to the database.
    """
    logger.info("Updating database")
    dbp_fd = DatabasePopulaterFlattenedData(
        session, flattened_validated_objs, start_fetch, end_fetch
    )
    batch_updated = dbp_fd.populate_database()
    logger.info("Database updated.")
    return batch_updated


def run_pipeline_flattened_objects(
    user_config: UserConfig,
    last_fetch: datetime | None = None,
    get_session_func: SessionFn = get_session,
    fetch_func: FetchFn = fetch_books_with_highlights,
    validate_nested_objs_func: ValidateNestedObjFn = validate_nested_objects,
    flatten_func: FlattenFn = flatten_books_with_highlights,
    validate_flat_objs_func: ValidateFlatObjFn = validate_flattened_objects,
    update_db_func: UpdateDbFlatObjFn = update_database_flattened_objects,
) -> None | ReadwiseBatch:
    """
    Orchestrate the end-to-end Readwise data sync process.

    Creates a new database and fetches all highlights, or gets the last fetch datetime
    and fetches only new/updated highlights.

    Use dependency injection for functions for simplified testing.

    Parameters
    ----------
    user_config : UserConfig, optional
        Configuration object.
    last_fetch: datetime | None, optional, default = None
        The last fetch datetime, if available and if only new highlights are required.
    get_session_func: SessionFn, optional, get_session()
        A function that returns a SQLAlchemy database Session.
    fetch_func: FetchFn, optional, default = fetch_books_with_highlights()
        Function that fetches highlights and returns them as a tuple with the start
        and end times of the fetch as datetimes.
    validate_nested_objs_func: ValidateNestedObjFn, optional,
            default = validate_nested_objects()
        The first layer of validation, performed on the nested Readwise objects output
        by the API. Adds fields "validated" and "validation_errors" to each obj.
    flatten_func: FlattenFn, optional, default = flatten_books_with_highlights()
        A function that flattens the nested API response into a dict of lists of
        unnested objects, associated by fk.
    validate_flattened_objs_func: ValidateFetchFlattenedObjFn, optional,
            default = validate_flattened_objects()
        The second layer of validation, performed on unnested objects using Pydantic
        schema.
    update_db_func: UpdateDbFlattenedDataFn, optional,
            default = update_database_flattened_objects()
        Function that populates the database with the flattened objects.

    Returns
    -------
    int | None
        The batch highlights were written in, or None if no writable highlights were
        found.
    """
    batch_written = None
    raw_books, start_fetch, end_fetch = fetch_func(last_fetch)

    with get_session_func(user_config.db_path) as session:
        if raw_books:
            nested_books_first_validation = validate_nested_objs_func(raw_books)
            flat_objs_first_validation = flatten_func(nested_books_first_validation)
            flat_objs_second_validation = validate_flat_objs_func(
                flat_objs_first_validation
            )
            # Raw books doesn't not guarantee writable updates. All highlights might
            # already exist in the database.
            batch_written: int | None = update_db_func(
                session, flat_objs_second_validation, start_fetch, end_fetch
            )

        # Always update the readwise_last_fetch table with the start and end fetch
        # times, even if no new data was fetched.
        update_readwise_last_fetch(session, start_current_fetch=start_fetch)

        try:
            logging.info("Committing session")
            session.commit()
            # Then return the batch id or batch object
            logging.info("Session committed")

        except Exception as err:
            session.rollback()
            logging.info(f"Error occurred committing session: {err}")
            raise err

        return batch_written
