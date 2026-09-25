# Local Getting Started

This guide runs Raindrop Sorter entirely on your computer. It does not require
Modal and does not deploy a background service.

The local sorter uses the native two-step route:

1. identify a personal-interest destination from bookmark text and user tags;
2. independently verify visual bookmarks with WD14 and the local visual exemplar index;
3. produce a `confirmed`, `provisional`, `review`, or `conflict` decision;
4. optionally apply the destination and lifecycle tags to Raindrop;
5. save the complete trace in a local SQLite journal.

Commands are dry-run by default. Raindrop is changed only when you explicitly add
`--apply`.

## Prerequisites

- Python 3.11
- [`uv`](https://docs.astral.sh/uv/)
- A Raindrop.io account with an existing collection hierarchy
- A Raindrop API test token
- Enough free disk space for Python packages, the WD14 model, embeddings, and the
  optional visual exemplar index

Create a Raindrop API application under
[Settings → Integrations](https://app.raindrop.io/settings/integrations), then copy
its test token. Use the raw token; do not add a `Bearer` prefix.

## 1. Install the project

From the repository root:

```bash
uv sync --python 3.11
```

If the existing virtual environment points to a removed Python installation:

```bash
uv venv --clear --python 3.11
uv sync --python 3.11
```

All examples below use `uv run`, so activating `.venv` is optional.

## 2. Configure the token

Create a local `.env` file in the repository root:

```dotenv
RAINDROP_TOKEN=your-token-here
```

Do not commit `.env`. You can instead export `RAINDROP_TOKEN` in your shell if you
prefer.

## 3. Build the local routing data

Bootstrap reads the authenticated Raindrop collection tree and existing bookmark
assignments. It creates the folder map, learned tag rules, text embeddings, and
other local data under `chroma_db/`.

```bash
uv run python bootstrap.py \
  --db-path chroma_db \
  --vision-model-dir .cache/wd14
```

Do not add `--upload`; that option is only for Modal.

Bootstrap is read-only with respect to bookmarks. It may take a while for a large
library and will download the WD14 model on first use. Reusing
`.cache/wd14` avoids downloading that model for later bootstrap runs.

For a faster initial bootstrap, reduce or skip historical WD14 learning:

```bash
# Smaller historical sample
uv run python bootstrap.py \
  --db-path chroma_db \
  --vision-model-dir .cache/wd14 \
  --vision-max-samples 96

# Skip historical WD14 learning
uv run python bootstrap.py \
  --db-path chroma_db \
  --vision-max-samples 0
```

Skipping historical learning reduces visual character rules, but does not disable
the text route or future per-bookmark vision analysis.

## 4. Build the optional visual exemplar index

For image-heavy collections, build a calibrated index from older bookmarks already
assigned to your folders:

```bash
uv run python visual_index.py --db-path chroma_db
```

This command is read-only in Raindrop. It reserves holdout images, grows the index
in bounded rounds, and only saves thresholds that produced no wrong holdout
destinations. The resulting files remain local under `chroma_db/`.

This step is optional. Without it, visual verification can still use WD14 labels,
but it will not have nearest-exemplar evidence.

## 5. Migrate existing Unsorted lifecycle state

The native sorter distinguishes bookmarks it has not seen from bookmarks it has
reviewed. Preview a bounded backfill of currently untagged items in `Unsorted`:

```bash
uv run python local_run.py --backfill-unreviewed 50
```

The output lists the affected bookmark IDs and proposed tags. It does not modify
Raindrop. After reviewing it, apply the same bounded migration:

```bash
uv run python local_run.py --backfill-unreviewed 50 --apply
```

This only adds `sorter-unreviewed`; it does not move bookmarks. Repeat in bounded
batches until the command returns `"count": 0`.

## 6. Dry-run one bookmark

Use a real Raindrop bookmark ID:

```bash
uv run python local_run.py \
  --bookmark-id 123456789 \
  --db-path chroma_db \
  --model-dir .cache/wd14
```

The command reads the live bookmark, runs both evidence steps when applicable, and
prints a structured decision. It does not update the bookmark.

Important output fields:

- `action` — `move` or `review`;
- `target_folder` — proposed collection, or `null` when retained in `Unsorted`;
- `decision.outcome` — `confirmed`, `provisional`, `review`, or `conflict`;
- `decision.text_evidence` — matched user tag, hashtag, or text alias;
- `decision.visual_evidence` — WD14 labels, exemplar winner and runner-up, scores,
  margins, and acceptance thresholds;
- `attempt_id` — the matching record in the local journal;
- `applied` — `false` for a dry run.

Outcome behavior:

| Outcome | Destination | Final tag when applied |
| --- | --- | --- |
| `confirmed` | Move to the agreed destination | `ai:sorted:<date>` |
| `provisional` | Move, but flag for inspection | `sorter-needs-review:<date>` |
| `review` | Keep in `Unsorted` | `sorter-reviewed:<date>` |
| `conflict` | Keep in `Unsorted` | `sorter-reviewed:<date>` and `sorter-edge-case:conflict` |

Existing user tags are preserved. Transient `ai:wdtag-*`, `ai:sauce-*`, and obsolete
sorter lifecycle tags are removed when the final outcome is applied.

## 7. Dry-run a bounded queue batch

```bash
uv run python local_run.py \
  --batch-size 5 \
  --db-path chroma_db \
  --model-dir .cache/wd14
```

The batch is still read-only. Work is selected from `Unsorted` in lifecycle order,
including pending, `sorter-unreviewed`, and previously unseen items. Keep batches
small while evaluating routing quality.

## 8. Apply decisions

Apply a single reviewed dry run first:

```bash
uv run python local_run.py \
  --bookmark-id 123456789 \
  --db-path chroma_db \
  --model-dir .cache/wd14 \
  --apply
```

Then, if the evidence and results are satisfactory, apply a small batch:

```bash
uv run python local_run.py \
  --batch-size 5 \
  --db-path chroma_db \
  --model-dir .cache/wd14 \
  --apply
```

An apply run may update tags and move a bookmark to an existing collection. It
never deletes bookmarks and never creates collections. A direct
`--bookmark-id --apply` can target a bookmark outside `Unsorted`, so verify the ID
and dry-run it first.

## 9. Inspect the local journal

The default journal is `chroma_db/run-journal.sqlite`. Journal commands do not need
a Raindrop token and do not initialize the vision models.

For the browser interface, run:

```bash
uv run python local_dashboard.py --db-path chroma_db --open
```

The dashboard stays on your computer at <http://127.0.0.1:8765>. The default
**Latest status** view shows only the newest attempt for each Raindrop, so completed
retries and dry runs do not clutter the list. Choose **Attempt history** in the view
selector to show recent older attempts again. The dashboard also shows outcome counts,
search and filters, the evidence behind each decision, the action taken, a live
bookmark image preview, and the full event timeline. It is read-only: it cannot move
bookmarks or change tags. Image previews use the configured
`RAINDROP_TOKEN` to resolve the current cover through the localhost server; the token
and cover URL are not stored in the journal or sent to the browser. Leave the command
running while using the page, and press `Ctrl+C` to stop it.

If port 8765 is already in use, choose another one with `--port 8766`. Use
`--journal-path /another/path.sqlite` when the sorter writes its journal somewhere
other than the selected database directory.

The command-line views remain available for scripts and quick checks:

```bash
# Latest attempt count by lifecycle phase
uv run python local_journal.py --db-path chroma_db status

# Recent attempts
uv run python local_journal.py --db-path chroma_db recent --limit 10

# Complete trace for the latest attempt on one bookmark
uv run python local_journal.py --db-path chroma_db explain 123456789
```

Use `--journal-path /another/path.sqlite` with both `local_run.py` and
`local_journal.py` to store the journal elsewhere.

## 10. Refresh after reorganizing Raindrop

Re-run the local bootstrap after creating, renaming, deleting, or substantially
reorganizing collections:

```bash
uv run python bootstrap.py \
  --db-path chroma_db \
  --vision-model-dir .cache/wd14
```

Rebuild the visual exemplar index when visual collection assignments have changed
enough to affect its training examples:

```bash
uv run python visual_index.py --db-path chroma_db
```

Always dry-run a small batch after refreshing either artifact.

### Refresh character aliases from CloudNotes

The local router ships with an Art-only character alias snapshot. To rebuild it
after changing the corresponding voicebank, PJSK, Touhou, VTuber, anime, or
Umamusume notes in CloudNotes, run:

```bash
uv run python scripts/sync_cloudnotes_character_aliases.py \
  --vault /home/krisspy/obsidian/cloudnotes
```

The command reads the vault and rewrites `src/character_aliases.json`; it does not
modify the vault. Voicebanks listing Vocaloid in their `platforms` frontmatter go
to `Art/VOCALOID`; known incomplete vault metadata and spelling differences are
handled by small, tested corrections in the sync script. Other voicebanks go to
`Art/VOICEBANKS`. Routing destinations outside the `Art/` collection group are
intentionally excluded for now.

Anime character notes are treated as personal aliases, not as a complete cast
list. `src/anime_character_aliases.json` supplies audited main characters and
canonical Japanese/Latin spellings when the vault is sparse or uses only a
translated filename. The provenance audit is recorded in
`docs/research/anime-character-alias-audit.md`.

## Troubleshooting

### `RAINDROP_TOKEN is required`

Confirm `.env` exists in the repository root and contains the raw token, or export
`RAINDROP_TOKEN` in the shell running the command.

### Local index is incomplete

Run the bootstrap command from step 3. A usable local index requires at least
`folder_id_map.json` and `tag_rules.json` under the selected `--db-path`.

### Model download restarts or stalls

Use the same persistent path for both commands:

```bash
uv run python bootstrap.py --vision-model-dir .cache/wd14
uv run python local_run.py --batch-size 1 --model-dir .cache/wd14
```

The WD14 model is large; an empty temporary model directory causes another download.

### Bookmark remains in `Unsorted`

Inspect `decision.text_evidence`, `decision.visual_evidence`, and the journal trace.
`review` and `conflict` deliberately remain in `Unsorted`. Missing or inaccessible
image media produces unavailable visual evidence rather than a forced destination.

### Proposed destination is missing

The sorter refuses to create a collection or silently choose a similar name. Refresh
the local data after changing the Raindrop collection tree.

### Tests

```bash
uv run --with pytest pytest
```

## Current local limitation

The independent, versioned Obsidian-backed Personal Interest Index described in
`ARCHITECTURE.md` is not implemented yet. The current local build seeds text rules
and visual exemplars from existing Raindrop tags and Art collection assignments,
plus the curated aliases in the codebase. These inputs produce native structured
evidence and pass through the native decision table; the legacy resolver compatibility
adapter is not used.
