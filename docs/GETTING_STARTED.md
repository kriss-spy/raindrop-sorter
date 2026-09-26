# Getting Started and Operations

This is the canonical guide for installing, deploying, monitoring, and operating Raindrop Sorter. The project has no built-in dashboard; references to the dashboard below mean Modal's external web console.

For a local-only setup with no Modal deployment, use
[`LOCAL_GETTING_STARTED.md`](LOCAL_GETTING_STARTED.md).

## Prerequisites

- A [Raindrop.io](https://raindrop.io) account with an existing folder hierarchy
- A [Modal.com](https://modal.com) account
- [`uv`](https://docs.astral.sh/uv/) and Python 3.11
- ~500MB free disk space for the local bootstrap
- A Modal account allowed to run T4 GPU functions. Modal may require a payment method even when credits are available.

## 1. Get your Raindrop API token

1. Go to [Raindrop Settings → Integrations](https://app.raindrop.io/settings/integrations)
2. Click **Create new app**
3. Copy the **Test token**
4. Keep it secret — this is your `RAINDROP_TOKEN`

Use the raw token value. Do not prepend `Bearer`; the client adds that part of the authorization header.

## 2. Install dependencies

```bash
uv sync --python 3.11
```

Run project commands through `uv run`; activating `.venv` is optional. If an old environment contains broken Python symlinks, recreate it instead of trying to repair individual scripts:

```bash
uv venv --clear --python 3.11
uv sync --python 3.11
```

## 3. Set up environment variables

For local bootstrap, provide the token in the process environment or a local `.env` file:

```bash
RAINDROP_TOKEN="your-token-here" uv run python bootstrap.py --upload
```

Never commit the token. Modal receives its own copy in step 5.

## 4. Bootstrap the agent's memory

This step crawls your entire Raindrop library, builds embeddings, computes folder centroids, and extracts tag rules. It runs locally and uploads the resulting database to Modal.

```bash
RAINDROP_TOKEN="your-token-here" uv run python bootstrap.py --upload
```

What happens during bootstrap:
- Fetches your UI groups plus all collections (folders), preserving group-aware routes such as `Art/VOCALOID` and `Music/VOCALOID`
- Crawls every bookmark in every collection
- Generates text embeddings for each bookmark
- Computes folder centroids (mean embedding per folder)
- Extracts candidate tag rules (tags that appear frequently in specific folders)
- Runs bounded visual learning over historical covers so character and series
  labels can be associated with their existing destinations

The bootstrap aborts if two collections still resolve to the same canonical
route. This is a safety check: a duplicate path must never silently replace a
different collection ID in the resolver map.

Visual learning is intentionally bounded. By default it focuses on the 32
image-heaviest folders, analyzes at most 192 image-bearing bookmarks, and only
stops early after at least three passes per selected folder when a non-empty
rule set remains unchanged for 48 more samples. Audio/video cover art does not
consume this budget. Only high-purity rules with at least three examples are retained.
WD14 runs on the local CPU, so this phase does not incur an inference API bill;
runtime depends on the machine and can be reduced explicitly:

```bash
# Smaller/faster learning pass
uv run python bootstrap.py --vision-max-samples 96

# Skip historical visual learning entirely
uv run python bootstrap.py --vision-max-samples 0
```

The resulting `visual_learning.json` records the configured budget, analyzed
sample count, failures, learned-rule count, and why sampling stopped.

The weekly re-index preserves these learned visual rules but does not repeat
the historical cover scan, avoiding recurring Modal compute cost. Re-run the
local bootstrap when a newly created visual collection needs character-rule
learning; ordinary folder/centroid changes are still learned by the re-index.
- Saves everything to `./chroma_db/`
- Uploads the completed index to the `raindrop-sorter-vol` Modal Volume

Large libraries take longer and are constrained by Raindrop's shared API rate limit. The client waits for rate-limit resets and retries transient 5xx responses automatically.

## 5. Configure Modal secrets

First authenticate the CLI:

```bash
uv run modal setup
```

Then store the raw Raindrop token in the `main` environment:

```bash
uv run modal secret create -e main raindrop-token \
  RAINDROP_TOKEN="your-token-here"
```

Verify it exists:

```bash
uv run modal secret list -e main
```

## 6. Deploy to Modal

```bash
uv run modal deploy -e main app.py
```

This deploys the weekly reindex function. The historical watcher, resolver,
and vision entry points remain inert during the transition and cannot write
Raindrop lifecycle tags; local dashboard processing owns lifecycle state.

| Function | Runtime | Schedule/trigger | Purpose |
|----------|---------|------------------|---------|
| `reindex_worker` | CPU | Sunday 03:00 UTC | Rebuilds the index and learns from corrections |

The reindex owns the shared Raindrop request budget while it is active.

## 7. Verify it's working

After starting the local dashboard sorter, add a bookmark to `Unsorted`:

1. Open the local dashboard sorter controls.
2. Process a bounded batch.
3. Confirm the destination in Raindrop and inspect the decision in the journal.

## Monitoring

### Lifecycle state

Lifecycle state lives in `chroma_db/run-journal.sqlite`, not in Raindrop tags.
Use the dashboard or `local_journal.py` commands below to inspect current state
and history.

### Check deployment and recent logs

```bash
uv run modal app list -e main
uv run modal app logs raindrop-sorter -e main \
  --since 1h --timestamps --tail 200
```

To show only application errors:

```bash
uv run modal app logs raindrop-sorter -e main \
  --since 1h --source stderr --timestamps --tail 200
```

Empty stderr output means no application error was recorded during that interval. A rate-limit wait followed by success is normal; a terminal traceback or timeout needs attention.

### Check current containers

```bash
uv run modal container list -e main
```

Zero containers usually means the serverless app is idle between reindex calls,
not that it is broken. Confirm health using the deployment and recent logs;
normal sorting progress is visible in the local dashboard and journal.

## Updating after folder changes

If you create new folders or significantly reorganize your library, the agent will learn this during the next weekly re-index (Sunday 3 AM). If you want it to learn immediately:

```bash
# Invoke the reindex_worker on the deployed app directly
uv run python -c 'import modal; print(modal.Function.from_name("raindrop-sorter", "reindex_worker", environment_name="main").remote())'
```

Only start one manual reindex. The command waits for the remote result. If the terminal disconnects, check the deployed function's call history or application logs before retrying.

Logs report phase timings, request count, and time spent waiting for Raindrop rate-limit resets. The CPU worker allows up to two hours and stops billing when it finishes. The replacement index is built separately and swapped in near the end, so failures before that swap preserve the previous completed index.

## Troubleshooting

### "No collections found"

- Check your `RAINDROP_TOKEN` is correct
- Ensure your Raindrop account has at least one custom collection

### "No state" error in Resolver

- The Modal Volume does not contain a completed index
- Run `bootstrap.py --upload`, or complete a deployed `reindex_worker` call

### Broken `.venv` interpreter or `bad interpreter`

The environment points to a Python installation that no longer exists. Recreate the project environment:

```bash
uv venv --clear --python 3.11
uv sync --python 3.11
```

Then use `uv run ...` rather than invoking `.venv/bin/modal` directly.

### HTTP 429 or temporary 5xx responses

Raindrop applies one shared API rate limit across reads and writes. The client records the response headers, waits for the reset, and retries 429 and transient server failures. A log line announcing a wait or retry is expected. Escalate only if the invocation ends with an error or repeatedly times out.

### Pending items are not moving

1. Confirm `raindrop-sorter` is deployed with `modal app list`.
2. Check the last hour of logs for a terminal error.
3. Check active containers, remembering that zero is normal between runs.
4. Compare Raindrop pending-tag counts again after 15–30 minutes.
5. If a reindex is active, wait; other API consumers intentionally pause.

### Bookmarks stay in Unsorted
- This is expected for low-confidence items
- Check if the bookmark has a `cover` image — art without covers can't be vision-analyzed
- Look for `sorter-reviewed:*` tags; these are retried after weekly re-index

### GPU costs

- The T4 worker runs only when text heuristics are uncertain and the bookmark has a cover image.
- Modal may require a payment method before it will execute GPU functions; available credits and current pricing are account-dependent.
- Without GPU execution, text sorting can still run, but `sorter-pending-vision:*` items cannot complete the vision stage.

## Tests

Run the local test suite without permanently adding a test dependency:

```bash
uv run --with pytest pytest
```

## Local end-to-end canary

Before deploying a change, run one existing pending-vision bookmark through the real local pipeline. This downloads its cover, runs WD14 locally, and evaluates the result against the local index. It never updates Raindrop:

```bash
RAINDROP_TOKEN="your-token-here" uv run python local_canary.py \
  --bookmark-id 123456789 \
  --db-path chroma_db
```

The command succeeds only when the bookmark still has a `sorter-pending-vision:*` tag. Its JSON result includes `dry_run: true`, the number of vision tags, the proposed destination, and the resolver reason. A valid outcome can either propose a folder or deliberately leave the bookmark in Unsorted as `sorter-reviewed:*`.

Use this as a pre-deployment gate. After it passes, validate one separately controlled write canary before restoring scheduled backlog processing.

## Run one bookmark locally

The local runner executes the actual text, CPU vision, rule, and centroid
pipeline without Modal. It is read-only unless `--apply` is supplied:

For newer anime/game works that WD14 does not name reliably, first build a
local visual exemplar index from older bookmarks in the configured game
folders:

```bash
RAINDROP_TOKEN="your-token-here" uv run python visual_index.py \
  --db-path chroma_db
```

This operation is read-only. It reserves the latest 10 images in every target
folder as an untouched holdout, caches frozen CCIP embeddings after every
image, grows the older exemplar set in bounded rounds, and stops after the
holdout result plateaus. It only saves a confidence policy with zero observed
holdout misroutes. The resulting index is used by `local_run.py`; Modal workers
are unchanged. Images sourced from `Art/GAMES/BA/gaki` are learned and reported
as `Art/GAMES/BA`; the child collection is never a sorting destination.

To prepare a separate oldest-10-per-folder evaluation without replacing the
active visual index or its metrics:

```bash
RAINDROP_TOKEN="your-token-here" uv run python visual_index.py \
  --db-path chroma_db \
  --holdout-position oldest \
  --holdout-per-folder 10 \
  --report-only \
  --report explicit-art-oldest-50-report.html
```

```bash
RAINDROP_TOKEN="your-token-here" uv run python local_run.py \
  --bookmark-id 123456789 \
  --db-path chroma_db
```

Review the JSON destination and structured evidence first. To perform that exact class of
operation against the current live bookmark, rerun with `--apply`. The command
never deletes a bookmark or creates a folder; it can only update tags and move
the bookmark to an existing collection from the local index.

The local runner now uses the native two-step policy. Its JSON contains structured
`text_evidence`, `visual_evidence`, and a `confirmed`, `provisional`, `review`, or
`conflict` outcome; legacy resolver reason strings are no longer emitted.

To process a bounded queue batch locally, use `--batch-size`. Pending vision
items are selected first, followed by pending resolution and untouched Unsorted
items. This is also a dry run unless `--apply` is present:

```bash
RAINDROP_TOKEN="your-token-here" uv run python local_run.py \
  --batch-size 5 \
  --db-path chroma_db
```

Every local run now writes a structured trace to
`chroma_db/run-journal.sqlite` (or the path supplied with `--journal-path`).
Inspect the local history without a Raindrop token or model startup:

```bash
uv run python local_journal.py status
uv run python local_journal.py recent --limit 10
uv run python local_journal.py explain 123456789
```

The journal records the bounded bookmark snapshot, lifecycle events, structured
evidence, intended or completed action, and any failure. Dry runs record a
`planned` action and never write to Raindrop.

Before the first database-backed apply run, preview the lifecycle-tag migration:

```bash
RAINDROP_TOKEN="your-token-here" uv run python local_run.py \
  --migrate-lifecycle-tags
```

After reviewing the counts, add `--apply`. The migration persists any missing
legacy state before removing obsolete lifecycle tags, preserves user tags, and
does not move bookmarks.

## Uninstall

To stop the agent:

```bash
uv run modal app stop -e main raindrop-sorter
```

To completely remove:

```bash
uv run modal volume delete -e main raindrop-sorter-vol
uv run modal secret delete -e main raindrop-token
```

Your Raindrop bookmarks are never modified by these commands — they remain in your account.
