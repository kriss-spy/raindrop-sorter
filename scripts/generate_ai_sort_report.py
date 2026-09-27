"""Generate an AI-ordered random review sample with smart cover loading."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
from html import escape
from pathlib import Path
import random
from typing import Any
from urllib.parse import urlparse

from src.cover_cache import SQLiteCoverCache
from src.run_journal import SQLiteRunJournal
from src.visual_order import order_by_visual_similarity


DEFAULT_SEED = 20260927


def load_review_sample(
    journal_path: str | Path,
    cover_cache_path: str | Path,
    *,
    sample_size: int = 100,
    seed: int = DEFAULT_SEED,
) -> list[dict[str, Any]]:
    """Return a reproducible AI-ordered sample of current apply/review records."""
    if sample_size < 1:
        raise ValueError("sample_size must be at least 1")
    journal = SQLiteRunJournal(journal_path, read_only=True)
    candidates = journal.recent(
        limit=100_000,
        outcome="review",
        mode="apply",
        latest_per_bookmark=True,
        exclude_phase="skipped_stale",
    )
    sample = random.Random(seed).sample(candidates, min(sample_size, len(candidates)))
    with_covers = SQLiteCoverCache(cover_cache_path).attach(sample)
    return order_by_visual_similarity(with_covers)


def review_candidate_count(journal_path: str | Path) -> int:
    journal = SQLiteRunJournal(journal_path, read_only=True)
    return len(
        journal.recent(
            limit=100_000,
            outcome="review",
            mode="apply",
            latest_per_bookmark=True,
            exclude_phase="skipped_stale",
        )
    )


def _safe_http_url(value: object) -> str | None:
    candidate = str(value or "")
    parsed = urlparse(candidate)
    return candidate if parsed.scheme.casefold() in {"http", "https"} and parsed.netloc else None


def _card(record: dict[str, Any], index: int, previous_labels: set[str]) -> str:
    bookmark_id = int(record["bookmark_id"])
    title = str(record.get("title") or f"Raindrop {bookmark_id}")
    labels = [str(label) for label in record.get("visual_labels") or []]
    label_set = {label.casefold() for label in labels}
    shared = sorted(label_set & previous_labels)
    cover = _safe_http_url(record.get("cover"))
    link = _safe_http_url(record.get("link"))
    image = (
        f'<img class="cover" data-src="{escape(cover, quote=True)}" '
        f'alt="{escape(title, quote=True)}" loading="lazy" decoding="async" '
        'fetchpriority="low" referrerpolicy="no-referrer">'
        if cover
        else '<div class="no-cover">No cached cover</div>'
    )
    chips = "".join(f'<span class="chip">{escape(label)}</span>' for label in labels)
    shared_text = ", ".join(shared[:6]) if shared else "New visual cluster"
    source = (
        f'<a href="{escape(link, quote=True)}" target="_blank" rel="noreferrer">Source</a>'
        if link
        else '<span class="muted">No source link</span>'
    )
    search = " ".join((title, *labels)).casefold()
    return f"""
    <article class="record" data-search="{escape(search, quote=True)}">
      <div class="rank"><strong>{index:02d}</strong><span>{escape(shared_text)}</span></div>
      <a class="media" href="https://app.raindrop.io/my/0/item/{bookmark_id}/edit"
         target="_blank" rel="noreferrer">{image}<i class="image-wash"></i></a>
      <div class="body">
        <h2>{escape(title)}</h2>
        <p class="meta">#{bookmark_id} · {escape(str(record.get('started_at') or ''))}</p>
        <div class="chips">{chips or '<span class="muted">No visual labels</span>'}</div>
        <div class="links">{source}<a href="https://app.raindrop.io/my/0/item/{bookmark_id}/edit" target="_blank" rel="noreferrer">Raindrop</a></div>
      </div>
    </article>"""


def render_report(
    records: list[dict[str, Any]],
    *,
    seed: int,
    candidate_count: int,
) -> str:
    """Render a standalone visual audit of the AI similarity order."""
    label_counts = Counter(
        str(label)
        for record in records
        for label in record.get("visual_labels") or []
    )
    cards = []
    previous_labels: set[str] = set()
    for index, record in enumerate(records, 1):
        cards.append(_card(record, index, previous_labels))
        previous_labels = {
            str(label).casefold() for label in record.get("visual_labels") or []
        }
    common = "".join(
        f'<span class="summary-chip">{escape(label)} <strong>{count}</strong></span>'
        for label, count in label_counts.most_common(12)
    )
    generated = datetime.now().astimezone().isoformat(timespec="seconds")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI visual order — {len(records)} review records</title>
<style>
:root{{--bg:#091017;--panel:#101922;--line:#293943;--text:#edf5f6;--muted:#8ca0aa;--cyan:#61d7d7;--violet:#b9a0ff;--ink:#060a0d;color-scheme:dark}}
*{{box-sizing:border-box}}body{{margin:0;background:linear-gradient(110deg,#10242d 0,transparent 28rem),var(--bg);color:var(--text);font:14px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace}}a{{color:var(--cyan)}}header,main{{width:min(1840px,calc(100% - 28px));margin:auto}}header{{display:grid;grid-template-columns:minmax(0,1.4fr) minmax(280px,.6fr);gap:24px;padding:30px 0 22px;border-bottom:1px solid var(--line)}}h1{{margin:0;font:750 clamp(34px,5vw,70px)/.94 system-ui;letter-spacing:-.06em}}.lede{{max-width:850px;color:var(--muted);font-size:15px}}.facts{{display:grid;grid-template-columns:repeat(2,1fr);align-self:end;border:1px solid var(--line);background:var(--panel)}}.fact{{padding:13px;border-right:1px solid var(--line);border-bottom:1px solid var(--line)}}.fact:nth-child(even){{border-right:0}}.fact:nth-last-child(-n+2){{border-bottom:0}}.fact strong{{display:block;color:var(--violet);font-size:22px}}.fact span{{color:var(--muted);font-size:11px}}.labels{{display:flex;flex-wrap:wrap;gap:6px;margin-top:16px}}.summary-chip,.chip{{border:1px solid var(--line);border-radius:999px;padding:3px 8px;color:var(--muted);font-size:11px}}.summary-chip strong{{color:var(--text)}}.toolbar{{position:sticky;top:0;z-index:5;display:flex;align-items:center;gap:10px;margin:16px 0;padding:10px;border:1px solid var(--line);background:#091017e8;backdrop-filter:blur(12px)}}input,button{{border:1px solid var(--line);background:#0d161d;color:var(--text);padding:9px 10px;font:inherit}}input{{min-width:260px;flex:1}}button{{cursor:pointer;color:var(--cyan)}}#shown{{color:var(--muted);white-space:nowrap}}.gallery{{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:12px;padding-bottom:48px}}.record{{min-width:0;border:1px solid var(--line);background:var(--panel);overflow:hidden}}.record[hidden]{{display:none}}.rank{{display:flex;align-items:center;gap:10px;padding:7px 10px;border-bottom:1px solid var(--line);color:var(--muted);font-size:11px}}.rank strong{{color:var(--violet);font-size:14px}}.rank span{{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}.media{{position:relative;display:grid;place-items:center;height:250px;background:var(--ink);text-decoration:none}}.cover{{position:relative;z-index:2;width:100%;height:100%;object-fit:contain;opacity:0;transition:opacity .16s ease}}.cover.loaded{{opacity:1}}.cover.failed{{display:none}}.image-wash{{position:absolute;inset:0;background:linear-gradient(105deg,#0d171f 20%,#172832 36%,#0d171f 52%);background-size:240% 100%;animation:shimmer 1.5s linear infinite}}.cover.loaded+.image-wash,.cover.failed+.image-wash,.no-cover+.image-wash{{display:none}}.no-cover{{position:relative;z-index:2;color:var(--muted)}}@keyframes shimmer{{to{{background-position:-240% 0}}}}.body{{padding:12px}}h2{{margin:0 0 5px;font:680 17px/1.25 system-ui;min-height:2.5em}}.meta,.muted{{color:var(--muted)}}.meta{{font-size:11px}}.chips{{display:flex;flex-wrap:wrap;gap:5px;max-height:86px;overflow:auto;margin:10px 0}}.chip{{color:var(--text)}}.links{{display:flex;justify-content:flex-end;gap:12px;border-top:1px solid var(--line);padding-top:9px}}
@media(max-width:780px){{header{{grid-template-columns:1fr}}.facts{{max-width:520px}}.gallery{{grid-template-columns:repeat(auto-fill,minmax(240px,1fr))}}}}@media(max-width:480px){{header,main{{width:calc(100% - 16px)}}.toolbar{{flex-wrap:wrap}}input{{width:100%;min-width:0}}}}
</style></head><body>
<header><section><h1>Visual-neighbour review</h1><p class="lede">A reproducible random sample from <code>outcome:review mode:apply</code>, ordered by weighted overlap of AI-generated visual labels. Rare labels count more than ubiquitous labels; the strip above each image shows continuity with the previous record.</p><div class="labels">{common}</div></section><section class="facts"><div class="fact"><strong>{len(records)}</strong><span>Sampled records</span></div><div class="fact"><strong>{candidate_count}</strong><span>Eligible records</span></div><div class="fact"><strong>{len(label_counts)}</strong><span>Distinct labels</span></div><div class="fact"><strong>{seed}</strong><span>Random seed</span></div></section></header>
<main><div class="toolbar"><input id="search" type="search" placeholder="Filter this sample by title or visual label"><button id="images" type="button" aria-pressed="true">Pause images</button><span id="shown">{len(records)} shown</span></div><section class="gallery">{''.join(cards)}</section><p class="muted">Generated {escape(generated)} · Random seed {seed}</p></main>
<script>
const MAX_CONCURRENT_IMAGES=4;
const queue=[];let activeImages=0,imagesEnabled=true;
function pumpImages(){{while(imagesEnabled&&activeImages<MAX_CONCURRENT_IMAGES&&queue.length){{const img=queue.shift();if(!img.dataset.src)continue;activeImages++;const done=failed=>{{img.classList.add(failed?'failed':'loaded');activeImages--;pumpImages();}};img.onload=()=>done(false);img.onerror=()=>done(true);img.src=img.dataset.src;delete img.dataset.src;}}}}
function enqueueImage(img){{if(!img.dataset.src||queue.includes(img))return;queue.push(img);pumpImages();}}
const observer='IntersectionObserver' in window?new IntersectionObserver(entries=>entries.filter(entry=>entry.isIntersecting).forEach(entry=>{{observer.unobserve(entry.target);enqueueImage(entry.target);}}),{{rootMargin:'800px 0px'}}):null;
function observeImages(){{document.querySelectorAll('img[data-src]').forEach(img=>observer?observer.observe(img):enqueueImage(img));}}
const cards=[...document.querySelectorAll('.record')],search=document.querySelector('#search'),shown=document.querySelector('#shown'),images=document.querySelector('#images');
search.addEventListener('input',()=>{{const needle=search.value.trim().toLocaleLowerCase();let count=0;cards.forEach(card=>{{card.hidden=Boolean(needle&&!card.dataset.search.includes(needle));if(!card.hidden)count++;}});shown.textContent=`${{count}} shown`;observeImages();}});
images.addEventListener('click',()=>{{imagesEnabled=!imagesEnabled;images.setAttribute('aria-pressed',String(imagesEnabled));images.textContent=imagesEnabled?'Pause images':'Resume images';if(imagesEnabled){{observeImages();pumpImages();}}}});
observeImages();
</script></body></html>"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", type=Path, default=Path("chroma_db"))
    parser.add_argument("--sample-size", type=int, default=100)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".private-reports/review-ai-sort-random-100.html"),
    )
    args = parser.parse_args()
    journal_path = args.db_path / "run-journal.sqlite"
    records = load_review_sample(
        journal_path,
        args.db_path / "cover-cache.sqlite",
        sample_size=args.sample_size,
        seed=args.seed,
    )
    candidates = review_candidate_count(journal_path)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        render_report(records, seed=args.seed, candidate_count=candidates),
        encoding="utf-8",
    )
    print(f"Wrote {len(records)} of {candidates} eligible records to {args.output.resolve()}")


if __name__ == "__main__":
    main()
