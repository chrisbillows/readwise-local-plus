# Roam Page State Notes

## Problem

The export flow currently tracks Roam daily note page state in two SQLite tables:

- `roam_known_pages`
- `roam_pages`

At first glance this looks redundant. Both tables are about the same Roam daily note page, and the distinction is not obvious when reading the code later.

The confusion shows up most clearly in export logic where we appear to care about two separate facts:

- does the page exist?
- do we already know the `[[Readwise highlights]]` header uid for that page?

Without explanation, this looks like needless complexity. In practice, it exists to model partial-success states in Roam writes.

## Why Both Tables Exist

The current design distinguishes:

- `roam_known_pages`
  - "We know this Roam daily note page exists."
  - This can be true even if we have not yet successfully written the Readwise header or any child blocks.

- `roam_pages`
  - "We know this page exists, and we also know the uid of the Readwise header on it."
  - This is the tracked/export-aware state.

This distinction matters because Roam writes are not transactional from the app's point of view. A run can partially succeed.

Examples of states the current model can represent:

1. Page confirmed to exist, no Readwise header written yet.
2. Readwise header written, but no book headers yet.
3. Book header written, but no highlights yet.
4. Highlights written and tracked.

The main practical benefit is avoiding unnecessary `create_page(..., exists_ok=True)` calls while still tolerating partial failures.

If the app only tracked `roam_pages`, then a page that existed but did not yet have a tracked Readwise header could trigger another page-create API call on the next run. If this happened across many pages, it would create unnecessary Roam traffic.

So the split is not arbitrary. It exists because the app is defensive about partial writes and wants to avoid repeated page-create calls.

## Option A: Keep Both Tables And Document Them Properly

This is the lowest-risk option.

Keep the current schema, but make the rationale explicit in code and docs so future readers do not have to reverse-engineer the design.

### Suggested documentation locations

1. ORM model docstrings in `readwise_local_plus/models.py`
2. Export workflow notes in `readwise_local_plus/workflows/roam_daily_note.py`
3. Export workflow notes in `readwise_local_plus/workflows/roam_daily_note_export.py` or its replacement
4. A short architecture note in `docs/`

### Suggested model doc wording

For `RoamKnownPage`:

```python
class RoamKnownPage(Base):
    """
    Track Roam daily note pages that are known to exist.

    This is intentionally separate from `RoamPage`. A page may be known to exist
    before the app has successfully written and tracked the `[[Readwise highlights]]`
    header on that page.

    This split allows the exporter to:
    - tolerate partial-success Roam writes
    - avoid repeated page-create API calls
    - distinguish "page exists" from "page has tracked Readwise export state"
    """
```

For `RoamPage`:

```python
class RoamPage(Base):
    """
    Track a Roam daily note page that has a known `[[Readwise highlights]]` header.

    `RoamKnownPage` records page existence only.
    `RoamPage` records the stronger state where the page exists and the app knows
    the uid of the Readwise header used for exports.
    """
```

### Suggested workflow note

Add a short note near page-state loading logic:

```python
# Page existence and tracked Readwise-header existence are different states.
# A Roam page may exist even if a prior export failed before the header uid
# was recorded. We therefore check both `RoamKnownPage` and `RoamPage`.
```

### Benefits

- no migration risk
- preserves current behavior exactly
- easiest option operationally

### Costs

- schema remains conceptually awkward
- future code still has to reason about two tables for one page concept

## Option B: Migrate To A Single Table

This is the cleaner data model.

The idea is to collapse `roam_known_pages` and `roam_pages` into one table representing:

- "What do we know about this Roam daily note page?"

The page can then be in either a minimal or enriched state in the same row.

## Proposed single-table shape

Example shape:

- `page_uid` primary key
- `last_verified_at` nullable or not-null
- `highlights_header_uid` nullable
- `highlights_header_text` nullable
- `export_batch_id` nullable

Possible meanings:

- row exists, `highlights_header_uid IS NULL`
  - page known to exist, but no tracked Readwise header yet

- row exists, `highlights_header_uid IS NOT NULL`
  - page exists and Readwise header is tracked

This preserves the useful partial-failure state without splitting the concept across two tables.

## How the merged table would work

Read path:

- load one row by `page_uid`
- if no row:
  - page unknown
- if row exists and `highlights_header_uid is NULL`:
  - page exists, header not tracked
- if row exists and `highlights_header_uid is not NULL`:
  - page exists and header can be reused

Write path:

- when page existence is confirmed:
  - insert row if missing
  - update `last_verified_at`
- when Readwise header uid becomes known:
  - update the same row with `highlights_header_uid` and `highlights_header_text`

## Migration outline

Both tables currently contain live data, so migration should be done carefully.

### Safe migration approach

1. Add any missing nullable columns to `roam_pages`
   - add `last_verified_at` if you want to preserve the semantics of `roam_known_pages`
   - ensure `highlights_header_uid` and `highlights_header_text` can represent the partial state you need

2. Backfill `roam_pages` from `roam_known_pages`
   - for each `roam_known_pages.page_uid` that is not already in `roam_pages`
   - insert a `roam_pages` row with:
     - `page_uid`
     - `last_verified_at`
     - `highlights_header_uid = NULL`
     - `highlights_header_text = NULL`

3. For rows already present in `roam_pages`
   - preserve existing `highlights_header_uid` and `highlights_header_text`
   - optionally merge or max `last_verified_at`

4. Update application code
   - replace dual checks against `RoamKnownPage` and `RoamPage`
   - load one page-state row only
   - interpret `NULL` header uid as "page exists, header not tracked"

5. Run validation queries
   - count rows before and after
   - verify every `roam_known_pages.page_uid` is represented in merged `roam_pages`
   - verify existing tracked page rows retain their header uids

6. Only then drop `roam_known_pages`
   - keep this as a separate migration step after code has shipped and data has been checked

## Migration cautions

- do not drop `roam_known_pages` in the same step as the backfill unless recovery is trivial
- existing code may implicitly assume `highlights_header_uid` is always present on `roam_pages`
- model and workflow code will both need updating
- tests or one-off verification scripts should compare pre/post row counts and sample records

## Recommendation

Short term:

- document the current two-table rationale clearly

Medium term:

- consider the one-table migration if page-state complexity continues to cause confusion in exporter design

If the priority is stability, documentation is enough.
If the priority is long-term model clarity, the merged-table design is better.
