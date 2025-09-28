"""
Generalised interactions with Roam Research APIs.

Classes, methods and functions to create a generalised, reusable wrapper for interacting
with Roam Research.

The rule of thumb is reuse - if the functionality is unique, or likely to be unique, to
a single use case then it keep in a specific workflow.
"""

from datetime import date
from typing import Any

import requests

from readwise_local_plus.config import fetch_user_config


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

    def __init__(self, start: int = -1):
        if start >= 0:
            raise ValueError("TempUidGenerator must start with a negative integer")
        self._next = start

    def next(self) -> int:
        uid = self._next
        self._next -= 1
        return uid

    def reset(self, start: int = -1):
        if start >= 0:
            raise ValueError("TempUidGenerator must start with a negative integer")
        self._next = start


class RoamClient:
    """
    Interactions with the Roam backend API.
    """

    BASE_URL = "https://api.roamresearch.com/api/graph"

    def __init__(self):
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

    def fetch_block_subtree(self, root_uid: str) -> dict:
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

        def normalize(b):
            return {
                "uid": b.get(":block/uid"),
                "text": b.get(":block/string", ""),
                "order": b.get(":block/order"),
                "children": [
                    normalize(child) for child in b.get(":block/children", [])
                ],
            }

        return normalize(block)

    def fetch_block_subtrees(self, root_uids: list[str]) -> dict[str, dict]:
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

            def normalize(b):
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

    def fetch_child_blocks(self, block_uid) -> list[dict[str, str]] | None:
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
        result = {}
        for child_dict in children:
            result[child_dict[":block/string"]] = child_dict[":block/uid"]
        return result

    def fetch_page_uid_from_title(self, page_title: str) -> str:
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
            result["result"][0][0]
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
        selectors = " ".join(selectors)
        page_name_or_block_text = {
            "eid": f'[:block/uid "{block_uid}"]',
            "selector": f"[{selectors}]",
        }
        return self._post("pull", page_name_or_block_text)["result"]

    def write_child_block(
        self,
        parent_uid: str,
        content: list[str],
        *,
        heading: int | None = None,
        open: bool | None = None,
    ) -> dict | None:
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
        return temp_id_for_block


class RoamBatchAction:
    def __init__(self) -> None:
        self.roam_client = RoamClient()
        self.batch_action_body = self.create_batch_action_body()

    def create_batch_action_body(self):
        """Create an empty batch action body."""
        return {"action": "batch-actions", "actions": []}

    def append_a_child_block_action(
        self,
        parent_uid: str,
        content: list[str],
        *,
        heading: int | None = None,
        open: bool | None = None,
    ) -> str:
        """

        Returns
        -------
        str
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

    def execute_batch_action(self):
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


# from readwise_local_plus.config import UserConfig, fetch_user_config
# from readwise_local_plus.db_operations import get_session
# from readwise_local_plus.models import RoamPage, RoamHighlightExport
# from sqlalchemy import select
# from sqlalchemy.orm import Session


# class RoamDBWriter:

#     def __init__(self, header: str, highlights: dict):
#         """"""
#         self.header: str = header
#         self.highlights = highlights
#         self.roam_client: RoamClient = RoamClient()
#         self.user_config: UserConfig = fetch_user_config()
#         self.session: Session = get_session(self.user_config.db_path)
#         self.process_highlights()

#     def process_highlights(self):
#         """"""
#         roam_pages = {}
#         for daily_note, books in self.highlights.items():
#             # Batch roam and db writes by daily note page.
#             roam_batch_action = RoamBatchAction()
#             # existing_page = self.session.get(RoamPage, daily_note)
#             existing_page = None
#             header_exists, header_uid = self._handle_header(
#                     existing_page, daily_note, roam_batch_action
#                 )
#             temp_uids, batch_action_body = self._write_highlights_to_roam_daily_note(
#                 books, header_uid, roam_batch_action
#                 )
#             self._update_roam_export_db(temp_uids, batch_action_body)
#             roam_page = RoamPage(
#                 page_uid = daily_note,
#                 highlights_header_uid="tbc",
#                 block_tree=roam
#             )


#     def _handle_header(
#         self,
#         existing_page: RoamPage,
#         daily_note: str,
#         roam_batch_action: RoamBatchAction
#         ):
#         """"""
#         dn_blocks = self.roam_client.fetch_block_subtree(daily_note)
#         header_exists = False
#         header_uid = None

#         # for child_block in dn_blocks['children']:
#         #     uid_matches = child_block['uid'] == existing_page.highlights_header_uid
#         #     text_matches = child_block['text'] == existing_page.highlights_header_text

#         #     match (uid_matches, text_matches):
#         #         case (True, True):
#         #             print("Existing header confirmed")
#         #             header_uid = child_block['uid']
#         #             header_exists = True
#         #             break

#         #         case (True, False):
#         #             print(f"Header UID found. Text changed to: {child_block['text']}")
#         #             header_uid = child_block['uid']
#         #             header_exists = True
#         #             break

#         #         case (False, True):
#         #             print(f"Header text found but block UID incorrect: {child_block['uid']}")
#         #             print("Creating a new header")
#         #             # Don’t set header_exists, will fall through to creation later

#         #         case _:
#         #             continue

#         if not header_exists:
#             header_uid = roam_batch_action.append_a_child_block_action(
#                 daily_note, header, heading=1
#             )

#         return header_exists, header_uid

#     def _write_highlights_to_roam_daily_note(
#         self,
#         books: dict,
#         header_uid: str,
#         roam_batch_action: RoamBatchAction
#         ):
#         """"""
#         for book_id, highlights in books.items():
#             # This can't be right?
#             book_title = book_id
#             book_title_uid = roam_batch_action.append_a_child_block_action(
#                 header_uid, book_title, heading=3
#             )

#             for highlight in highlights:
#                 roam_batch_action.append_a_child_block_action(
#                     book_title_uid, highlight
#                 )

#             temp_uids = roam_batch_action.execute_batch_action()

#         return temp_uids, roam_batch_action.batch_action_body


#     def _update_roam_export_db(self, temp_uids, batch_action_body):


#         print("-------------")
#         print(temp_uids)
#         print(batch_action_body)
#         print("-------------")


if __name__ == "__main__":
    # rc = RoamClient()
    # dn_today = rc.date_to_roam_daily_note(date.today())
    # dn_today = "09-18-2025"

    input = {
        "09-21-2025": {"book_10": ["a", "b", "c"], "book_11": ["e", "f"]},
        "09-20-2025": {"book_11": ["g"], "book_12": ["h", "i", "j"]},
    }

    header = "Fake header"
    # roam_dbw = RoamDBWriter(header, input)
    rc = RoamClient()
    x = rc.fetch_block_subtrees(["09-21-2025", "09-20-2025"])
    print(x)

    # payload = {
    #         "action": "batch-actions",
    #         "actions": [
    #             {
    #                 "action": "create-block",
    #                 "location": {"parent-uid": "JjIBf_M5l", "order": "last"},
    #                 "block": {"string": "> Ioana", "uid": rc._get_temp_uid()}
    #             },
    #             {
    #                 "action": "create-block",
    #                 "location": {"parent-uid": "JjIBf_M5l", "order": "last"},
    #                 "block": {"string": "> Andreea", "uid": rc._get_temp_uid()}
    #             },
    #             {
    #                 "action": "create-block",
    #                 "location": {"parent-uid": "JjIBf_M5l", "order": "last"},
    #                 "block": {"string": "> Stuey", "uid": rc._get_temp_uid()}
    #             },
    #             {
    #                 "action": "create-block",
    #                 "location": {"parent-uid": "JjIBf_M5l", "order": "last"},
    #                 "block": {"string": "> Bebe", "uid": rc._get_temp_uid()}
    #             },
    #         ]
    #     }
