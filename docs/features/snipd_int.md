# Planning snipd integration

- initially only be utilised by Obsidian sync
- sync into an Obsidian vault, defined in the user config 
- sync into a readwise folder in Obsidian, defined in the user config
- sync into a hardcoded `podcasts` folder in the readwise folder
- runs as part of `rwlp sync --delta`

## Working approach

Do not commit to a design until all phases complete.

- i.e. no premature abstraction into classes etc.
- no merging into the Roam integration
- duplicate rather than generalise

## Out of scope

- No writing back to the db current Obsidian state
    - YAGNI or move toward selective syncing per [expanding_cli](expanding_cli.md)


## Repo structure

Vague guiding structure is [here](repo_structure.md)

New files for end of this feature:

```shell
readwise_local_plus/
    
    workflows/
        obsidian/
            obsidian.py  # read from db and write to obs
            format_addl_metadata.py # called by obs_export.py
    
    snipd.py # fetch additional metadata and write to db
```

## Phases

### Phase 1 / ticket 79 - MVP

- logic to fetch from the db (duplicate roam fetching classes etc.)
- processing logic
    - figure out formatting db output

Details [here](../tickets/79_1_add_obs_sync.md)

### Phase 2 / ticket 81 - capture additional metadata

- get show notes and chapter headings
- write to readwise local
- ensure this is extremely API friendly e.g. handful of scrapes per minute with
  a break, and back off etc.
- run for all podcasts for initial db population

Reminder for ntlk: 

- nltk needs to be pinned at 3.9.2  for dev, a new security feature to prevent shadowed dependencies doesn't work with an editable install


### Phase 3 / ticket 82 - process and format additonal metadata

- use codex locally for extracting useful text from show notes
- use HTML and playwright screenshot to create a "nice" header for each note

### Phase 4 / ticket 83

- intergrate all the pieces
- refactor as sensible (e.g. combine with roam code, possibly?)
- run (manually, via a disposable bash script) for all podcast batches

