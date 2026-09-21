# Getting Started and Operations

This is the canonical guide for installing, deploying, monitoring, and operating Raindrop Sorter. The project has no built-in dashboard; references to the dashboard below mean Modal's external web console.

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

This deploys five functions:

| Function | Runtime | Schedule/trigger | Purpose |
|----------|---------|------------------|---------|
| `watcher` | CPU | Every 30 minutes | Discovers new Unsorted items and starts resolution |
| `resolver` | CPU | Spawned on demand | Resolves a bounded batch and continues while work remains |
| `vision_cron` | CPU | Every 15 minutes | Dispatches a bounded batch of pending vision items |
| `vision_worker` | T4 GPU | Spawned on demand | Analyzes one cover image |
| `reindex_worker` | CPU | Sunday 03:00 UTC | Rebuilds the index and learns from corrections |

The watcher and vision schedules are offset so they do not normally hit Raindrop simultaneously. A reindex temporarily pauses the other Raindrop API consumers and owns the shared request budget.

## 7. Verify it's working

After deployment, add a bookmark to your `Unsorted` collection. Allow at least one watcher cycle:

1. Check the external [Modal web console](https://modal.com/apps) or use the CLI health checks below.
2. In Raindrop, look for a state tag on the bookmark.
3. A confident bookmark moves to the predicted folder; a low-confidence bookmark remains in Unsorted with a `sorter-reviewed:YYYY-MM-DD` tag.

## Monitoring

### State tags in Raindrop

In the Raindrop UI, filter by tag to see what the agent has done:

- `sorter-pending-resolution` — waiting for the CPU resolver
- `sorter-pending-vision:*` — waiting for a GPU vision worker
- `ai:sorted:*` — successfully sorted
- `sorter-reviewed:*` — low confidence; intentionally left in Unsorted
- `ai:new-rule-*` — bookmarks sorted by a newly learned rule

Dated tags use the UTC date. For backlog progress, compare pending-tag counts 15–30 minutes apart; a single count is not enough to distinguish active draining from a stall.

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

Zero containers usually means the serverless app is idle between scheduled calls, not that it is broken. Confirm health using all three signals: the deployment exists, recent logs have no terminal error, and Raindrop backlog counts move over time.

### Manual runs

Do not manually start `watcher`, `resolver`, or `vision_cron` during normal operation. The deployed schedules and self-draining batches orchestrate them, while `modal run app.py::...` creates a separate ephemeral app that can make the Modal console confusing.

## Updating after folder changes

If you create new folders or significantly reorganize your library, the agent will learn this during the next weekly re-index (Sunday 3 AM). If you want it to learn immediately:

```bash
# Invoke the reindex_worker on the deployed app directly
uv run python -c 'import modal; print(modal.Function.from_name("raindrop-sorter", "reindex_worker", environment_name="main").remote())'
```

Only start one manual reindex. The command waits for the remote result. If the terminal disconnects, check the deployed function's call history or application logs before retrying.

While reindexing, the other functions pause their Raindrop API activity so the rebuild owns the account's shared request budget. Logs report phase timings, request count, and time spent waiting for Raindrop rate-limit resets. The CPU worker allows up to two hours and stops billing when it finishes. The replacement index is built separately and swapped in near the end, so failures before that swap preserve the previous completed index.

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

```bash
RAINDROP_TOKEN="your-token-here" uv run python local_run.py \
  --bookmark-id 123456789 \
  --db-path chroma_db
```

Review the JSON destination and reason first. To perform that exact class of
operation against the current live bookmark, rerun with `--apply`. The command
never deletes a bookmark or creates a folder; it can only update tags and move
the bookmark to an existing collection from the local index.

To process a bounded queue batch locally, use `--batch-size`. Pending vision
items are selected first, followed by pending resolution and untouched Unsorted
items. This is also a dry run unless `--apply` is present:

```bash
RAINDROP_TOKEN="your-token-here" uv run python local_run.py \
  --batch-size 5 \
  --db-path chroma_db
```

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
