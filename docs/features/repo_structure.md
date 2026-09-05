# Evolution of structure

Do not refactor toward this entirely absolutely necessary!!

But I see a likely structure emerging like this:

```bash
# My new approach for documenting
docs/
    features/
    tickets/
```

The `readwise_local_plus` dir:

```bash
cli.py
config.py
configure_logging.py
main.py  # needed?

intergrations/
    obsidian.py
    readwise.py
    roam.py

workflows/
    roam.py
    obsidian_export.py

highlights/
    readwise/
        db_operations.py
        models.py
        schemas.py
        types.py
        utils.py
    snipd/
        snipd.py
```

## To be evolved

In light of the `db_export.py` approach.

Some thoughts I've had along the way:

QUESTIONS: Where are the lines between "general" and "snipd" here?
    - `DbHls`, `HightlightFromDb` and `BookFromDB` are designed to be general
    - I think we want to automate them though...
    - So `HighlightFromDb` on instantiation:
        - Knows if it's a snipd highlight
        - Knows if what type of snipd highlight
        - Has a SnipdHighlight<Type>

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
