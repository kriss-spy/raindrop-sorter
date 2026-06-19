# Project Documentation: Raindrop Sorter (Serverless Edition)

## 1. System Overview

**Raindrop Sorter** is an autonomous agent deployed on **Modal.com**. It monitors the Raindrop.io `Unsorted` collection, performs visual and semantic analysis using cloud GPUs, and organizes bookmarks into a folder hierarchy based on a "learned" vector database of your existing library.

## 2. Technical Architecture

### A. The "Brain" (Modal App)

The system is built as a single Python application using the Modal SDK, split into three functional layers:

1. **The Watcher (CPU):** A scheduled cron job (every 30 mins) that polls the Raindrop API.
2. **The Vision Worker (GPU):** A serverless function that spins up an **NVIDIA T4** to run the **WD14 Tagger** and **SauceNAO** reverse search.
3. **The Resolver (CPU):** A semantic logic layer that queries your personal **Vector Memory** to decide the final folder.

### B. The Memory (Modal Volume)

* **Vector Database:** A persistent **ChromaDB** instance stored on a `modal.Volume`. This contains embeddings of your ~1,000+ existing sorted raindrops.
* **Normalization Map:** A JSON lookup table bridging AI tags (e.g., `hakurei_reimu`) to your specific tag names (e.g., `Hakurei Reimu`).

---

## 3. Decision Logic & Intelligence

### Phase 1: URL & Metadata Intelligence

Before spinning up the GPU, the agent checks the "easy" data:

* **Domain Matching:** YouTube/Crunchyroll links trigger the `Videos/Anime` logic.
* **Title Keywords:** If the title contains "Minecraft" + "5 hunters," it bypasses the LLM and maps directly to `Videos -> Minecraft`.

### Phase 2: Hybrid Visual Analysis

For images/Twitter art:

1. **Metadata Check:** Query **SauceNAO** with the Raindrop `cover` URL.
2. **Tagging:** Run **WD14 Tagger**.
* **Single Char:** If tags contain exactly one high-confidence character (e.g., `hatsune_miku`), it searches for that character in your **Memory**.
* **Multi-Char:** If tags detect multiple distinct characters (e.g., `2girls` + different series tags)  Move to `Art -> Misce`.



### Phase 3: Semantic Retrieval (Learning)

If Rules 1 & 2 don't yield a 100% match:

* **Query:** The agent takes the Title + AI Tags and performs a **Vector Search** against your ChromaDB.
* **Matching:** It looks for the "Nearest Neighbor." If you previously put "Miku in a winter coat" in `Art/Vocaloid`, the agent will put "Miku in a swimsuit" in the same folder because the vectors are semantically close.

---

## 4. Operational Workflow

| Step | Action | Environment |
| --- | --- | --- |
| **Ingestion** | Fetch `Unsorted` raindrops via API. | Modal (CPU) |
| **Vision** | Run WD14 on `cover` URL via serverless GPU. | Modal (T4 GPU) |
| **Memory** | Fetch similar items from ChromaDB Volume. | Modal (CPU) |
| **Decision** | Apply "Misce" rule or Character-match rule. | Modal (CPU) |
| **Action** | Update Raindrop folder and Add Tags. | Modal (CPU) |

### The "Passive Learning" Loop

* **Weekly Re-index:** Every Sunday at 3 AM, a script scans your *entire* library.
* **Self-Correction:** If you moved a Miku art from `Unsorted` to a new `Art/RacingMiku` folder manually, the Sunday scan updates the Vector DB. The AI now "knows" this new preference for all future matches.

---

## 5. Deployment & Costs (Modal-specific)

* **Free Tier Mastery:** Modal provides **$30/month in free credits**.
* **WD14 (GPU):** ~2 seconds per run. 100 runs/day = ~6,000 seconds/month  **$1.00**.
* **Llama 3 / Logic (CPU):** Negligible.
* **Total Monthly Cost:** **$0.00** (well under the $30 limit).


* **Cold Starts:** Modal containers "sleep" when not in use. The first run of the day may take 10 seconds to load the model weights into the GPU.

---

## 6. Project Roadmap

1. **Phase 1: Initial Indexing.** Write a local script to crawl your existing library and build the first `chroma.sqlite3` file.
2. **Phase 2: Modal Setup.** Upload the model weights (WD14 ONNX) to a Modal Volume.
3. **Phase 3: Logic Implementation.** Build the "Misce" rule and the Tag Normalizer.
4. **Phase 4: Deployment.** Deploy the cron job to Modal and monitor the logs.

