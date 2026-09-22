# Raindrop Sorter

An autonomous serverless agent that organizes your [Raindrop.io](https://raindrop.io) bookmarks for you.

It monitors your `Unsorted` collection, learns your personal folder hierarchy from existing bookmarks, and automatically moves new items to the right place — no manual dragging required.

## How it works

1. **Learn.** The agent embeds your existing sorted bookmarks, builds folder centroids, and performs a bounded local vision sample to discover high-purity character/series rules from your current organization.
2. **Watch.** A cron job polls your `Unsorted` collection every 30 minutes.
3. **Sort.** New bookmarks are analyzed through a deterministic pipeline:
   - **Exact tag rules** — recognizes characters from cover images (e.g., `hatsune_miku` → `Art/Vocaloid/Hatsune Miku`)
   - **Series rules** — groups same-series items into group-aware destinations, using image/audio/video modality when names repeat across Art, Music, and Video
   - **Localized text aliases** — recognizes distinctive character and franchise names in Chinese, English, Japanese, and Korean before vision
   - **Visual exemplars** — the local runner compares newer art with older images already sorted into the user's game folders
   - **Crossover fallback** — ambiguous art lands safely in `Art/ANIME`
   - **Centroid matching** — everything else is matched against folder embeddings; low-confidence items stay in `Unsorted` for your review
4. **Improve.** A weekly re-index updates the vector database as your library grows and learns from your manual corrections.

## Architecture

- **Watcher** (CPU, every 30 minutes) — discovers new items and starts the resolution pipeline
- **Resolver** (CPU, on-demand) — processes bounded batches and moves confident matches
- **Vision Cron** (CPU, every 15 minutes) — drains pending vision work in bounded batches
- **Vision Worker** (T4 GPU, on-demand) — runs WD14 Tagger when text heuristics are uncertain
- **Reindex Worker** (CPU, weekly) — rebuilds embeddings and learns from manual corrections

All state is stored in a ChromaDB vector database on a persistent Modal Volume. The agent uses Raindrop tags as its state machine — no separate database needed.

## Tech Stack

| Component | Technology |
|-----------|------------|
| Hosting | [Modal.com](https://modal.com) (serverless Python) |
| Vector DB | ChromaDB |
| Embeddings | `sentence-transformers/all-mpnet-base-v2` |
| Vision | WD14 Tagger (ONNX on NVIDIA T4) |
| Local visual exemplars | CCIP (frozen ONNX encoder) |
| Source API | Raindrop.io REST API |

## Project Status

**Core pipeline complete.**

- ✅ Autonomous sorting (text + vision)
- ✅ Weekly re-index with passive learning
- ✅ Raindrop rate-limit handling and transient-server-error retries
- ✅ Bounded, self-draining CPU and vision queues
- ✅ Bounded, resumable local visual exemplar indexing with untouched holdouts
- ✅ Audit trail via Raindrop tags
- ⏳ SauceNAO advisory integration (issue #4)
- ⏳ Structured logging & observability (issue #4)

The full architecture and design decisions are documented in [`docs/PRD.md`](docs/PRD.md).

## Design Principles

- **Autonomous first.** Unconfident items stay in `Unsorted`; everything else is sorted without asking.
- **Never delete.** The agent only moves bookmarks — it never removes them.
- **Never auto-create folders.** Your folder structure stays under your control.
- **No LLMs.** All decisions are deterministic rules and vector similarity. No hallucinations, no API tokens for language models.
- **Usage-conscious.** GPU is invoked only when visual analysis is needed; text inference and orchestration run on CPU.

## Quick Start

```bash
# 1. Create/sync the Python 3.11 environment
uv sync --python 3.11

# 2. Authenticate the Modal CLI
uv run modal setup

# 3. Put the raw Raindrop test token in Modal (do not include "Bearer ")
uv run modal secret create -e main raindrop-token \
  RAINDROP_TOKEN="your-token-here"

# 4. Bootstrap the index locally and upload it to the Modal Volume
RAINDROP_TOKEN="your-token-here" uv run python bootstrap.py --upload

# 5. Deploy the scheduled application
uv run modal deploy -e main app.py
```

See [`docs/GETTING_STARTED.md`](docs/GETTING_STARTED.md) for setup, health checks, reindexing, and troubleshooting.

## Credits

Original concept brainstormed with [Gemini](https://gemini.google.com/share/5604d377d9da).
