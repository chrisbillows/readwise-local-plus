# Planning CLI

## Current commands

```bash
rwlp sync # defaults to --delta
rwlp sync --delta
rwlp sync --all # don't use dumb ass!
rwlp sync --batch-id
rwlp 

rwlp list-invalids
rwlp e2e-data
rwlp rw-api
```

`sync --delta` is the key, simple - all new highlights, to all services

So - for the MVP Obsidian sync - we can build it to a runnable point, and leave it commented out as part of the delta call

## Thinking

- we don't need more batch sync options
- we don't know what's in a historic batch

## IDEA
- interact with highlights in the CLI
- target sync by highlight
- POSSIBLE: sync by configurable batch (worried this might be dangerous)

Can work by  a selection of saved filters (+ raw_sql option??)

- possible searches
    - podcasts / <podcast name>
    - articles / what? 

Will the real search most likely be from using Readwise itself?
    - e.g. the AI search etc.
    - And then I want to LOCATE via

I think I am drawn to this for testing more than real use???
