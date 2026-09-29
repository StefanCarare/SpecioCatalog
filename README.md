# Specio Catalog

Read-only viewer for the catalogue built by **Specio Identify**.

## Relationship to Specio Identify

Specio Catalog needs a catalogue, and **Specio Identify is what produces one** —
it is the only supported source. The two projects are meant to sit side by
side:

```
Desktop\
├── SpecioIdentify\      <- writes the catalogue
└── SpecioCatalog\        <- this one, reads it
```

**What is required:** the file `output\catalog.db` inside the Specio Identify
folder, together with the `species_profiles` and `catalog_items` tables. A
folder without it is rejected with a clear message rather than opened.

Specio Catalog looks for the sibling folder first (`..\SpecioIdentify`), then
falls back to the Desktop. It opens the catalogue **read-only** (`mode=ro`):
no row, table or schema is ever changed, and `test_readonly.py` fails if a
write ever goes through.

One detail worth knowing: the catalogue is in SQLite's **WAL** mode, and WAL
keeps two helper files next to the database — `catalog.db-wal` and
`catalog.db-shm`. SQLite recreates those for readers too, so opening the
catalogue leaves them there (and touches their timestamps) even though nothing
is written. If the Specio Identify folder has to sit on a read-only volume,
copy `output\catalog.db` elsewhere first and point Specio Catalog at that copy.

The chosen path is stored in `config\settings.txt`, which is per-machine and
not tracked by git.

## What it does

- Search the catalogue by scientific name, Romanian or English vernacular
  name, any name, or **full text in the species profile**.
- Filter by group (Plant, Bird, Insect, Mammal, ...).
- Browse photos, with date, location and file path.
- Read the full profile next to the photo, in panes you can drag.

**Determinator — free filtering.** Add criterion rows (a character and a
value). Species that don't match are excluded; species that simply have no
such character stay, marked as incomplete. Month criteria are compared as
spans, so "March" matches every period containing March, not only the one
spelled exactly that way.

**Determinator — guided key.** The same panel switches to a dichotomous key:
one trait at a time, most discriminating first, with the number of remaining
candidates on every option.

**🔎 Find by description.** Describe what you saw in your own words. A local
Ollama model turns it into filters and narrows the list. Criteria appear in
the Determinator, where you can correct them. Results only, no answer.

**💬 Ask the species.** Ask about the species on screen, or describe
something new. Filters are applied first, then the answer is built from the
profiles that survived them. Answers come **only** from the catalogue's own
profiles — never from the model's general knowledge — and technical terms get
a short parenthetical explanation. *New topic* starts a fresh subject, *Why?*
answers about the selected species, *Read* opens the conversation in a
narrower, comfortable window.

Both AI boxes use the model selected in the chat bar, and both need
[Ollama](https://ollama.com) running locally.

**Other.** Open the species folder, look it up in Catalogue of Life and
Wikipedia. `Ctrl + wheel` resizes the text everywhere, including the reading
window. The divider at the bottom makes the conversation taller. The **? Guide**
button documents all of this in the app, in Romanian and English.

## Requirements

- Python 3.10+ (tested on Windows)
- Pillow — `pip install -r requirements.txt`
- Optional, for the two AI boxes: Ollama, running locally

## Running it

Double-click `run.bat`, or:

```
pythonw gui\main_window.py
```

On first start the app asks for the **Specio Identify** project folder (the
one containing `output\catalog.db`). If it sits next to this one, it is
found automatically. The choice is saved in `config\settings.txt` and can be
changed from the top bar.

Diacritics are normalized for search: `Peliniță` is found by typing
`pelinita`.
