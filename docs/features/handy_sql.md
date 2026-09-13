## Handy sql

Handy for digging into the db from the command line.

Remember:

```bash
sqlite3 <db>
.tables
.headers on
```

```bash
select h.* from highlights as h join books as b on b.user_book_id = h.book_id where h.batch_id = 133;
```


Longer query example:

```bash
SELECT h.*
FROM highlights AS h
JOIN books AS b ON b.user_book_id = h.book_id
WHERE b.category = 'podcasts'
AND b.source = 'snipd'
AND b.source_url IN (
    SELECT batch_b.source_url
    FROM highlights AS batch_h
    JOIN books AS batch_b
        ON batch_b.user_book_id = batch_h.book_id
    WHERE batch_h.batch_id = :batch_id
        AND batch_b.category = 'podcasts'
        AND batch_b.source = 'snipd'
)
ORDER BY h.book_id, h.highlighted_at, h.id;
```
