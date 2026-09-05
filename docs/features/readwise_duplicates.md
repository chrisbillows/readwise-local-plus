# Readwise Duplicate records

## Summary

Db contains multiple duplicates
  - duplicate books
    - either when snipd emits revised versions (unknown what triggers)
    - sometimes even seperate listening sessions (seeminlgy if episode metadata changes in between listening sessions)

- Snipd URLs retain stable episode and snip UUIDs across the different Readwise records. 

## Wider Readwise Duplicate Scan (22 August 2026)

### Scope

A subsequent read-only scan tested whether similar identity failures occur outside
Snipd. 

The scan checked:

- Exact and conservatively normalized highlight URLs.
- Book and highlight `external_id` values.
- Exact and conservatively normalized book source URLs.
- Exact and normalized highlight text across different Readwise books.
- The documented title, author, text, and source-URL dedupe signature.
- Same-book location and text collisions.
- Cross-source records sharing the same underlying source URL.

The URL normalization joined only unambiguous variants such as `twitter.com` versus
`x.com` and Twitter tracking-query variants. URL fragments and functional query
parameters were otherwise preserved to avoid treating distinct Gmail messages, Roam
pages, or forum topics as the same document.

### Overall result

Duplicate highlights are not unique to Snipd, but Snipd is overwhelmingly the largest
and most systematic case.

| Source or pattern | Likely extra highlights | Assessment |
| --- | ---: | --- |
| Snipd, same snip URL | 3,960 | Systematic and severe |
| Twitter | 29 | Multiple convincing integration or reprocessing failures |
| `api_article` | 26 | Historical reprocessing and document reassignment |
| Reader | 3 | Definitive stable-identity failure |
| Kindle | 2 | Exact duplicate rows; two additional color-different pairs are ambiguous |
| Cross-source imports | 4 | Same content imported through different methods |

This is approximately 60 convincing non-Snipd extras within individual sources, plus
four cross-source overlaps. The within-source result is roughly 0.17% of the 36,375
non-Snipd highlights, compared with approximately 30% of Snipd highlights being extras
under the same-highlight-URL identity test. 

The evidence therefore does not point to one universal four-field comparison simply
being disabled. It points to source integrations repeatedly assigning new identities,
with Readwise accepting and exporting those identities as distinct records. Snipd is a
very large instance of this broader class, while Reader demonstrates that duplication
can occur even when explicit stable identities survive intact.

## Monitoring

### Decision

- fix snipd as is ~30 of highlights
- tolerate the upstream duplicates and monitor them, not clean the live Readwise library 
or introduce a new canonical identity layer in the local mirror.

### Monitoring rules and examples

#### 1. Snipd // one episode URL under multiple Readwise book IDs

**Signal:** for `books.source = 'snipd'`, group by the episode UUID extracted from
`books.source_url` (falling back to `unique_url`) and alert when there is more than one
`user_book_id`.

This is a book/container alert. It does not by itself prove that any highlight is a
duplicate; calculate snip-set overlap using rule 3.


#### 2. Reader // one exported `external_id` under multiple Readwise IDs

**Signal:** independently for Reader books and highlights, group each non-null
`external_id` and alert when it maps to multiple Readwise primary IDs. This should be
treated as a high-confidence upstream identity failure.


#### 3. Twitter // one canonical tweet status ID under multiple highlight IDs

**Signal:** extract the numeric status ID from Twitter or X highlight URLs, normalize
`x.com`, `twitter.com`, and mobile hosts, and ignore only known tracking parameters.
Alert when one status ID maps to multiple Readwise highlight IDs.


#### 4. Twitter // replayed content where the old URL is null or a search URL

**Signal:** as a fallback when a status identity is unavailable, report exact
normalized text repeated within the same author/container and created close together.
Also report same-book, same-location, same-text rows whose older copy has no tweet URL
and newer copy has one.


#### 5. `api_article` // exact content replayed into a different book

**Signal:** group a conservative normalized-text hash across `api_article` books and
report exact matches in different `book_id` values. Raise confidence when the books
have the same canonical page URL, title/author, or a burst of copied highlights.
Retain short bylines and quotations as low-confidence until manually reviewed.


#### 6. Cross-source // same page URL with exact or contained highlight text

**Signal:** group books by conservatively canonicalized `source_url` without including
`books.source`, then compare normalized highlight text across source values. Report
exact matches separately from high-similarity or containment matches. Do not merge
automatically: importing the same page through two methods can contain deliberately
different selections.


#### 7. Any source // same book, location, and text under multiple IDs

**Signal:** group by `source`, `book_id`, `location`, `location_type`, and normalized
text. Alert when multiple highlight IDs occupy the same position. Compare color and
state before classifying; distinct colors may represent intentional repeated
highlighting.

#### 8. Any source // repeated book container without repeated highlights

**Signal:** group books by `source` plus canonical `source_url`. If there are multiple
book IDs but no overlapping source-highlight URL or normalized text, report a
low-severity structural split rather than a highlight duplicate.


