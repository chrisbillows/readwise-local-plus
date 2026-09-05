"""
Functions to interrogate the local readwise database.
"""
from dataclasses import dataclass, field
from datetime import datetime, date
import inspect
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from pathlib import Path

from sqlalchemy import Select, select

from readwise_local_plus.db_export import (
    DbHls, BookFromDb, HighlightFromDb, SnipdEpisodeFromDb
)
from readwise_local_plus.models import (
    Book,
    Highlight,
)

logger = logging.getLogger(__name__)


def ordered_property(order):
    """
    Decorator to order class properties.
    """
    def decorator(func):
        func.order = order
        return property(func)
    return decorator


class DbHlsAnalysis:
    """
    Methods and attributes for analysising a DbHls export.
    
    Driver function `self.all_stats` generates stats by calling functions that 
    loop over different groupings of Hls (e.g. by book, by snipd url, by  
    snipd url, location and highlighted time). Stats are added as attrs to
    the object.

    Stats are most easily output by creating properties which are 
    automatically  output via `self.print_analysis`. 

    Attributes
    ----------

    """
    def __init__(self, dbhls: DbHls):
        self.dbhls = dbhls
        # Does this list book urls? And it's just random non duplicates. Count better?
        # Then use `hls_by_snipd_episode` for a true list/double check?
        self.snipd_book_urls: list[str] = []
        self.snipd_duplicate_book_ids: list[int] = []
        self.snipd_books_url_mismatch: int = 0
        self.snipd_hls_no_location: list[HighlightFromDb] = []
        self.snipd_hls_no_location_ai_notes: list[HighlightFromDb] = []
        self.snipd_hls_no_highlighted_at: list[HighlightFromDb] = []
        self.snipd_hls_no_created_at: list[HighlightFromDb] = []
        self.snipd_hls_no_snipd_url: list[HighlightFromDb] = []
        self.snipd_episode_book_counts = {}
        self.snipd_hls_url_hl_at_mismatch: list[tuple[HighlightFromDb, HighlightFromDb]] = []
        #-------------------------------------
        self.snipd_hls_by_location: dict[str, dict[int, list[HighlightFromDb]]] = {}
        self.snipd_hls_by_location_and_hl_at: dict[str, dict[int, list[HighlightFromDb]]] = {}
        self.snipd_location_duplicates_by_snipd_url: dict[str, dict[int, list[HighlightFromDb]]] = {}
        self.snipd_duplicate_locations_2: int = 0
        #-------------------------------------
        self._all_stats()

#--------------------------------------------------------------------------------------------------------------------------

    @ordered_property(130)
    def snipd_duplicate_locations_from_hls_by_location(self):
        """
        13. Total unique HLs duplicating location (i.e. same location, different `highlighted_at`) METHOD 1:
        >>> WHY DOESN'T THIS MATCH METHOD 2???
        """
        duplicate_locations = 0
        for eps_hls_by_location in self.snipd_hls_by_location.values():
            for location, hls in eps_hls_by_location.items():

                # For location, group unique `highlighted_at`s
                highlighted_ats = set()

                for hl in hls:
                    highlighted_ats.add(hl.highlighted_at)

                # If all `highlighted_at`s the same: multiple versions of
                # same Hl. If more than one `highlighted_at` different
                # Hl(s) at the same location. 
                if len(highlighted_ats) > 1:
                    # Total all Hls with different `highlighted_at`
                    # Exclude an (abitrary) "original" for duplicate count
                    duplicate_locations += (len(highlighted_ats) - 1) 

        return duplicate_locations

    @ordered_property(140)
    def snipd_duplicate_locations_from_hls_by_location_and_hl_at(self) -> int:
        """
        14. Total unique HLs duplicating location (i.e. same location, different `highlighted_at`) METHOD 2:
        >>> WHY DOESN'T THIS MATCH METHOD 1???

        """
        total_hls = 0
        for snipd_url, hls_by_location_and_hl_at in self.snipd_location_duplicates_by_snipd_url.items():
            for location, hls_by_hl_at in hls_by_location_and_hl_at.items():
                for hl_at, hls in hls_by_hl_at.items():
                    total_hls += (len(hls) - 1)
        return total_hls

    @ordered_property(150)
    def snipd_episodes_with_duplicate_location_hls(self) -> int:
        """
        15. Total Snipd episodes with at least one duplicate location highlight:
        """
        return len(self.snipd_location_duplicates_by_snipd_url)

    def _group_snipd_episode_hls_by_location(
            self, snipd_episode: SnipdEpisodeFromDb
        ) -> None:
        """
        ORIGINAL METHOD
        
        Creates a new grouping for each `SnipdEpisodeFrimDb`:
                    -> All Hls
                        -> locations
                            -> Hl
        """
        hls_by_location: dict[str, list[HighlightFromDb]] = {}

        for hl in snipd_episode.hls:
            hl_location = hls_by_location.get(hl.location)
            if hl_location:
                hls_by_location[hl.location].append(hl)
            else:
                hls_by_location[hl.location] = [hl]

        self.snipd_hls_by_location[snipd_episode.snipd_url] = hls_by_location

    def _group_snipd_episode_hls_by_location_and_highlighted_at_and_missing_locations(
            self, snipd_episode: SnipdEpisodeFromDb
        ) -> None:
        """
        NEW METHOD

        Creates a new grouping for each `SnipdEpisodeFromDb`:
            -> All Hls
                -> locations
                    -> highlighted_at
                        -> Hl

        So a positive is any location with multiple `highlighted_at` keys -
        the count of them would be the unique hls.
        
        Adds this `self.snipd_hls_by_location`.
        """
        hls_by_location_and_highlighted_at: dict[int, dict[datetime, list[HighlightFromDb]]] = {}
        location_duplicates_hls_by_location_and_highlighted_at: dict[str, dict[datetime, list[HighlightFromDb]]] = {}

        for hl in snipd_episode.hls:
            location = hls_by_location_and_highlighted_at.setdefault(hl.location, {})
            highlights = location.setdefault(hl.highlighted_at, [])
            highlights.append(hl)

        self.snipd_hls_by_location_and_hl_at[snipd_episode.snipd_url] = hls_by_location_and_highlighted_at

        for location, hls_by_hl_at in hls_by_location_and_highlighted_at.items():
            if len(hls_by_hl_at) > 1:
                location_duplicates_hls_by_location_and_highlighted_at[location] = hls_by_hl_at

        if location_duplicates_hls_by_location_and_highlighted_at:
            self.snipd_location_duplicates_by_snipd_url[snipd_episode.snipd_url] = location_duplicates_hls_by_location_and_highlighted_at   


#--------------------------------------------------------------------------------------------------------------------------
    def print_properties(self):
        """
        Print the available properites.

        Helper function to check all properties. Useful as module is
        structured with properties followed by the method that
        generates the objects the property is calculated on.
        """
        for name, prop in inspect.getmembers(type(self), lambda x: isinstance(x, property)):
            print("---")
            print(prop.fget.__name__)

    def print_analysis(self):
        """
        Print analysed summary stats.
        """
        print(
            f"==== SUMMARY STATS FOR '{self.dbhls.query_shortname}'"
            f" ON {datetime.now().isoformat(sep=" ", timespec="minutes")} ====\n"
        )

        # Gather and apply sorting via order_property decorator
        class_properties = inspect.getmembers(type(self), lambda x: isinstance(x, property))
        class_properties.sort(key=lambda item: getattr(item[1].fget, "order", 999))

        for name, prop in class_properties:
            print(inspect.getdoc(prop))
            print(getattr(self, name))
            print("---")

    def output_hls_missing_location_and_not_ai_notes(self) -> list[HighlightFromDb]:
        """
        Return hls missing location that are (probably) NOT episode ai notes.
        
        Returns
        -------
        list[HighlightFromDB]
            Requires manual printing etc. Not clear what ideal output is so 
            returns the highlights themselves.
        """
        result = []
        hl_ids_episode_ai_notes = [hl.id for hl in self.snipd_hls_no_location_ai_notes]

        for hl in self.snipd_hls_no_location:
            if hl.id not in hl_ids_episode_ai_notes:
                result.append(hl)
        return result

    def _all_stats(self) -> None:
        """
        Driver function to generate all intermediate lists, dicts and counts.
        """
        self._all_snipd_stats_on_hls_by_book()
        self._all_snipd_stats_on_hls_by_snipd_url()

    def _all_snipd_stats_on_hls_by_book(self):
        """
        Generate stats created by looping over `self.hls_by_book`.
        """
        for book in self.dbhls.hls_by_book:

            self._generate_snipd_episode_stats(book)
            self._generate_snipd_book_url_mismatch_stats(book)

            for hl in book.highlights:

                self._generate_snipd_hl_missing_location_stats(hl)
                self._generate_snipd_hl_missing_date_stats(hl)
                self._generate_snipd_hl_missing_url_stats(hl)

    def _all_snipd_stats_on_hls_by_snipd_url(self):
        """
        Genearate stats created by looping over `self.hls_by_snipd_url`.
        """    
        for snipd_episode in self.dbhls.hls_by_snipd_url:
            self._generate_snipd_unique_episode_book_counts(snipd_episode)
            self._analyse_hl_snipd_urls(snipd_episode)
            self._group_snipd_episode_hls_by_location(snipd_episode)
            self._group_snipd_episode_hls_by_location_and_highlighted_at_and_missing_locations(snipd_episode)

#----------- SORT BY PROPERTY AND METHOD THAT GENERATES STATS FOR PROPERTY  ---------
    
    # Property requires no generator method
    @ordered_property(10)
    def snipd_episodes(self) -> None:
        """
        1. Total Snipd highlights:
        """
        count = sum(
            len(book.highlights) for book in self.dbhls.hls_by_book
            if book.source == "snipd"
            ) 
        return count

    # Property requires not generator method
    @ordered_property(20)
    def snipd_highlights(self) -> int:
        """
        2. Total Snipd podcast episodes:
        """
        return len(self.dbhls._hls_by_book_dict)


    @ordered_property(30)
    def snipd_unique_episodes(self) -> int:
        """
        3. Total unique snipd urls/podcast episodes:
        """
        return len(self.snipd_book_urls)

    @ordered_property(40)
    def snipd_duplicate_episodes(self) -> int:
        """
        4. Total duplicate books (i.e. books duplicating pre-existing snipd url):
        """
        return len(self.snipd_duplicate_book_ids)

    def _generate_snipd_episode_stats(self, book: BookFromDb) -> None:
        """
        Count unique snipd episodes.

        TODO: duplicate_book_ids is only the "second" book, arbitrarily,
        TODO: depending on the sort used. If books are sorted, then 
        TODO: this is probably fine.
        """
        if book.source_url in self.snipd_book_urls:
            self.snipd_duplicate_book_ids.append(book.user_book_id)
        else:
            self.snipd_book_urls.append(book.source_url)


    @ordered_property(50)
    def snipd_url_mismatches(self) -> int:
        """
        5. Total snipd books where `source_url` and `unique_url` are different.
        """
        return self.snipd_books_url_mismatch

    def _generate_snipd_book_url_mismatch_stats(self, book: BookFromDb) -> None:
        """
        Count snipd books where `source_url` is different to `unique_url`.
        """
        if book.source_url != book.unique_url:
            self.snipd_books_url_mismatch += 1


    @ordered_property(60)
    def snipd_hls_missing_location(self) -> int:
        """
        6. Total snipd hls missing a `location` field.
        """
        return len(self.snipd_hls_no_location)

    @ordered_property(70)
    def snipd_hls_missing_location_ai_notes(self) -> int:
        """
        7. Total snipd hls missing a `location` field that are definitely 'Episode AI Notes':
        """
        return len(self.snipd_hls_no_location_ai_notes)

    def _generate_snipd_hl_missing_location_stats(self, hl: HighlightFromDb) -> None:
        """
        Count snipd hls missing `location`.

        Attempts to count "Episode AI Notes" Hls which will have no `location`.
        """
        if not hl.location and isinstance(hl.location, int):
            self.snipd_hls_no_location.append(hl)
            # Brittle to Snipd output changes
            if hl.text.startswith("Episode AI notes"):
                self.snipd_hls_no_location_ai_notes.append(hl)


    @ordered_property(80)
    def snipd_hls_missing_highlighted_at_date(self) -> int:
        """
        8. Total snipd hls missing a `highlighted_at` field.
        """
        return len(self.snipd_hls_no_highlighted_at)

    @ordered_property(90)
    def snipd_hls_missing_created_at_date(self) -> int:
        """
        9. Total snipd hls missing a `created_at` field.
        """
        return len(self.snipd_hls_no_created_at)

    def _generate_snipd_hl_missing_date_stats(self, hl: HighlightFromDb) -> None:
        """
        Count hls missing `highlighted_at` or `created_at`.
        """
        if not hl.highlighted_at:
            self.snipd_hls_no_highlighted_at.append(hl)
        if not hl.created_at:
            self.snipd_hls_no_created_at.append(hl)


    @ordered_property(100)
    def snipd_hls_missing_snipd_url(self) -> int:
        """
        10. Total hls missing a snipd hl `url` (distinct from snipd podcast url):
        """
        return len(self.snipd_hls_no_snipd_url)

    def _generate_snipd_hl_missing_url_stats(self, hl: HighlightFromDb) -> None:
        """
        Count hls missing a snipd hl `url` (distinct from snipd podcast url).
        """
        if not hl.url:
            self.snipd_hls_no_snipd_url.append(hl)


    @ordered_property(110)
    def snipd_unique_episode_book_counts(self) -> str:
        """
        11. Counts of total books per unique snipd url. (i.e. number of duplicate books).
        """
        result = "\n"
        for num_of_episodes, num_of_books in sorted(self.snipd_episode_book_counts.items()):
            result += (f"{num_of_episodes} episodes duplicated in {num_of_books} books\n")

        total_books = sum([(k * v) for k, v in self.snipd_episode_book_counts.items()])
        result += f"\nTotal snipd books: {total_books}"

        return result

    def _generate_snipd_unique_episode_book_counts(self, snipd_episode: SnipdEpisodeFromDb):
        book_count = len(snipd_episode.books)
        current_tally = self.snipd_episode_book_counts.get(book_count)

        if current_tally:
            self.snipd_episode_book_counts[book_count] = current_tally + 1
        else:
            self.snipd_episode_book_counts[book_count] = 1


    @ordered_property(120)
    def snip_highlighted_at_mismatch_hl_url(self) -> int:
        """
        12. Total Hls with matching `highlighted_at` but different <snip> url:
        """
        return len(self.snipd_hls_url_hl_at_mismatch)

    def _analyse_hl_snipd_urls(self, snipd_episode: SnipdEpisodeFromDb) -> None:
        """
        `hl.url` behaves identically to `highlighted_at` for Hl version tracking.

        Iterate over all Hls from all Books for a Snipd Episode. Add unique 
        `highlighted_at`s to a tracker. Makes a list to count and for easy
        future analysis (although see below note for accuracy).

        Hls have unique urls in the form: `https://share.snipd.com/snip/<uid>` 
        compared to episode/books where <snip> is replaced with <episode>.

        We prefer `highlighted_at` as a) it gives additional context and b)
        a lack of confidence HL URLs are used by Snipd users, so they might
        be removed.  (Could same be said for episode URLs...?).
        """
        tracker: dict[datetime, HighlightFromDb] = {}
        for hl in snipd_episode.hls:

            # Add unseen `highlighted_at`s to `tracker`
            if hl.highlighted_at not in tracker:
                tracker[hl.highlighted_at] = hl

            # For seen,  `highlighted_at`, confirm the new hl.url matches
            # the tracked hl's .url.
            # NOTE: This not exact. For example, if we have 3 highlights where Hls
            # Nos 2/3 have a different URL to Hl 1, but they have the same url as
            # EACH OTHER this will be counted as 2 mismatches and not one.
            # This is moot while mistmatches is zero.
            else:
                tracker_hl = tracker[hl.highlighted_at]
                if tracker_hl.url != hl.url:
                    self.snipd_hls_url_hl_at_mismatch.append((tracker_hl, hl))


def duplicate_hls_have_identical_highlighted_at(
        books_by_snipd_uid: dict[str, tuple[int, BookFromDb, str]],
        hls_by_book: dict[int, BookFromDb],
    ) -> None:
    """
    Do all duplicate hls have identical highlighted at times?
    
    Visual sampling by book for all episodes that don't match.

    Q: What is a duplicate highlight?
    A: Title, speaker, trancript CAN all change. But title is a fair approximation.
    ∴ Group hls if `highlighted_at` and `title` exact match 
    
    If ALL highlights grouped, don't output.

    """
    hls_by_snipd_uid = {}
    possible_problems = 0

    for snipd_uid, book_tuples in books_by_snipd_uid.items():
        # Ignore already unique episodes
        
        snipd_duplicates = len(book_tuples)

        if snipd_duplicates > 1:

            hls_by_highlighted_at: dict[datetime, HighlightFromDb] = {}

            for book_tuple in book_tuples: 
                book_id, book_obj, title = book_tuple
                real_book = hls_by_book[book_id]

                for hl in real_book.highlights:

                    saved_hls = hls_by_highlighted_at.get(hl.highlighted_at)

                    if saved_hls:
                        # hls_by_highlighted_at[hl.highlighted_at] = saved_hls.append(hl)
                        saved_hls.append(hl)
                    else:
                        hls_by_highlighted_at[hl.highlighted_at] = [hl]

            # ensure sorted by `highlighted_at`
            sorted_hls_by_highlighted_at = dict(sorted(hls_by_highlighted_at.items()))

            # Possible problems - any highlight that isn't CLEARLY a revision
            # This will produce false positives
            # - highlights that are not revisions (e.g. split listening sessions)
            # - highlights MISSED from later revisions (known to exist, not invesitaged why)
            # REAL GOAL: 
            #       - Is a highlights that are 'identical' but with seperate highlighted_at times
            # BEWARE: 
            #       - snips made at very similar times may have very NEAR highlighted_at times and
            #        identical location fields
            #       - these may need more detailed output 


            possible_problem = 0
        
            for highlighted_at, highlights in sorted_hls_by_highlighted_at.items():
                if len(highlights) == 1 and highlights[0].text.startswith("Episode AI notes"):
                    break
                if len(highlights) != snipd_duplicates:
                    possible_problem += 1
                    possible_problems += 1
                    break

            if possible_problem:
                print(f"\n====={title}=====")
                for highlighted_at, highlights in sorted_hls_by_highlighted_at.items():
                    for hl in highlights:
                        if len(highlights) == snipd_duplicates:
                            print(f"FINE      {highlighted_at.isoformat()} | {repr(hl.text[:50])}")
                        else:
                            print(
                                f"\nERROR >>> {highlighted_at.isoformat()} "
                                f"created_at {hl.created_at} | batch {hl.batch_id} | location: {hl.location}"
                                f"\n{repr(hl.text)}\n"

                                )

                breakpoint()

    print(f"----\n{possible_problems}: unique snipd episodes with possible problems")


def confirm_duplicate_hls_always_have_same_location(
        books_by_snipd_uid: dict[str, tuple[int, BookFromDb, str]],
        hls_by_book: dict[int, BookFromDb],
    ) -> None:
    """
    Does a duplicate highlight always retain it's location?
    """
    # hls_by_snipd_uid = {}
    problems = 0

    for snipd_uid, book_tuples in books_by_snipd_uid.items():
        # Ignore already unique episodes
        
        snipd_duplicates = len(book_tuples)

        if snipd_duplicates > 1:

            hls_by_highlighted_at: dict[datetime, HighlightFromDb] = {}

            for book_tuple in book_tuples: 
                book_id, book_obj, title = book_tuple
                real_book = hls_by_book[book_id]

                for hl in real_book.highlights:

                    saved_hls = hls_by_highlighted_at.get(hl.highlighted_at)

                    if saved_hls:
                        # hls_by_highlighted_at[hl.highlighted_at] = saved_hls.append(hl)
                        saved_hls.append(hl)
                    else:
                        hls_by_highlighted_at[hl.highlighted_at] = [hl]

            # ensure sorted by `highlighted_at`
            sorted_hls_by_highlighted_at = dict(sorted(hls_by_highlighted_at.items()))

            problem = 0

            # 
            for highlighted_at, highlights in sorted_hls_by_highlighted_at.items():
                hl_location = highlights[0].location
                for hl in highlights:
                    if hl.location != hl_location:
                        problems = 0



            # if possible_problem:
            #     print(f"\n====={title}=====")
            #     for highlighted_at, highlights in sorted_hls_by_highlighted_at.items():
            #         for hl in highlights:
            #             if len(highlights) == snipd_duplicates:
            #                 print(f"FINE      {highlighted_at.isoformat()} | {repr(hl.text[:50])}")
            #             else:
            #                 print(
            #                     f"\nERROR >>> {highlighted_at.isoformat()} "
            #                     f"created_at {hl.created_at} | batch {hl.batch_id} | location: {hl.location}"
            #                     f"\n{repr(hl.text)}\n"

            #                     )

            #     breakpoint()

    print(f"----\n{problems}: unique snipd episodes with possible problems")




def duplicate_locations_need_to_be_kept(
        books_by_snipd_uid: dict[str, tuple[int, BookFromDb, str]],
        hls_by_book: dict[int, BookFromDb],
    ) -> None:
    """
    Do we ever want more than a single highlight for a given location.

    When will we see duplicate locations?

    1 - when a new version exists ∴ created_at and location will match (confirmed)
    2 - when multiple snips were started at the same position
    3 - unknown edge cases?

    """
    duplicate_location_hls = 0

    for snipd_uid, book_tuples in books_by_snipd_uid.items():
        
        hls_by_location_and_hlat: dict[int, dict[datetime, list[HighlightFromDb]]] = {}

        for book_tuple in book_tuples:
            book_id, book_obj, title = book_tuple
            real_book = hls_by_book[book_id]

            for hl in real_book.highlights:
                by_time = hls_by_location_and_hlat.setdefault(hl.location, {})
                by_time.setdefault(hl.highlighted_at, []).append(hl)


        # TODO: What is this actually doing right now???!
        # Need to think through what we are achieving here.
        # Seems to just be showing versions - what are we trying to exclude here


        # ensure sorted by `highlighted_at`
        sorted_hls_by_location_and_hlat = dict(sorted(hls_by_location_and_hlat.items()))
 
        for location, highlighted_at_dict in sorted_hls_by_location_and_hlat.items():
            # means a location has multiple highlighted_at times
            # duplicates/revisions would always have the SAME
            if len(highlighted_at_dict.keys()) > 2:
                
                print(f"\n====={title} | {location}=====")
                breakpoint()
                for highlighted_at, hls in highlighted_at_dict.items():
                    # more than one HL at a) that location b) with that created_time
                    print(f"highlighted_at: {highlighted_at} | highlights: {len(hls)}")

                    for hl in hls:                        
                        print(f"batch {hl.batch_id}",
                            f"\n{repr(hl.text)}\n"
                        )

    print(
        f"----\n{duplicate_location_hls}: snipd episodes where duplicate locations have different highlight_at times"
    )


if __name__ == "__main__":
    # Use for experimentation/development
    all_snipd_hls = DbHls("snipd", "all")
    all_snipd_hls_analysis = DbHlsAnalysis(all_snipd_hls)
    all_snipd_hls_analysis.print_analysis()
