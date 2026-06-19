# Raindrop Sentinel — PRD

**Status:** `ready-for-agent`

---

## Problem Statement

The user maintains a large Raindrop.io bookmark library (~1,000+ items) organized into a personal folder hierarchy. New bookmarks arrive in the `Unsorted` collection and must be manually dragged into the correct folders. This manual sorting is tedious, repetitive, and scales poorly as the library grows. The user wants an autonomous agent that learns their personal organization style from existing sorted bookmarks and applies it to new incoming items without human intervention.

## Solution

**Raindrop Sentinel** is a serverless agent deployed on Modal.com that monitors the Raindrop.io `Unsorted` collection, performs visual and semantic analysis, and automatically moves bookmarks into the user's existing folder hierarchy. It learns the user's organization style by embedding existing sorted bookmarks into a vector database and matching new items against folder centroids. The system is fully autonomous: unconfident items stay in `Unsorted` for human review, but everything else is sorted automatically.

## User Stories

1. As a Raindrop.io user, I want new bookmarks in `Unsorted` to be automatically categorized into my existing folders, so that I don't have to manually drag them.
2. As a user with an anime art library, I want the agent to recognize characters from bookmark cover images and sort them into character-specific folders, so that my art collection stays organized without manual tagging.
3. As a user who saves crossovers and multi-character art, I want ambiguous images to land in a safe catch-all folder (`Art/ANIME`) rather than being forced into a wrong specific folder, so that I can review them later.
4. As a user who organizes by series, I want group shots of characters from the same series to land in the series folder, so that related art stays together.
5. As a user who creates new folders, I want the agent to learn about them automatically during the weekly re-index, so that I don't have to reconfigure the agent.
6. As a user who manually moves a mis-sorted bookmark, I want the agent to detect the correction and stop using the bad rule, so that the same mistake doesn't repeat.
7. As a user on Modal's free tier, I want the system to stay within $0/month by avoiding unnecessary GPU usage, so that I don't pay for bookmark organization.
8. As a user, I want to see which bookmarks were recently sorted by the AI, so that I can spot-check accuracy without hunting through every folder.
9. As a user with nested folders, I want parent folders to be valid sorting destinations, so that general items don't get forced into overly specific subfolders.
10. As a user, I want the system to never delete my bookmarks, even if the URL is dead, so that I don't lose references I meant to keep.
11. As a user, I want the system to never auto-create folders in my Raindrop library, so that my folder structure stays under my control.
12. As a user, I want ambiguous bookmarks to stay in `Unsorted` rather than being dumped into a wrong folder, so that I remain the final arbiter for edge cases.
13. As a user with a mix of art, videos, and articles, I want the system to handle non-art bookmarks via text analysis alone, so that GPU time is only spent when visual analysis is actually needed.
14. As a user, I want the initial setup to be a single local script that seeds the agent's memory from my existing library, so that the agent is useful from day one.
15. As a user, I want the weekly re-index to happen automatically without my intervention, so that the agent continuously learns as my library evolves.
16. As a user, I want the system to retry sorting previously rejected bookmarks after the weekly re-index, so that new reference data can unlock sorting for old ambiguous items.
17. As a user, I want bad auto-extracted rules to be automatically disabled after repeated manual corrections, so that the agent doesn't persistently mis-sort items.
18. As a user, I want AI-generated tags to be cleaned up after sorting, so that my Raindrop tag cloud doesn't get cluttered with transient metadata.
19. As a user, I want the system to gracefully handle dead cover images by falling back to text-only analysis, so that a broken image link doesn't break the entire pipeline.
20. As a user, I want to know when the agent encounters an API failure, so that I can diagnose if Raindrop is down or rate-limiting the agent.

## Implementation Decisions

### Architecture

- **One Modal App** with three serverless functions sharing a persistent `modal.Volume`:
  - `watcher` (CPU, cron every 30 min): polls Raindrop `Unsorted`, applies text heuristics, tags items needing vision, spawns Vision Worker asynchronously.
  - `vision_worker` (GPU, on-demand): downloads cover image via Raindrop's `cover` URL, runs WD14 Tagger and SauceNAO advisory lookup, tags results, spawns Resolver.
  - `resolver` (CPU, on-demand): applies all deterministic decision logic and updates bookmark folder via Raindrop API.

### Decision Pipeline (Resolver)

The Resolver is the single source of truth for all sorting decisions. It executes a strict priority order:

1. **Exact Tag Rules:** If WD14 tags contain a character tag that maps to a known exact rule (e.g., `hatsune_miku` → `Art/Vocaloid/Hatsune Miku`), sort there immediately.
2. **Series Rules:** If WD14 tags contain multiple characters from the same series (detected via series tags like `vocaloid`, `touhou`), sort to the series folder (e.g., `Art/Vocaloid`).
3. **Crossover Fallback:** If characters are from different series or the image is otherwise ambiguous, sort to `Art/ANIME`.
4. **Folder Centroid Matching:** If no character/series match applies, embed the bookmark's text features and compare against pre-computed folder centroids. Sort to the nearest centroid only if the gap between 1st and 2nd place exceeds the relative confidence threshold. Otherwise, leave in `Unsorted`.

### Text Embedding Strategy

- **Model:** `sentence-transformers/all-mpnet-base-v2` (768-dim, CPU inference).
- **Input template (truncated bottom-up):**
  ```
  Title: {title}
  Domain: {domain}
  Tags: {wd14_tags} {user_tags}
  Description: {description}
  ```
  Description is truncated first to stay within token limits, protecting title and tags.

### Vision Worker Trigger

- **Funnel architecture:** Text-only rules run first. GPU vision is only invoked when:
  - Text heuristics return low confidence (no exact tag rule, ambiguous centroid match)
  - AND the bookmark has a `cover` image URL from Raindrop
- The Raindrop `cover` URL is the **only** image source; no page scraping or fallback fetching.

### Memory & Learning

- **Vector Database:** ChromaDB stored on Modal Volume (`chroma_db/`).
- **Folder Centroids:** Computed weekly during re-index. Each folder's centroid is the mean embedding of all bookmarks in that folder's subtree (recursive contribution: subfolder bookmarks feed parent centroids). Both leaf and parent folders compete as sorting destinations.
- **Passive Learning Loop:**
  - Weekly re-index (Sunday 3 AM) rebuilds the DB via atomic swap (`chroma_db_new/` → `chroma_db/`).
  - Detects manual corrections by comparing `last_seen_folder` metadata to current folder.
  - Auto-extracts candidate exact tag rules from existing bookmarks (tag frequency ≥ 3 per folder).
  - Validates rule targets against live folders; disables rules pointing to missing folders.
  - Auto-deletes rules after 3 manual-move mismatches are detected.
- **Re-index retry logic:** Old `sentinel-reviewed:<date>` tags are stripped during re-index, causing the Watcher to retry previously rejected bookmarks against the updated vector space.

### State Machine via Raindrop Tags

The system uses Raindrop tags as its sole state ledger (no separate database):

- `sentinel-pending-vision:<date>` — Watcher tagged, awaiting Vision Worker.
- `sentinel-pending-resolution` — Vision Worker tagged, awaiting Resolver.
- `sentinel-reviewed:<date>` — Resolver attempted, item stayed in `Unsorted` (low confidence).
- `ai:new-rule-<rule_name>` — Sorted by a newly auto-extracted rule (audit trail).
- `ai:sorted:YYYY-MM-DD` — Successfully sorted by any path (audit trail).

Operational tags (`sentinel-reviewed`, `ai:new-rule-*`, `ai:sorted:*`) are preserved. Transient extraction tags (`ai:wdtag-*`, `ai:sauce-*`) are stripped after sorting.

### SauceNAO Integration

- **Advisory only.** Adds metadata tags (`ai:sauce-*`) to bookmarks for searchability.
- **Never drives sorting decisions.** If SauceNAO fails, returns nothing, or rate-limits, the pipeline continues on WD14 tags alone.

### Error Handling & API Resilience

- Raindrop API failures during sorting are logged and fail silently; the bookmark stays in `Unsorted` and is retried by the next Watcher cycle (30 min later).
- Vision Worker image download failures (dead cover URL) fall back to text-only centroid matching.
- No exponential backoff or dead-letter queue; simplicity is prioritized for a personal tool.

### Secrets & Credentials

- Raindrop API token and SauceNAO API key stored as Modal Secrets.
- Local bootstrap script reads from `.env` file for initial crawling.

### Bootstrap

- A local `bootstrap.py` script runs before first deploy.
- Crawls the entire existing Raindrop library, generates embeddings, computes initial centroids, extracts candidate tag rules, and uploads the seeded Volume to Modal.
- The agent is fully functional from its first deployed run.

## Testing Decisions

- **Test external behavior, not implementation details.** Each test should feed a bookmark through the public decision interface and assert the resulting folder (or `Unsorted`).
- **Key seams to test:**
  - The Resolver's decision function given synthetic bookmark data + a known vector DB state.
  - Text template generation and truncation.
  - WD14 tag parsing and normalization.
  - Tag rule extraction and validation logic.
  - Centroid computation from a set of known embeddings.
  - The relative gap threshold (confident sort vs. stay in `Unsorted`).
- **No Modal infrastructure testing.** Unit tests mock the Raindrop API and Modal Volume; integration testing happens via manual dry-runs against the real Raindrop library.

## Out of Scope

- **LLM / language model reasoning.** The design explicitly excludes any LLM (Llama, GPT, etc.) from the pipeline. All decisions are deterministic rules and vector similarity.
- **Auto-creating Raindrop folders.** The system never creates folders. If a rule targets a missing folder, the rule is disabled during pre-validation.
- **Deleting or archiving dead bookmarks.** The system only sorts; it never removes bookmarks.
- **Page scraping for images.** Only Raindrop's `cover` URL is used.
- **Multimodal embeddings (CLIP).** Text-only `mpnet-base-v2` for now; vision-to-vision similarity is a future optimization.
- **Heuristic JSON config.** Phase 1 URL/title heuristics are set aside for a future iteration; the initial build relies on tag rules and centroids.
- **Notifications / digests / dashboards.** No email, Slack, or external alerting. Observability is via Raindrop tags only.
- **Mobile app or web UI.** The agent is purely backend/serverless.

## Further Notes

- **Folder naming:** The catch-all terminal folder for ambiguous art is `Art/ANIME` (all caps, matching the user's existing convention). The user must create this folder before the first re-index, or the crossover fallback rule will pre-validate as disabled.
- **Cost target:** Modal free tier (~$30/month credit). GPU is invoked sparingly via the funnel architecture; text inference runs on CPU.
- **Cold starts:** Expected ~10s for the first Vision Worker run of the day as the T4 GPU loads WD14 ONNX weights. Acceptable for a personal tool.
- **Tag normalization:** The `tag_rules.json` bridges WD14's snake_case tags (e.g., `hakurei_reimu`) to the user's folder names. This map is auto-extracted but can be manually curated on the Volume if needed.
- **Version tracking:** Each bookmark in ChromaDB carries `last_seen_folder` metadata. The re-index detects manual moves by comparing this stored value to the live folder, enabling true self-correction rather than blind overwrites.
