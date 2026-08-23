# Dealing with the highlight duplications

Specific details are in the local gitignored file.

We are resolved to monitor non-snipd books/highlights for the error types observed.

## What is the solution for snipd?

It's too big a problem to ignore with 30% of episodes effected.

1. Fix the Readwise database itself
    - Manually confirm, episode by episode, what can be deleted
    - Run the deletions
    - Assumes deletion is reliably counted as a "change" in and added to new batches
    - Reliably for both books and highlights

2. Workaround is fix in the Obsidian export
    - The RW dupes themselves matter little
    - We know we have a reliable indicator there in the snipd URL

## How would the Obsidian Fix Work

There are two observed failure types:

    1) Updates to old episodes
    2) New listening sessions where "something" ignores the deduping (the known issue
       seems to be because of a slight title change)

For updating old episodes:

- default to the new episode
    - delete the old episode from Obsidian
    - recreate a new one
    - log a warning (Original ep was deleted with rw link to old ep)
    - include rw link to old ep in the new episode export

- ISSUE: multiple episodes versions in the same batch (major issue for batch 1)
    - order isn't guaranteed... 
    - well, it can be if we sort first

For different listening sessions:
    - Example we saw changed episode title
    - But... no, we've seen some historic episode title changes also...


So, this duplicate highlight SHOWS the revision with the change in `created_at`:

```bash
location|highlighted_at|created_at
658|2023-12-22 11:52:49.155000|2023-12-22 11:52:49.667000

location|highlighted_at|created_at
658|2023-12-22 11:52:49.155000|2026-05-25 19:44:53.467000
```

This carries across multiple entries, including triple entries.

Also raises the question of ordering - which is presumably somewhat random at the moment, as they are just written out...

And if we contrast it with our known split session issue... we can't compare highlights, but we
can clearly see that the difference listening sessions in action...

## Possible workflow

- use existing mirror db as source of truth?
- a highlight is a 'REVISION' if it has:
    - same snipd URL
    - same location
    - same highlighted at
- in the case of a duplicate highlight, most recent "created_at" wins

Issue is: we don't store quotes independently
    - could consider it with mass linking... but Obsidian sucks at that

So, in event of an incoming revision
    - would we just recreate the entire page?

Possible flow:
- revision found
- existing page check
- existing page found...
- existing page deleted...
- pull all highlights by snipd-uid
- write out page
- skip the remainder in the current batch

## Moving to solution - cases

We need to do some analysis to ensure this rough flow works for enough of our actual cases.

```bash
Total Snipd podcast episodes: 887
Total Snipd highlights:       13375
---
676: Total snipd books/podcast episodes
211: Duplicate books/podcast episodes (use an already used snipd_uid)
---
193: Snipd UIDs listed by more than 1 book
Two books: 175 | Three books: 18
---
0: Books have different `source_url` and `unique_url`
---
299: HLs do not have a location field
299: Of those HLs are Episode AI Notes
---
0: HLs do not have a created_at field
0: HLs do not have a highlighted_at field
---
0: Hls with no location also have no created_at date
0: Hls with no location also have no highlighted_at date
---
0: hls in duplicate books are missing a created_at date
0: hls in duplicate books are missing a highlighed_at date
```

1. Which URL to use?

- For all books, `source_url` and `unique_url` are identical
- Will use `source_url` as makes most semantic sense


2. Almost all have location

- All that don't are "Episode AI Notes" (slight oddity here but can't reproduce)

WORKING ASSUMPTION: If not `location`, add at the end of the page. 
If more than one, order in ascending creation date. 
(Let errors created by this, if there are any, appear in usage)

3. All have `highlighted_at` and `created_at`




