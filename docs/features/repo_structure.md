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