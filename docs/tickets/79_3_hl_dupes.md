# Dealing with the highlight duplications

- Readwise does not deduplicate books reliably
- monitor for non-snipd books/highlights 

## What is the solution for snipd?

It's too big a problem to ignore with 30% of episodes effected.

1. Fix the Readwise database itself
    - Manually confirm, episode by episode, what can be deleted
    - Run the deletions
    - Assumes deletion is reliably counted as a "change" in and added to new batches
    - Reliably for both books and highlights

2. Workaround is fix in the Obsidian export
    - The RW db dupes themselves matter little
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

And if we contrast it with our known split session issue... we can't compare highlights, but we can clearly see that the difference listening sessions in action...

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

1. Which URL to use?

- For all books, `source_url` and `unique_url` are identical
- Will use `source_url` as makes most semantic sense


2. Almost all have location

- All that don't are "Episode AI Notes" (slight oddity here but can't reproduce)

WORKING ASSUMPTION: If not `location`, add at the end of the page. 
If more than one, order in ascending creation date. 
(Let errors created by this, if there are any, appear in usage)

3. All have `highlighted_at` and `created_at`


## Migrate `db_analysis.py` to OOP and use `db_export.py` objects

- Analysis loops were replciating output loops so migrated it all to OOP
- In DB Export:
    - `DbHls` is a parent object for a database export; it groups Hls (into by_book, by_snipd_url)
    - `HighlightFromDB` and `BookFromDB` now include ALL db fields, and additional helper fields
    - `SnipdEpisodeByDB` is a grouping of `BookFromDb`s with the same Snipd URL
        - So effectively a container object for books and highlights
    - `SnipdHighlightTranscript` and `SnipdHighlightAiEpisodeNotes` are instantiated with a `HighlightFromDb` and contain processing methods


QUESTIONS: Where are the lines between "general" and "snipd" here?
    - `DbHls`, `HightlightFromDb` and `BookFromDB` are designed to be general
    - I think we want to automate them though...
    - So `HighlightFromDb` on instantiation:
        - Knows if it's a snipd highlight
        - Knows if what type of snipd highlight
        - Has a SnipdHighlight<Type>

[Multiple locations example](79_examples.md#multiple-locations-example)


### Todos (1st Sept )

✅ 1) Restructure module
    - ❌ make it Snipd only?
    - ✅ group properties by the "stat generator"?

- 2) Look at Hls with matching `highlighted_at` by different snipd url. 

Current count is 56...?
    - This could be key, because it challenges our entire highlight version hypothesis
    - However, it's a small % - and issues should be revealled in usage, so not worth a lot of time


- 3) Look at Hls with matching `locations` but different `highlighted_ats` (the big part of work)
    - Why are the METHOD 1 and METHOD 2 counts different?

- 4) There are three remaing standalone functions:
    
    - These each attempt to answer a valuable question:
        
        - 1) `duplicate_hls_have_identical_highlighted_at`
            - We have assumed that duplicate/hl versions ARE reliably defined by `highlighted_at`
            - The latest snipd url analysis suggest this might not be true (in a tiny % of cases)
            - If it ISN'T true, we should detect this in our export output
                - i.e. We will see it, so don't need to worry about it
                - It's a problem of keeping MORE as a "duplicate/version" with different highlighted_at will both
                  currently be included
        
        - 2) `confirm_duplicate_hls_always_have_same_location`
            - So works on `highlighted_at` for versioning
                - Does the location always stay the same
            - This I would heavily expect to: I think we can say that Hls with exactly the same highlighted_at time
              ARE duplicates/versions (the question is if some are not)
            - This is potentially a useful double check 
            - HAVE I ALREADY DONE THIS???
        
        - 3) `duplicate_locations_need_to_be_kept`
            - So this is something we did a count of and found it DOES need handling
            - Effectively this is also addressing the `snipd_episodes_with_duplicate_location_hls` problem we 
              were working on, so this approach may be superseeded

[Example Hl with same highlighted_at but clearly different Hls](79_examples.md#example-hl-with-same-highlighted_at-but-clearly-different-hls)


- It is probably worth checking all the hl urls are unique and, if so, those are
  our highlight version checker...

- Do I need to redo other checks then???

- If every Hl url has the same highlighted_at, then they are (almost all) versions
    - Then that follows I think...

### Does using snipd url change anything?

- I don't think so!
- I can't see where I've actually written that code yet...
✅ Tidy up `obsidian_snipd.py` - build out full flow

See which decisions the analysis now needs to inform.

For later:
- [ ] Do we want to output stats on Hl type / Hl body type etc.?
    - Might not be a bad idea for monitoring??

### Next step - reconsider what we know

- code is commited
- export working, probably with kinks
- currently outputs ALL Hls - from every book - for a snipd episode
    - so we need sorting, filtering

