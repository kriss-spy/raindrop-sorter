# Getting Started

This guide walks you through setting up Raindrop Sorter from scratch and deploying it to Modal.

## Prerequisites

- A [Raindrop.io](https://raindrop.io) account with an existing folder hierarchy
- A [Modal.com](https://modal.com) account (free tier works)
- Python 3.11+
- ~500MB free disk space for the local bootstrap

## 1. Get your Raindrop API token

1. Go to [Raindrop Settings → Integrations](https://app.raindrop.io/settings/integrations)
2. Click **Create new app**
3. Copy the **Test token** (starts with `Bearer`)
4. Keep it secret — this is your `RAINDROP_TOKEN`

## 2. Install dependencies

```bash
# Create a virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

## 3. Set up environment variables

```bash
export RAINDROP_TOKEN="your_token_here"
```

Or create a `.env` file:

```bash
cp .env.example .env
# Edit .env and paste your token
```

## 4. Bootstrap the agent's memory

This step crawls your entire Raindrop library, builds embeddings, computes folder centroids, and extracts tag rules. It runs locally and uploads the resulting database to Modal.

```bash
python bootstrap.py
```

What happens during bootstrap:
- Fetches all your collections (folders) and their hierarchy
- Crawls every bookmark in every collection
- Generates text embeddings for each bookmark
- Computes folder centroids (mean embedding per folder)
- Extracts candidate tag rules (tags that appear frequently in specific folders)
- Saves everything to `./chroma_db/`

**Time estimate:** ~1-5 minutes depending on library size (100-5,000 bookmarks).

## 5. Configure Modal secrets

The deployed agent needs your Raindrop token. Store it as a Modal secret:

```bash
modal secret create raindrop-token RAINDROP_TOKEN="your_token_here"
```

Verify it exists:

```bash
modal secret list
```

## 6. Deploy to Modal

```bash
modal deploy app.py
```

This deploys four functions:

| Function | Schedule | Purpose |
|----------|----------|---------|
| `watcher` | Every 30 min | Polls Unsorted, tags new items |
| `resolver` | On-demand (spawned by watcher) | Applies sorting logic and moves bookmarks |
| `vision_worker` | On-demand (GPU) | Analyzes cover images when text is uncertain |
| `vision_cron` | Every 15 min | Safety net for any stuck vision items |
| `reindex` | Sunday 3 AM UTC | Rebuilds DB, learns from corrections |

## 7. Verify it's working

After deployment, add a bookmark to your `Unsorted` collection. Within 30 minutes:

1. Check Modal's [dashboard](https://modal.com/apps) for function runs
2. In Raindrop, look for tags like `sorter-pending-resolution` or `ai:sorted:2024-06-30` on the bookmark
3. The bookmark should move from `Unsorted` to the predicted folder

## Monitoring

### Check recent activity

In the Raindrop UI, filter by tag to see what the agent has done:

- `ai:sorted:*` — bookmarks the agent successfully sorted
- `sorter-reviewed:*` — bookmarks the agent wasn't confident about (stayed in Unsorted)
- `ai:new-rule-*` — bookmarks sorted by a newly learned rule

### Check Modal logs

```bash
modal logs raindrop-sorter
```

### Trigger a manual run

You can invoke functions manually for testing:

```bash
modal run app.py::watcher
modal run app.py::resolver
modal run app.py::reindex
```

## Updating after folder changes

If you create new folders or significantly reorganize your library, the agent will learn this during the next weekly re-index (Sunday 3 AM). If you want it to learn immediately:

```bash
# Run re-index manually
modal run app.py::reindex
```

## Troubleshooting

### "No collections found"
- Check your `RAINDROP_TOKEN` is correct
- Ensure your Raindrop account has at least one custom collection

### "No state" error in Resolver
- You haven't run `bootstrap.py` yet, or the Modal Volume is empty
- Re-run bootstrap and ensure it completes successfully

### Bookmarks stay in Unsorted
- This is expected for low-confidence items
- Check if the bookmark has a `cover` image — art without covers can't be vision-analyzed
- Look for `sorter-reviewed:*` tags; these are retried after weekly re-index

### GPU costs
- The Vision Worker only runs when text heuristics are uncertain AND the bookmark has a cover image
- Typical usage: 0-10 GPU invocations per day for a moderate art library
- Modal's free tier includes $30/month of GPU credits

## Uninstall

To stop the agent:

```bash
modal app stop raindrop-sorter
```

To completely remove:

```bash
modal volume delete raindrop-sorter-vol
modal secret delete raindrop-token
```

Your Raindrop bookmarks are never modified by these commands — they remain in your account.
