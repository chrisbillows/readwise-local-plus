# Finalise the overall design

## Review current status

Current structure:

### `db_export.py`

- `DbHls`
    --> groups `HighlightFromDb`s by:
        - `BookFromDb`
        - `SnipdEpisodeFromDb`

    --> `HighlightFromDb` are ALREADY enriched 
        - adds `HighlightFromDb` properties
        - if a `BaseFmtr` is configured to the `hl_type`/`snipd_hl_snipd`
            - e.g `SnipdTranscriptFmtr`/`SnipdEpisodeAIotesFmtr`


### `db_analysis.py`

- `DBHlAnalysis`
    --> takes a `DbHls`
        - `@order_property`(ies) 
        - grouped with methods generating property's underlying stat(s)
        - likely will become purpose specific subclasses(Export? Source? 'Problem?')


### `obsidian_snipd.py`

- Driver function

```python
def write_dbhls_to_obsidian(
        user_config: UserConfig, query_shortname: str, batch_id: int | str,
    ) -> None:
```

--> takes a `query_shortname` and a `batch_id`
    --> instantiates a `Dbhls` with them
        --> iterates over `Dbhls.hls_by_snipd_url`
            --> populates them with `<hl_by_snipd_url>.populate`
                --> writes `<hl_by_snipd_url>.full_page` to Obsidian 

Working back to `<hl_by_snipd_url>.full_page`:
    --> `SnipdEpisodeFromDb`
        --> `SnipdEpisodeFromDb.populate`
            --> podcast_title
            --> episode_title
            --> front_matter
            --> page_body
            (all from already enriched Hls)

What is the boundary between "extracting from db" and "exporting"?
    - processing/fmting happens inbetween
    - divider is really reusability
    - So `SnipdEpisodeFromDb` could be a general snipd export object
        - with attrs like `obs_podcast_title`, `obs_page_front_matter`
        - or we could them in an obj `ObsFmtd`
    - Or we could rename it `SnipdEpisodeFromDbObsidianExport`
        - Now this we don't want - not at this stage
        - As most of this is likely to be reusable
    - For now, lets put the philosophy aside

## What's needed now?

Key things:

- ✅ Book ordering on `SnipdEpisodeFromDb`
- ❌ More analysis needed for this for HL ordering/filtering on versions
- ✅ Hl ordering/filtering on versions
    
- [ ] General cleanup todos (all over the place)

### Book Ordering on `SnipdEpisodeFromDb`

Needed for a) docstring contract b) to create 
`SnipdEpisodeFromDb.podcast_title` and `SnipdEpisodeFromDn.episode_title` 
from the most recent book obj.

- Hls are extracted ordered by
    - book_id
    - highlighted_at
    - id

- Effectively pre-grouped by book...
- book_ids are probably in order they are created at
- ∴  duplicate books would appear later in `hls_by_book_dict/hls_by_book`

- Confirmed by printing all `created_at` dates from all books
    - (Should this be `highlighted_at`???  Perhaps. Leave for now.)

- `_generate_hls_by_snipd_url_dict` iterates in order and appends books
- ∴ `SnipdEpisodeFromDb.hls_by_snipd_url[xxx].books` will be in oldest first order

- Confirmed in pdb, see [Book ordering in SnipdEpisodeFromDb](79_examples.md#book-ordering-in-snipdepisodefromdb)

Quick fix is just use last list item.
- Brittle sure, but it's low stakes and fine now, probably good enough long term

### - [ ] More analysis needed for this for HL ordering/filtering on versions??

What are our current assumptions? What do we currently know?

- some hls are missing a `location` (e.g. anything AI generated)
- all hls have a `highlighted_at`
- all hls have a (snipd) `url`
- there are ~54 hls with MATCHING `highlighted_at` but different (snipd) `url`
    - it IS possible for different Hls to have the exact same `highlighted_at`
        - see [example](79_examples.md#example-hl-with-same-highlighted_at-but-clearly-different-hls)

- there are ~289/~343 Hls with MATCHING `location` but different `highlighted_at`
    - we have issues with the count
    - but are we sure they exist

QUESTION: Do Episode AI Notes have urls?
- ✅ YES! They have 'episode-takeaways' urls!  See [episode takeaways example](79_examples.md#episode-takeaways-url-example)

QUESTION: Are there any other types?
- ✅ Nopre - just `snip` and `episode-takeways`.
(see [Types of snipd URL](79_examples.md#types-of-snipd-highlight-url)).


- By using url we (think) we are guaranteeing uniqueness...
    - i.e. all identical urls will have the same `highlighted_at` and same `location`
        - therefore those are moot

We look at `url` - and if there are more than one, we look at `created_at` and take
the latest.

This is true even for hls without `location` - their duplicates will also have no 
location.  We do want to SORT by location.

We will be working with `SnipdEpisodeFromDb.hls` (currently sorted by `highlighted_at`)

SEE `SnipedEpisodeFromDb._generate_hls` for latest WIP.

QUESTION: Where should Episode AI Notes go in the ordering?
- non-snipd hls get a int 0 location (see [[episode-ai-notes int 0 location](79_examples.md#episode-ai-nottes-int-0-as-location)])
- ❌ Problem, these are not always first
    - Ignore. No ticket. Will annoy me and I will fix if an issue.

- ✅Problem, podcast names not valid obsidian tags
    - make alphanumeric only