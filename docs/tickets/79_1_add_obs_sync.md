# Ticket notes

Because writing all this shit in GitHub is dumb.

## Don't mess with cli.py args.all

There is a comment there but you will break `rwlp sync` and we're still using that locally from this WIP copy. (Because laziness).

## Current progress

Test with 

```shell
rwlp sync --batch-id <batch>
```

- I've been testing with batch `113` and `112` (and previously `99`).
- `cli.py` calls  `write_batch_to_obsidian` from `obsidian.py`.

- So we are splitting highlights effectively it seems
- Working through formatting
    - HL Title is isolated and formatted
    - summary doesn't need formatting
- So issue is the quotes

For format, was considering nesting but not sure it's better.
Going with this is as the desired format:

[Example Format](79_examples.md#highlight-format])

- Now we have split transcripts into speaker / text like this:

```shell
['Dominic Sandbrook', "quote...", 'speaker', "quote", 'speaker', "quote"]
```

- Still working in functions
- Refactored the code into a proper loop
- Have dividers for possible splitting into functions/methods
- Should now create a decent export for a podcast episode

Have now added basic front matter.

- Readwise does not get show notes / AI episodes / chapter
  - They are in the snipd link, so maybe scrape?? 
  - Show notes on their own prob quick... but will need formating per podcast
 

Scope explosion!! 
  - Explored adding show notes (originally also chapter headings)
  - requires a webscraping step
          - and should be stored in the db as additional metadata
          - which should really be a refactor
  - then a display step

Ideally, at least two if not three tickets

Issue with closing mvp functionality is the CLI
 - so perhaps we reconfigure CLI... although again, feels like another ticket


Have now split into three ticketsbranches defined in [](../features/snipd_int.md#phase-1--ticket-79---mvp) etc.

- REMAINGING ISSUES FOR 79 / MVP:
  - ✅need to sanatise front matter
  - ✅full stop for last split quote 

Are quotes "accurate"?
- No - there is data loss...

✅ Ok - multiple quote issue is now fixed.


Q: what is splitting on "dumb" full stops doing on question marks, exclaimation points or ellpsis etc.?
- question marks end up mid sentence, reads ok
- ellipsis get chopped... annoying but worth fixing?

✅ Added handling for question marks, ellipsis and full stops...

It's still not perfect (e.g. J.D. Vance) - replace with ntlk or codex calls when we use 
those for importing

✅ Going to keep punctuation inline

✅ Added readwise page for the raw quotes

✅ Added append logic

✅ Make snipd only - there is some old "other" podcast junk in batch 1

Make work for older formats

[Current known hl formats](79_examples.md#current-known-hl-formats)


[Front matter example from clippings](79_examples.md#front-matter-sample-from-clippings)

[Transcript samples](79_examples.md#transcript-samples)


