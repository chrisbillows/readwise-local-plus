# 5th April

- dn will always exist
  - but it will not always be the parent
  - if the header exists, then   


Are we trying to do too much, we are creating only EXPORT nodes, we could create empty nodes?

{}



# 4th april

don't forget 

RW HEADER
- need to check if rw header alraedy exists
- need to add readwise header itself
- need to check if book already exists


# 3rd april

So issue with the fact we need bits of hls and books to make the headings!?!

Plan is to add links BENEATH the HLs in their own section

- [[Readwise Highlights]]
  - Book_1
      - Hl_1
  etc
- Readwise Links
  - ((Book_1))
    - Link_1 Link_2 Link_3

Roam Backend API docs
https://roamresearch.com/#/app/developer-documentation/page/IEmaIxzTU



# 2nd April

URLs
------
in highlights: url = original source, i.e. tweet, reader for times articles etc
in books     :  

user_book_id|batch_id|title|is_deleted|author|readable_title|source|cover_image_url|unique_url|summary|category|document_note|readwise_url|source_url|external_id|asin|validated|validation_errors

we are going to need all this - so we need a book obj


# 30th March

have a basic graph represenation
next q is how do we most easily iterate over that
creating the batch action body
presumably it's some kind of recursion

so... i think this is so much better because IT NEVER NEEDS TO BE GROUPED?




# 28th March

Working in `roam_daily_note_3.py`

- added roam daily note existence check (logic is currently WRONG!)

Grouping still an issue
- considered NOT grouping...
- create seperate list of daily notes and books
- then check existence of daily notes
- but so much wasted looping

Chat GPT suggested a composite key but not sure that works

Steps
- recieve the batch_id
- query DB, get back list of highlights `<class 'readwise_local_plus.models.Highlight'>`
- convert that to a dataclass (remove session dependency)

THE BIG ISSUE - is this payload by book by day
we want to be able to flexibly format THIS

```python
@dataclass
def formatting_target():
    header

```




# 26th March

Start with 
--> batch_id

Query DB, get back
--> list of Highlights
`<class 'readwise_local_plus.models.Highlight'>`

Which we can use like:
```bash
dict_keys(['_sa_instance_state', 'id', 'created_at', 'is_deleted', 'batch_id', 'updated_at', 'readwise_url', 'text', 'external_id', 'validated', 'location', 'end_location', 'validation_errors', 'location_type', 'url', 'note', 'is_favorite', 'color', 'is_discard', 'book_id', 'highlighted_at', 'book'])

>>> x.book
Book(user_book_id=19764647, title='Tweets from GRITCULT', highlights=4)
```

What do we actually use?
- Book - Title
- Book - Id
- Created Date
- is_deleted


Our eventual output is

```json
"action": "batch-actions",
  "actions": [
     {
       "action": "create-block",
       "location": {
         "order": "last",
         "parent-uid": "ERwJmpO5Y"
       },
       "block": {
         "string": "Tweet Thread From Tim Ferriss #[[tweets]] #[[rw]] [↗️](https://x.com/tferriss/tatus/2036266171121467752/?rw_tt_thread=True)",
         "uid": -1,
         "heading": 3
       }
     },
     {
       "action": "create-block",
       "location": {
         "order": "last",
         "parent-uid": -1
       },
       "block": {
         "string": "the point of investing is ultimately to improve your quality of life [↗️]https://read.readwise.io/read/01kmgh6bkd0gxkqwe8gtf0n830)",
         "uid": -2
       }
```