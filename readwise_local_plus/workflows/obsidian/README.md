# Guide to using the Obsidian Workflow

By batch, writes selected highlights to Obsidian.

Current selection is by `category` via the `REQUIRED_CATEGORY_DIRS` constant in [obsidian.py](obsidian.py).

The current export is just podcasts.

## Vault Config

Valut configuration is set [here](../../config.py) via:

- `self.obsidian_vault_path`: absolute `Path` to the vault
- `self.obsidian_rw_dir`: Named dir as a `Path` e.g. `self.obsidian_vault_path / "readwise"`

## Podcast Save Locations

For podcasts, Readwise (and therefore our sqlitedb uses)

- "author" = the podcast name (e.g. "The Rest if History")
- "title" = the episode title

Podcasts are therefore saved as `<obsidian_vault_path>/<obsidian_rw_dir>/<author>/<title>`

> ⚠️ NOTE : "author" can be transformed via the `PODCAST_TITLE_MAP` in [obsidian.py](obsidian.py)
> <br> E.g.  *"The Rest Is History"* to *"Rest Is History"*.




