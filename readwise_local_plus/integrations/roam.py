"""
Generalised interactions with Roam Research APIs.

Classes, methods and functions to create a generalised, reusable wrapper for interacting
with Roam Research.

The rule of thumb is reuse - if the functionality is unique, or likely to be unique, to
a single use case then it keep in a specific workflow.
"""

import logging
from datetime import date
from typing import Any, Iterable, cast

import requests
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from readwise_local_plus.config import fetch_user_config
from readwise_local_plus.db_operations import get_session
from readwise_local_plus.models import (
    RoamBookExport,
    RoamExportBatch,
    RoamHighlightExport,
    RoamHighlightSnapshot,
    RoamPage,
    RoamPageSnapshot,
)

logger = logging.getLogger(__name__)


class RoamAPIError(Exception):
    pass


class RoamUnauthorizedError(RoamAPIError):
    pass


class RoamRateLimitError(RoamAPIError):
    pass


class RoamUnavailableError(RoamAPIError):
    pass


class TempUidGenerator:
    """
    Generates unique temporary negative integers for Roam batch actions.

    Roam treats negative integers as temporary UIDs.
    These are resolved into permanent UIDs on write.
    """

    def __init__(self, start: int = -1) -> None:
        if start >= 0:
            raise ValueError("TempUidGenerator must start with a negative integer")
        self._next = start

    def next(self) -> int:
        uid = self._next
        self._next -= 1
        return uid

    def reset(self, start: int = -1) -> None:
        if start >= 0:
            raise ValueError("TempUidGenerator must start with a negative integer")
        self._next = start


class RoamClient:
    """
    Interactions with the Roam backend API.
    """

    BASE_URL = "https://api.roamresearch.com/api/graph"

    def __init__(self) -> None:
        """
        Initialise instance of the class.
        """
        self.user_config = fetch_user_config()
        self.graph_name = self.user_config.roam_graph_name
        self.token = self.user_config.roam_api_token
        self.uid_generator = TempUidGenerator()

    def _get_temp_uid(self) -> int:
        """
        Create a sequential temporary UID.

        To get the real block UIDs returned, temp UIDs must be specified in the payload.
        (The real UIDs are returned in a dict where the key is the temp UID).
        """
        return self.uid_generator.next()

    def _headers(self) -> dict[str, str]:
        return {
            "accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}",
            "x-authorization": f"Bearer {self.token}",
        }

    def _handle_response(self, response: requests.Response) -> Any:
        if response.ok:
            return response.json()
        elif response.status_code == 401:
            raise RoamUnauthorizedError("Invalid or unauthorized token.")
        elif response.status_code == 429:
            raise RoamRateLimitError("Rate limit exceeded.")
        elif response.status_code == 503:
            raise RoamUnavailableError("Graph is unavailable or not ready.")
        else:
            try:
                error_msg = response.json()
            except Exception:
                error_msg = response.text
            raise RoamAPIError(f"{response.status_code}: {error_msg}")

    def _post(self, endpoint: str, payload: dict[str, Any]) -> Any:
        url = f"{self.BASE_URL}/{self.graph_name}/{endpoint}"
        response = requests.post(url, headers=self._headers(), json=payload)
        return self._handle_response(response)

    def _query(self, datalog: str, args: list[Any]) -> Any:
        return self._post("q", {"query": datalog, "args": args})

    def _write(self, payload: dict[str, Any]) -> Any:
        return self._post("write", payload)

    def _pull(self, payload: dict[str, Any]) -> Any:
        return self._post("pull", payload)

    @staticmethod
    def date_to_roam_daily_note(date: date) -> str:
        """
        Convert a date object to Roam's daily note format (MM-DD-YYYY).

        Parameters
        ----------
        date : date
            A datetime.date object.

        Returns
        -------
        str
            A string in the format 'MM-DD-YYYY'.
        """
        return date.strftime("%m-%d-%Y")

    def fetch_block_subtree(self, root_uid: str) -> dict[str, Any]:
        """
        Fetch an entire block tree (root + descendants).

        Returns
        -------
        dict
            The root block as a dict and it's children, recursively as a list of dicts.
        """
        datalog = """
        [:find (pull ?b [:block/uid :block/string :block/order {:block/children ...}])
         :in $ ?uid
         :where [?b :block/uid ?uid]]
        """
        results = self._query(datalog, [root_uid])

        if not results.get("result"):
            return {}

        block = results["result"][0][0]

        def normalize(b: dict[str, Any]) -> dict[str, Any]:
            return {
                "uid": b.get(":block/uid"),
                "text": b.get(":block/string", ""),
                "order": b.get(":block/order"),
                "children": [
                    normalize(child) for child in b.get(":block/children", [])
                ],
            }

        return normalize(block)

    def fetch_block_subtrees(self, root_uids: list[str]) -> dict[str, dict[str, Any]]:
        """
        Fetch full block trees for multiple root UIDs in one query.

        Returns
        -------
        dict[str, dict]
            Mapping from root UID -> normalized block tree.
        """
        datalog = """
        [:find (pull ?b [:block/uid :block/string :block/order {:block/children ...}])
        :in $ [?uid ...]
        :where [?b :block/uid ?uid]]
        """
        results = self._query(datalog, [root_uids])

        trees = {}
        for row in results.get("result", []):
            block = row[0]

            def normalize(b: dict[str, Any]) -> dict[str, Any]:
                return {
                    "uid": b.get(":block/uid"),
                    "text": b.get(":block/string", ""),
                    "order": b.get(":block/order"),
                    "children": [
                        normalize(child) for child in b.get(":block/children", [])
                    ],
                }

            trees[block[":block/uid"]] = normalize(block)

        return trees

    def fetch_child_blocks(self, block_uid: str) -> list[dict[str, str]] | None:
        """
        Pull the text only for direct children of a block.

        Direct children only. Run recursively to collect all text.

        Returns
        -------
        list[dict[str, str]]
            A list of dicts where the key is the text and the value is the block_uid:
            `{'[[Watched]]': 'uPzmyqs2m'}, {'[[Readwise highlights]]': 'D8Ykbjbxf'}`
        """
        fetched = self.fetch_block_attributes(
            block_uid, ["{:block/children [:block/uid :block/string]}"]
        )
        if not fetched:
            return None

        children = fetched[":block/children"]
        result: list[dict[str, str]] = []
        for child_dict in children:
            if isinstance(child_dict, dict):
                block_string = child_dict.get(":block/string")
                block_uid = child_dict.get(":block/uid")
                if block_string is not None and block_uid is not None:
                    result.append({str(block_string): str(block_uid)})
        return result

    def fetch_page_uid_from_title(self, page_title: str) -> str | None:
        """
        Find the UID of a page.

        Returns
        -------
        str | None
            The page's UID, or None if exact match not found.
        """
        query = """
        [:find ?page-uid
         :in $ ?page-title
         :where [?page :node/title ?page-title]
                [?page :block/uid ?page-uid]]
        """
        result = self._query(query, [page_title])
        if result.get("result"):
            return str(result["result"][0][0])
        else:
            return None

    def fetch_block_attributes(
        self, block_uid: str, selectors: list[str]
    ) -> dict[str, str]:
        """
        Fetch selected block attrs.

        Parameters
        ----------
        block_uid : str
            Target block.
        selectors : list[str]
            List of selectors as strings.

        Notes
        -----
        Available attributes, may not be exhaustive:

        Block:
            - ':create/user', ':block/string', ':edit/seen-by', ':create/time',
            - ':block/heading', ':edit/user', ':block/children', ':block/uid',
            - ':block/open', ':edit/time', ':db/id', ':block/parents', ':block/order',
            - ':block/page'

        Page:
            - ':create/user', ':create/time', ':node/title', ':edit/user',
            - ':block/children', ':log/id', ':block/uid', ':edit/time', ':db/id'

        Returns
        -------
        dict[str, str]
            A dict of the selected attrs and their values, if the attr present. E.g.
                {':node/title': 'August 24th, 2025', ':block/uid': '08-24-2025'}
        """
        selectors_str = " ".join(selectors)
        page_name_or_block_text = {
            "eid": f'[:block/uid "{block_uid}"]',
            "selector": f"[{selectors_str}]",
        }
        result = self._post("pull", page_name_or_block_text)["result"]
        return cast(dict[str, str], result)

    def write_child_block(
        self,
        parent_uid: str,
        content: list[str],
        *,
        heading: int | None = None,
        open: bool | None = None,
    ) -> str:
        """
        Add a child block to a block (or page).

        Parameters
        ----------
        parent_uid : str
            The UID of the parent block. For daily notes the UID is the date in Roam
            format e.g. "09-21-2025". Use `date_to_roam_daily_note` to automate creating
            these.
        content : str
            The content of the block to be added.
        heading : int, optional
            The heading level for the block (1, 2, or 3). Defaults to None.
        open : bool, optional
            Whether the block state should be open or closed. Defaults to None (closed).

        Raises
        ------
        ValueError
            If the heading is not 1, 2, or 3.

        Returns
        -------
        str
           The UID of the created block.
        """
        if heading is not None and heading not in (1, 2, 3):
            raise ValueError("Roam heading must be 1, 2, or 3")

        temp_uid = self._get_temp_uid()

        location = {"order": "last", "parent-uid": parent_uid}
        block = {"string": content, "uid": temp_uid}
        if heading is not None:
            block["heading"] = heading
        if open is not None:
            block["open"] = open

        payload = {
            "action": "batch-actions",
            "actions": [
                {
                    "action": "create-block",
                    "location": location,
                    "block": block,
                }
            ],
        }
        response_json = self._write(payload)
        temp_id_for_block = response_json["tempids-to-uids"][str(temp_uid)]
        return str(temp_id_for_block)


class RoamBatchAction:
    def __init__(self) -> None:
        self.roam_client = RoamClient()
        self.batch_action_body = self.create_batch_action_body()

    def create_batch_action_body(self) -> dict[str, Any]:
        """Create an empty batch action body."""
        return {"action": "batch-actions", "actions": []}

    def append_a_child_block_action(
        self,
        parent_uid: int | str,
        content: str,
        *,
        heading: int | None = None,
        open: bool | None = None,
    ) -> int:
        """

        Parameters
        ----------
        parent_uid : int | str
            The UID of the parent block. Roam UIDs are strings, but temp UIDs are
            negative integers.
        content : str
            The content of the block to be added.
        heading : int, optional
            The heading level for the block (1, 2, or 3). Defaults to None.
        open : bool, optional
            Whether the block state should be open or closed. Defaults to None (closed).

        Returns
        -------
        int
            The temp_uid of the block.
        """
        temp_uid = self.roam_client._get_temp_uid()

        if heading is not None and heading not in (1, 2, 3):
            raise ValueError("Roam heading must be 1, 2, or 3")

        location = {"order": "last", "parent-uid": parent_uid}
        block = {"string": content, "uid": temp_uid}
        if heading is not None:
            block["heading"] = heading
        if open is not None:
            block["open"] = open

        self.batch_action_body["actions"].append(
            {
                "action": "create-block",
                "location": location,
                "block": block,
            }
        )
        return temp_uid

    def append_delete_block_action(self, block_uid: str) -> None:
        """Queue a delete-block action for the supplied UID."""

        self.batch_action_body.setdefault("actions", []).append(
            {
                "action": "delete-block",
                "block": {"uid": block_uid},
            }
        )

    def execute_batch_action(self) -> dict[str, str] | None:
        """"""
        response_json = self.roam_client._write(self.batch_action_body)
        # {'tempids-to-uids':
        #   {
        #       '-12': 'WwOwJiPtF', '-4': 'a4dTDJAVA', '-2': 'mht-feEDx',
        #       '-1': 'yq5xSLLSd', '-8': 'IE9Qp8Gyt', '-6': 'wQ6OTUS4U',
        #       '-3': 'YdgE0-FgX', '-7': 'YEwvr1Zfp', '-11': 'K7kkuX_xN',
        #       '-9': 'Qx_yRJsBU', '-10': 'VILbzzDmC', '-13': 'ej3lDcwC1',
        #       '-5': 'wIpxGQu23'}
        #   }
        return response_json["tempids-to-uids"] if response_json else None


def delete_roam_export_batch(
    batch_id: int,
    *,
    session: Session | None = None,
) -> None:
    """Delete a Roam export batch, removing Roam blocks and database records.

    Parameters
    ----------
    batch_id : int
        Primary key of the ``RoamExportBatch`` to delete.
    session : Session, optional
        Existing SQLAlchemy session. If omitted, a new session is created using the
        configured database path.
    """

    owns_session = False
    if session is None:
        config = fetch_user_config()
        session = get_session(config.db_path)
        owns_session = True

    assert session is not None  # for static type checkers

    def _unique(values: Iterable[str]) -> list[str]:
        unique_values: list[str] = []
        seen: set[str] = set()
        for value in values:
            if value and value not in seen:
                seen.add(value)
                unique_values.append(value)
        return unique_values

    try:
        export_batch = session.get(RoamExportBatch, batch_id)
        if export_batch is None:
            return

        batch_action = RoamBatchAction()

        highlight_uids = _unique(h.block_uid for h in export_batch.highlights)
        book_uids = _unique(b.parent_block_uid for b in export_batch.books)
        header_uids = _unique(p.highlights_header_uid for p in export_batch.pages)

        for uid in highlight_uids:
            batch_action.append_delete_block_action(uid)
        for uid in book_uids:
            batch_action.append_delete_block_action(uid)
        for uid in header_uids:
            batch_action.append_delete_block_action(uid)

        if batch_action.batch_action_body.get("actions"):
            try:
                batch_action.execute_batch_action()
                print(f"Deleted Roam blocks for batch {batch_id}")
            except (requests.exceptions.RequestException, RoamAPIError) as exc:
                logger.warning(
                    "Failed to delete Roam blocks for batch %s: %s",
                    batch_id,
                    exc,
                )

        # Order matters here due to foreign key constraints.
        roam_objects = (
            RoamHighlightSnapshot,
            RoamHighlightExport,
            RoamBookExport,
            RoamPageSnapshot,
            RoamPage,
        )

        for roam_obj in roam_objects:
            stmt = select(roam_obj).where(roam_obj.export_batch_id == batch_id)
            results = session.execute(stmt).scalars().all()
            for obj in results:
                session.delete(obj)

        try:
            export_batch = session.get(RoamExportBatch, batch_id)
            session.delete(export_batch)
            session.commit()
            print(f"Deleted Roam export batch {batch_id} and associated db records")
        except OperationalError as exc:
            session.rollback()
            logger.error(
                "Failed to delete Roam export batch %s due to database error: %s",
                batch_id,
                exc,
            )
            return
    except Exception:
        session.rollback()
        raise
    finally:
        if owns_session:
            session.close()


if __name__ == "__main__":
    delete_roam_export_batch(1)
