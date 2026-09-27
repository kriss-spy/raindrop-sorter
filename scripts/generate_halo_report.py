"""Generate a standalone report for latest journal records tagged with ``halo``."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
from html import escape
import json
from pathlib import Path
import sqlite3
from typing import Any
from urllib.parse import urlparse


def _json(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    decoded = json.loads(value)
    return decoded if isinstance(decoded, dict) else {}


def _safe_http_url(value: object) -> str | None:
    candidate = str(value or "")
    parsed = urlparse(candidate)
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.netloc:
        return None
    return candidate


def _cover_urls(path: Path, bookmark_ids: set[int]) -> dict[int, str]:
    if not path.exists() or not bookmark_ids:
        return {}
    placeholders = ", ".join("?" for _bookmark_id in bookmark_ids)
    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            f"SELECT bookmark_id, cover_url FROM bookmark_covers "
            f"WHERE bookmark_id IN ({placeholders})",
            tuple(bookmark_ids),
        )
        return {
            int(bookmark_id): str(cover_url)
            for bookmark_id, cover_url in rows
            if cover_url
        }


def load_halo_records(
    journal_path: str | Path,
    cover_cache_path: str | Path,
) -> list[dict[str, Any]]:
    """Load bookmarks whose latest attempt's visual evidence contains ``halo``."""
    journal_path = Path(journal_path)
    with sqlite3.connect(journal_path) as connection:
        rows = connection.execute(
            """
            WITH ranked AS (
                SELECT attempts.*,
                       ROW_NUMBER() OVER (
                           PARTITION BY bookmark_id
                           ORDER BY started_at DESC, attempt_id DESC
                       ) AS latest_rank
                FROM attempts
            )
            SELECT ranked.attempt_id,
                   ranked.bookmark_id,
                   ranked.started_at,
                   ranked.current_phase,
                   ranked.outcome,
                   ranked.destination,
                   ranked.bookmark_snapshot_json,
                   ranked.decision_json,
                   evidence.details_json
            FROM ranked
            JOIN evidence ON evidence.attempt_id = ranked.attempt_id
            WHERE ranked.latest_rank = 1
              AND evidence.source_kind = 'wd14+visual_exemplar'
            ORDER BY ranked.started_at DESC, ranked.bookmark_id DESC
            """
        ).fetchall()

    records: list[dict[str, Any]] = []
    seen: set[int] = set()
    for (
        attempt_id,
        bookmark_id,
        started_at,
        current_phase,
        outcome,
        destination,
        snapshot_json,
        decision_json,
        visual_json,
    ) in rows:
        visual = _json(visual_json)
        labels = [str(label) for label in visual.get("labels") or []]
        bookmark_id = int(bookmark_id)
        if "halo" not in labels or bookmark_id in seen:
            continue
        seen.add(bookmark_id)
        decision = _json(decision_json)
        snapshot = _json(snapshot_json)
        records.append(
            {
                "attempt_id": str(attempt_id),
                "bookmark_id": bookmark_id,
                "started_at": str(started_at),
                "current_phase": str(current_phase),
                "outcome": str(outcome or "unknown"),
                "destination": str(destination) if destination else None,
                "snapshot": snapshot,
                "decision": decision,
                "visual": visual,
            }
        )

    covers = _cover_urls(Path(cover_cache_path), seen)
    return [
        {**record, "cover": covers.get(record["bookmark_id"])}
        for record in records
    ]


def _counter_list(counter: Counter[str], *, empty: str = "None") -> str:
    if not counter:
        return f"<li><span>{escape(empty)}</span><strong>0</strong></li>"
    return "".join(
        f"<li><span>{escape(label)}</span><strong>{count}</strong></li>"
        for label, count in counter.most_common()
    )


def _destinations(evidence: list[dict[str, Any]]) -> list[str]:
    return list(
        dict.fromkeys(
            str(candidate)
            for item in evidence
            for candidate in [item.get("destination"), *(item.get("candidates") or [])]
            if candidate
        )
    )


def _card(record: dict[str, Any], index: int) -> str:
    snapshot = record["snapshot"]
    visual = record["visual"]
    decision = record["decision"]
    bookmark_id = record["bookmark_id"]
    title = str(snapshot.get("title") or f"Raindrop {bookmark_id}")
    excerpt = str(snapshot.get("excerpt") or "")
    link = _safe_http_url(snapshot.get("link"))
    cover = _safe_http_url(record.get("cover"))
    outcome = record["outcome"]
    destination = record.get("destination") or "Unsorted"
    visual_destination = visual.get("destination") or "No passing destination"
    winner = visual.get("winner") or "None"
    runner_up = visual.get("runner_up") or "None"
    similarity = visual.get("similarity")
    margin = visual.get("margin")
    labels = [str(label) for label in visual.get("labels") or []]
    text_destinations = _destinations(decision.get("text_evidence") or [])
    search_value = " ".join(
        [
            title,
            excerpt,
            outcome,
            destination,
            str(visual_destination),
            str(winner),
            " ".join(labels),
            " ".join(text_destinations),
        ]
    ).casefold()
    image = (
        f'<img class="cover-image" data-src="{escape(str(cover), quote=True)}" '
        f'alt="{escape(title, quote=True)}" loading="lazy" decoding="async" '
        'fetchpriority="low" referrerpolicy="no-referrer">'
        if cover
        else '<div class="image-state">No cached cover</div>'
    )
    image_skeleton = (
        '<span class="image-skeleton" aria-hidden="true"></span>' if cover else ""
    )
    source_link = (
        f'<a href="{escape(link, quote=True)}" target="_blank" rel="noreferrer">Source</a>'
        if link
        else '<span class="muted">No source link</span>'
    )
    label_chips = "".join(
        f'<span class="tag{" halo" if label == "halo" else ""}">{escape(label)}</span>'
        for label in labels
    )
    candidate_text = ", ".join(str(item) for item in visual.get("candidates") or []) or "None"
    text_text = ", ".join(text_destinations) or "None"
    similarity_text = f"{float(similarity):.3f}" if similarity is not None else "—"
    margin_text = f"{float(margin):.3f}" if margin is not None else "—"
    return f"""
    <article class="card" data-outcome="{escape(outcome, quote=True)}"
             data-visual="{escape(str(visual_destination), quote=True)}"
             data-search="{escape(search_value, quote=True)}">
      <a class="media" href="https://app.raindrop.io/my/0/item/{bookmark_id}/edit"
         target="_blank" rel="noreferrer">
        {image}
        {image_skeleton}
      </a>
      <div class="card-body">
        <div class="eyebrow"><span>#{index} · {bookmark_id}</span><span>{escape(record['started_at'])}</span></div>
        <h2>{escape(title)}</h2>
        <p class="excerpt">{escape(excerpt)}</p>
        <div class="badges"><span class="badge {escape(outcome)}">{escape(outcome)}</span><span class="badge neutral">{escape(record['current_phase'])}</span></div>
        <dl>
          <div><dt>Decision</dt><dd>{escape(destination)}</dd></div>
          <div><dt>Visual</dt><dd>{escape(str(visual_destination))}</dd></div>
          <div><dt>Visual candidates</dt><dd>{escape(candidate_text)}</dd></div>
          <div><dt>Exemplar</dt><dd>{escape(str(winner))} · {similarity_text}</dd></div>
          <div><dt>Runner-up</dt><dd>{escape(str(runner_up))} · margin {margin_text}</dd></div>
          <div><dt>Text candidates</dt><dd>{escape(text_text)}</dd></div>
        </dl>
        <details><summary>Visual labels ({len(labels)})</summary><div class="tags">{label_chips}</div></details>
        <div class="links">{source_link}<a href="https://app.raindrop.io/my/0/item/{bookmark_id}/edit" target="_blank" rel="noreferrer">Raindrop</a></div>
      </div>
    </article>"""


def render_report(records: list[dict[str, Any]]) -> str:
    """Render a dependency-free report with viewport-aware cover loading."""
    outcomes = Counter(record["outcome"] for record in records)
    decisions = Counter(record.get("destination") or "Unsorted" for record in records)
    visual_destinations = Counter(
        str(record["visual"].get("destination") or "Inconclusive")
        for record in records
    )
    ba_decisions = sum(
        count for destination, count in decisions.items() if destination == "Art/GAMES/BA"
    )
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    outcome_options = "".join(
        f'<option value="{escape(value, quote=True)}">{escape(value)} · {count}</option>'
        for value, count in outcomes.most_common()
    )
    visual_options = "".join(
        f'<option value="{escape(value, quote=True)}">{escape(value)} · {count}</option>'
        for value, count in visual_destinations.most_common()
    )
    cards = "".join(_card(record, index) for index, record in enumerate(records, 1))
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Halo visual evidence — {len(records)} Raindrops</title>
<style>
:root{{color-scheme:dark;--bg:#091017;--panel:#111b24;--panel2:#16232d;--line:#293b47;--text:#eef7f8;--muted:#8da2ad;--cyan:#62d7db;--lime:#a7dc6a;--amber:#f3bd66;--red:#ef7777;--violet:#baa1ff}}
*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at 15% -5%,#173241 0,transparent 32rem),var(--bg);color:var(--text);font:14px/1.45 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}}a{{color:var(--cyan)}}header,main{{width:min(1800px,calc(100% - 28px));margin:auto}}header{{padding:32px 0 20px}}h1{{font-size:clamp(32px,5vw,64px);line-height:.95;letter-spacing:-.055em;margin:0}}.lede{{color:var(--muted);max-width:900px;margin:14px 0 0}}.stats{{display:grid;grid-template-columns:repeat(4,minmax(130px,1fr));gap:10px;margin:24px 0}}.stat,.breakdown{{border:1px solid var(--line);background:color-mix(in srgb,var(--panel) 92%,transparent);border-radius:14px;padding:15px}}.stat strong{{display:block;font-size:28px;letter-spacing:-.04em}}.stat span{{color:var(--muted)}}.breakdowns{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}}.breakdown h3{{margin:0 0 8px;font-size:13px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}}.breakdown ul{{list-style:none;padding:0;margin:0;max-height:180px;overflow:auto}}.breakdown li{{display:flex;justify-content:space-between;gap:12px;padding:4px 0;border-bottom:1px solid color-mix(in srgb,var(--line) 55%,transparent)}}.toolbar{{position:sticky;top:0;z-index:5;display:grid;grid-template-columns:minmax(240px,1fr) minmax(180px,auto) minmax(200px,auto) auto;gap:8px;padding:12px;margin:18px 0;background:color-mix(in srgb,var(--bg) 88%,transparent);backdrop-filter:blur(14px);border:1px solid var(--line);border-radius:14px}}input,select,button{{border:1px solid var(--line);background:#0d171f;color:var(--text);border-radius:9px;padding:10px 11px;font:inherit}}button{{cursor:pointer;color:var(--cyan)}}.count{{align-self:center;color:var(--muted);white-space:nowrap}}.gallery{{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:12px;padding-bottom:48px}}.card{{min-width:0;overflow:hidden;border:1px solid var(--line);border-radius:14px;background:var(--panel)}}.card[hidden]{{display:none}}.media{{position:relative;display:grid;place-items:center;height:260px;background:#070c10;border-bottom:1px solid var(--line);text-decoration:none}}.cover-image{{position:relative;z-index:2;width:100%;height:100%;object-fit:contain;opacity:0;transition:opacity .18s ease}}.cover-image.loaded{{opacity:1}}.cover-image.failed{{display:none}}.image-skeleton{{position:absolute;inset:0;background:linear-gradient(105deg,#0d171f 20%,#172832 36%,#0d171f 52%);background-size:240% 100%;animation:shimmer 1.5s linear infinite}}.cover-image.loaded+.image-skeleton,.cover-image.failed+.image-skeleton{{display:none}}.image-state{{position:relative;z-index:2;color:var(--muted)}}@keyframes shimmer{{to{{background-position:-240% 0}}}}.card-body{{padding:12px}}.eyebrow{{display:flex;justify-content:space-between;gap:8px;color:var(--muted);font-size:11px}}h2{{font-size:17px;line-height:1.25;margin:8px 0;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}}.excerpt{{color:var(--muted);min-height:2.8em;max-height:4.2em;overflow:hidden;white-space:pre-line}}.badges,.tags,.links{{display:flex;flex-wrap:wrap;gap:6px}}.badge,.tag{{border:1px solid var(--line);border-radius:999px;padding:2px 7px;font-size:11px}}.badge.confirmed{{color:var(--lime)}}.badge.provisional{{color:var(--amber)}}.badge.conflict,.badge.error{{color:var(--red)}}.badge.review{{color:var(--violet)}}.badge.neutral{{color:var(--muted)}}dl{{margin:10px 0}}dl div{{display:grid;grid-template-columns:105px 1fr;gap:8px;padding:4px 0;border-top:1px solid var(--line)}}dt{{color:var(--muted)}}dd{{margin:0;overflow-wrap:anywhere}}details{{border-top:1px solid var(--line);padding-top:8px}}summary{{cursor:pointer;color:var(--muted)}}.tags{{margin-top:8px}}.tag.halo{{color:#10170a;background:var(--lime);border-color:var(--lime)}}.links{{justify-content:flex-end;margin-top:12px}}.muted{{color:var(--muted)}}
@media(max-width:900px){{.stats{{grid-template-columns:repeat(2,1fr)}}.breakdowns{{grid-template-columns:1fr}}.toolbar{{grid-template-columns:1fr 1fr}}}}@media(max-width:560px){{header,main{{width:min(100% - 16px,1800px)}}.toolbar{{grid-template-columns:1fr}}.gallery{{grid-template-columns:1fr}}.media{{height:230px}}}}
</style></head><body>
<header><h1>Halo evidence</h1><p class="lede">All {len(records)} bookmarks whose latest journal attempt contains the WD14 visual label <code>halo</code>. Generated {escape(generated_at)}. Covers come from the local cover projection and load only near the viewport.</p>
<section class="stats"><div class="stat"><strong>{len(records)}</strong><span>Latest halo records</span></div><div class="stat"><strong>{ba_decisions}</strong><span>Decision: Blue Archive</span></div><div class="stat"><strong>{outcomes.get('review',0)}</strong><span>Awaiting review</span></div><div class="stat"><strong>{outcomes.get('conflict',0)}</strong><span>Conflicts</span></div></section>
<section class="breakdowns"><div class="breakdown"><h3>Outcomes</h3><ul>{_counter_list(outcomes)}</ul></div><div class="breakdown"><h3>Decision destinations</h3><ul>{_counter_list(decisions)}</ul></div><div class="breakdown"><h3>Visual destinations</h3><ul>{_counter_list(visual_destinations)}</ul></div></section></header>
<main><section class="toolbar" aria-label="Report filters"><input id="search" type="search" placeholder="Search title, labels, destinations"><select id="outcome"><option value="">All outcomes</option>{outcome_options}</select><select id="visual"><option value="">All visual destinations</option>{visual_options}</select><button id="images" type="button" aria-pressed="true">Pause image loading</button><span class="count" id="count">{len(records)} shown</span></section><section class="gallery" id="gallery">{cards}</section></main>
<script>
const cards=[...document.querySelectorAll('.card')];
const search=document.querySelector('#search'),outcome=document.querySelector('#outcome'),visual=document.querySelector('#visual'),count=document.querySelector('#count'),imageButton=document.querySelector('#images');
let imagesEnabled=true;
function loadImage(img){{if(!imagesEnabled||!img.dataset.src)return;img.onload=()=>img.classList.add('loaded');img.onerror=()=>img.classList.add('failed');img.src=img.dataset.src;delete img.dataset.src;}}
const observer='IntersectionObserver' in window?new IntersectionObserver(entries=>{{for(const entry of entries){{if(entry.isIntersecting&&imagesEnabled){{loadImage(entry.target);observer.unobserve(entry.target)}}}}}},{{rootMargin: '900px 0px'}}):null;
function observeImages(reset=false){{if(observer&&reset)observer.disconnect();document.querySelectorAll('img[data-src]').forEach(img=>observer?observer.observe(img):loadImage(img));}}
function applyFilters(){{const needle=search.value.trim().toLocaleLowerCase();let shown=0;for(const card of cards){{const visible=(!needle||card.dataset.search.includes(needle))&&(!outcome.value||card.dataset.outcome===outcome.value)&&(!visual.value||card.dataset.visual===visual.value);card.hidden=!visible;if(visible)shown++;}}count.textContent=`${{shown}} shown`;observeImages();}}
for(const control of [search,outcome,visual])control.addEventListener(control===search?'input':'change',applyFilters);
imageButton.addEventListener('click',()=>{{imagesEnabled=!imagesEnabled;imageButton.setAttribute('aria-pressed',String(imagesEnabled));imageButton.textContent=imagesEnabled?'Pause image loading':'Resume image loading';if(imagesEnabled)observeImages(true);}});
observeImages();
</script></body></html>"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", type=Path, default=Path("chroma_db"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".private-reports/halo-visual-report.html"),
    )
    args = parser.parse_args()
    records = load_halo_records(
        args.db_path / "run-journal.sqlite",
        args.db_path / "cover-cache.sqlite",
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_report(records), encoding="utf-8")
    print(f"Wrote {len(records)} records to {args.output.resolve()}")


if __name__ == "__main__":
    main()
