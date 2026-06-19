# Raindrop Sentinel

An autonomous serverless agent that organizes your [Raindrop.io](https://raindrop.io) bookmarks for you.

It monitors your `Unsorted` collection, learns your personal folder hierarchy from existing bookmarks, and automatically moves new items to the right place — no manual dragging required.

## How it works

1. **Learn.** The agent embeds your existing sorted bookmarks into a vector database and builds folder centroids. It also auto-discovers character/series tag rules from your current organization.
2. **Watch.** A cron job polls your `Unsorted` collection every 30 minutes.
3. **Sort.** New bookmarks are analyzed through a deterministic pipeline:
   - **Exact tag rules** — recognizes characters from cover images (e.g., `hatsune_miku` → `Art/Vocaloid/Hatsune Miku`)
   - **Series rules** — groups same-series multi-character art into series folders
   - **Crossover fallback** — ambiguous art lands safely in `Art/ANIME`
   - **Centroid matching** — everything else is matched against folder embeddings; low-confidence items stay in `Unsorted` for your review
4. **Improve.** A weekly re-index updates the vector database as your library grows and learns from your manual corrections.

## Architecture

- **Watcher** (CPU, cron) — polls Raindrop, applies text heuristics, queues vision jobs
- **Vision Worker** (GPU, on-demand) — runs WD14 Tagger on cover images, performs advisory SauceNAO lookups
- **Resolver** (CPU, on-demand) — applies all decision logic and moves bookmarks via the Raindrop API

All state is stored in a ChromaDB vector database on a persistent Modal Volume. The agent uses Raindrop tags as its state machine — no separate database needed.

## Tech Stack

| Component | Technology |
|-----------|------------|
| Hosting | [Modal.com](https://modal.com) (serverless Python) |
| Vector DB | ChromaDB |
| Embeddings | `sentence-transformers/all-mpnet-base-v2` |
| Vision | WD14 Tagger (ONNX on NVIDIA T4) |
| Advisory | SauceNAO API |
| Source API | Raindrop.io REST API |

## Project Status

**Design complete, implementation in progress.**

The full architecture and design decisions are documented in [`docs/PRD.md`](docs/PRD.md).

## Design Principles

- **Autonomous first.** Unconfident items stay in `Unsorted`; everything else is sorted without asking.
- **Never delete.** The agent only moves bookmarks — it never removes them.
- **Never auto-create folders.** Your folder structure stays under your control.
- **No LLMs.** All decisions are deterministic rules and vector similarity. No hallucinations, no API tokens for language models.
- **Free tier friendly.** GPU is only invoked when visual analysis is actually needed. Text inference runs on CPU.

## Setup (coming soon)

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Bootstrap the agent's memory from your existing library
python bootstrap.py

# 3. Deploy to Modal
modal deploy app.py
```

## Credits

Original concept brainstormed with [Gemini](https://gemini.google.com/share/5604d377d9da).
