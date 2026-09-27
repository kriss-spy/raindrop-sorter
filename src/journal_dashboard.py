"""Self-contained browser asset for the local journal dashboard."""

DASHBOARD_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Raindrop Sorter</title>
<style>
:root{color-scheme:dark;--bg:#0a0f14;--panel:#111820;--line:#26323d;--muted:#8fa0ae;--text:#edf4f7;--cyan:#61d7d7;--lime:#a8db67;--amber:#f2bd62;--red:#f07878;--violet:#b9a0ff}
*{box-sizing:border-box}
body{margin:0;background:radial-gradient(circle at 10% 0,#12252a 0,transparent 32rem),var(--bg);color:var(--text);font:14px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace}
button,input,select{font:inherit}
.top{display:flex;justify-content:space-between;gap:16px}
.brand{font-family:system-ui;font-weight:700;line-height:1.1}
.live{display:flex;align-items:center;gap:8px;color:var(--muted);white-space:nowrap}
.dot{width:9px;height:9px;border-radius:50%;background:var(--lime);box-shadow:0 0 14px var(--lime)}
.panel{background:color-mix(in srgb,var(--panel) 94%,transparent);border:1px solid var(--line);border-radius:12px}
.toolbar{display:grid}
.toolbar [hidden]{display:none!important}
.control{border:1px solid var(--line);background:#0e151c;color:var(--text);border-radius:9px;outline:none}
.control:focus{border-color:var(--cyan)}
button.control{cursor:pointer;color:var(--cyan)}
.panel{overflow:hidden}
.panel-head{border-bottom:1px solid var(--line);display:flex;justify-content:space-between;color:var(--muted)}
.attempt{display:flex;flex-direction:column;gap:5px;color:inherit;width:100%;text-align:left;cursor:pointer}
.attempt-head{display:flex;align-items:flex-start;justify-content:space-between;gap:10px}
.attempt-title{font:650 15px/1.3 system-ui;white-space:normal;overflow-wrap:anywhere}
.attempt-meta{line-height:1.35}
.attempt-footer{display:flex;align-items:flex-end;justify-content:space-between;gap:8px}
.attempt-time{color:var(--muted);font-size:11px;white-space:nowrap;margin-left:auto}
.attempt-destination{overflow-wrap:anywhere}
.meta,.when{color:var(--muted);font-size:12px}
.destination{color:var(--cyan)}
.badge{align-self:start;border:1px solid currentColor;border-radius:99px;padding:2px 8px;font-size:10px;text-transform:uppercase}
.confirmed{color:var(--lime)}.provisional{color:var(--amber)}.review,.pending{color:var(--violet)}.conflict,.error,.failed{color:var(--red)}
.empty{display:grid;place-content:center;text-align:center;color:var(--muted)}
.detail-title{font-family:system-ui;font-weight:700;margin:4px 0}
.external{color:var(--cyan);text-decoration:none}
.bookmark-preview{display:block;width:100%;object-fit:contain;background:#070b0f;border:1px solid var(--line);border-radius:10px}
.summary{border-left:3px solid var(--cyan);padding:10px 14px;background:#0c151b;margin:18px 0}
.section{margin-top:24px}.section h3{font:650 13px system-ui;text-transform:uppercase;letter-spacing:.1em;color:var(--muted)}
.card{border:1px solid var(--line);border-radius:9px;padding:12px;margin:9px 0;background:#0d141a}
.card-head{display:flex;justify-content:space-between;gap:8px}
.explain{color:var(--muted);margin:6px 0 0}
.timeline{border-left:1px solid var(--line);margin-left:6px;padding-left:18px}
.event{position:relative;margin:13px 0}.event:before{content:"";position:absolute;width:7px;height:7px;border-radius:50%;background:var(--cyan);left:-22px;top:7px}
.json{white-space:pre-wrap;overflow-wrap:anywhere;color:var(--muted);font-size:11px;background:#080d11;padding:10px;border-radius:7px}
.error{color:var(--red);padding:20px}
.skeleton{height:72px;background:linear-gradient(90deg,#111820,#18242c,#111820);background-size:200%;animation:p 1.2s infinite}
@keyframes p{to{background-position:-200%}}
.resolution{border:1px solid color-mix(in srgb,var(--amber) 55%,var(--line));border-radius:11px;padding:16px;margin:18px 0;background:#17150f}.resolution h3{margin:0 0 7px;font:700 16px system-ui}.choice-group{margin-top:14px}.choice-label{display:block;color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.08em;margin-bottom:7px}.choice-grid,.collection-results{display:flex;flex-wrap:wrap;gap:7px}.choice{border:1px solid var(--line);background:#101820;color:var(--text);border-radius:8px;padding:8px 10px;cursor:pointer;text-align:left}.choice:hover,.choice.selected{border-color:var(--cyan);color:var(--cyan);background:#102126}.choice:disabled{cursor:not-allowed;opacity:.45}.collection-search{width:100%;margin-bottom:8px}.collection-results{max-height:155px;overflow:auto}.selection{color:var(--cyan);margin:14px 0 9px}.apply-choice{width:100%;background:var(--cyan);color:#071013;border:0;border-radius:8px;padding:11px;font-weight:750;cursor:pointer}.apply-choice:disabled{cursor:not-allowed;opacity:.45}.resolution-error{color:var(--red);margin-top:9px}
html,body{height:100%;overflow:hidden}
.shell{height:100dvh;max-width:none;padding:10px 16px;display:grid;grid-template-rows:auto auto auto auto auto minmax(0,1fr);gap:8px}
.top{align-items:center;min-height:32px}.brand{font-size:20px;margin:0}
.toolbar{grid-template-columns:minmax(220px,1fr) 36px 76px repeat(3,36px);grid-template-areas:"search filters view refresh control detail";gap:8px;margin:0}
.toolbar #search{grid-area:search}.toolbar #filter-toggle{grid-area:filters}.toolbar .view-switch{grid-area:view}.toolbar button[type="submit"]{grid-area:refresh}.toolbar #sorter-toggle{grid-area:control}.toolbar #detail-toggle{grid-area:detail}
.control{padding:8px 10px}.icon-button{display:inline-grid;place-items:center;border:1px solid var(--line);background:#0e151c;color:var(--cyan);width:36px;height:36px;padding:0;border-radius:9px;cursor:pointer}.icon-button:hover,.icon-button:focus-visible{border-color:var(--cyan);background:#122129}.icon-button svg,.icon-link svg{width:17px;height:17px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}.icon-button.active{color:var(--lime);border-color:var(--lime)}
.filter-toggle{position:relative}.filter-count{position:absolute;top:-6px;right:-6px;display:grid;place-items:center;min-width:17px;height:17px;padding:0 4px;border-radius:9px;background:var(--cyan);color:#071013;font-size:10px;font-weight:800}.filter-count:empty{display:none}.filter-panel{display:grid;grid-template-columns:repeat(4,minmax(150px,1fr));gap:11px;padding:12px;background:color-mix(in srgb,var(--panel) 96%,transparent);border:1px solid var(--line);border-radius:11px;box-shadow:0 14px 36px #05080b66}.filter-panel[hidden]{display:none}.filter-field{display:grid;align-content:start;gap:5px;min-width:0}.filter-field>label,.filter-field-label{color:var(--muted);font-size:11px}.filter-field .control{width:100%;min-width:0}.filter-field-wide{grid-column:span 2}.location-filter{display:flex;align-items:center;min-height:37px;gap:8px;padding:7px 9px;border:1px solid var(--line);border-radius:9px;background:#0e151c}.location-filter output{min-width:0;flex:1;color:var(--cyan);overflow-wrap:anywhere}.filter-clear{border:0;background:transparent;color:var(--muted);cursor:pointer;padding:0 3px}.filter-clear:hover{color:var(--red)}.filter-actions{display:flex;align-items:flex-end;justify-content:flex-end}.reset-filters{width:auto;min-width:110px}
.view-switch{display:flex}.view-switch .icon-button{border-radius:0}.view-switch .icon-button:first-child{border-radius:9px 0 0 9px}.view-switch .icon-button:last-child{border-radius:0 9px 9px 0;margin-left:-1px}
.action-bar,.sorter-panel{display:flex;align-items:center;gap:9px;padding:8px 10px;border:1px solid var(--line);border-radius:10px;background:#101820}.action-bar[hidden],.sorter-panel[hidden]{display:none}.action-bar .control{min-width:260px}.action-message{color:var(--muted);margin-left:auto}.sorter-panel{justify-content:flex-end}.sorter-status{margin-right:auto}.sorter-status strong{color:var(--lime)}.sorter-panel .explain{margin:0}.batch-picker{position:relative;flex:0 1 520px}.batch-picker .control{width:100%}.batch-destination-results{position:absolute;z-index:10;top:calc(100% + 5px);left:0;right:0;max-height:min(380px,60vh);overflow:auto;padding:5px;background:#0e151c;border:1px solid var(--line);border-radius:9px;box-shadow:0 18px 42px #05080bcc}.batch-destination-results[hidden]{display:none}.batch-destination-option{display:block;width:100%;padding:8px 10px;border:0;border-radius:6px;background:transparent;color:var(--text);text-align:left;cursor:pointer}.batch-destination-option:hover,.batch-destination-option.active{background:#183039;color:var(--cyan)}.batch-destination-empty{padding:10px;color:var(--muted)}
.workspace{display:grid;grid-template-columns:280px minmax(0,1fr);gap:8px;position:relative;min-height:0;overflow:hidden}.attempt-panel{height:100%;display:grid;grid-template-rows:auto minmax(0,1fr) auto}.panel-head{padding:9px 12px}
.library-tree-panel{min-height:0;display:grid;grid-template-rows:auto minmax(0,1fr)}.collection-tree{overflow:auto;padding:7px}.collection-group{margin-bottom:12px}.collection-group-title{padding:5px 8px;color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.1em}.collection-list{display:grid;gap:2px}.collection-row{display:grid;grid-template-columns:24px minmax(0,1fr) auto;align-items:center;gap:2px;padding-left:calc(var(--depth,0) * 14px)}.collection-toggle,.collection-select{border:0;background:transparent;color:var(--text);border-radius:6px;cursor:pointer}.collection-toggle{width:24px;height:28px;color:var(--muted)}.collection-toggle:disabled{cursor:default;color:transparent}.collection-select{padding:6px;text-align:left;overflow-wrap:anywhere}.collection-select:hover,.collection-select.active{background:#17232b;color:var(--cyan)}.collection-count{padding-right:6px;color:var(--muted);font-size:11px}.library-message{padding:12px;color:var(--muted)}
.attempt-grid{padding:10px;overflow:auto;display:grid;grid-template-columns:repeat(auto-fill,minmax(245px,1fr));grid-auto-rows:min-content;align-content:start;align-items:stretch;gap:10px;max-height:none}.attempt{position:relative;padding:0;border:1px solid var(--line);border-radius:11px;background:#0d141a;overflow:hidden}.attempt:hover,.attempt.active,.attempt.selected{background:#17232b;border-color:color-mix(in srgb,var(--cyan) 58%,var(--line))}.attempt.active{box-shadow:inset 3px 0 var(--cyan)}.attempt.selected{border-color:var(--cyan);box-shadow:inset 0 0 0 2px color-mix(in srgb,var(--cyan) 42%,transparent)}.attempt.selected.active{box-shadow:inset 3px 0 var(--cyan),inset 0 0 0 2px color-mix(in srgb,var(--cyan) 42%,transparent)}.attempt-body{display:flex;flex-direction:column;gap:5px;padding:9px 10px 10px;min-width:0}.attempt-cover{display:block;width:100%;height:100%;object-fit:cover;background:linear-gradient(135deg,#111d25,#0a1015)}.attempt-cover-wrap{position:relative;background:linear-gradient(135deg,#111d25,#080d11)}.card-cover-wrap{aspect-ratio:16/9}.attempt-cover{position:absolute;inset:0;z-index:1}.attempt-cover-wrap.missing img{display:none}.attempt-select{position:absolute;z-index:3;top:8px;left:8px;width:18px;height:18px;accent-color:var(--cyan)}.attempt-tools{display:flex;align-items:center;gap:7px}.icon-link{display:inline-grid;place-items:center;color:var(--cyan);width:25px;height:25px;border:1px solid var(--line);border-radius:7px;text-decoration:none}.attempt-head .attempt-tools{margin-left:auto}.attempt-head .badge{margin-left:0}
.attempt-table-wrap{padding:0;overflow:auto}.attempt-table{width:100%;border-collapse:collapse;table-layout:fixed}.attempt-table th,.attempt-table td{padding:8px 9px;border-bottom:1px solid var(--line);text-align:left;vertical-align:middle}.attempt-table th{position:sticky;top:0;z-index:2;background:#111820;color:var(--muted);font-size:10px;text-transform:uppercase}.attempt-table tbody tr{cursor:pointer}.attempt-table tbody tr:hover,.attempt-table tbody tr.active,.attempt-table tbody tr.selected{background:#17232b}.attempt-table tbody tr.selected{box-shadow:inset 3px 0 var(--cyan)}.attempt-table .col-check{width:42px}.attempt-table .col-cover{width:76px}.attempt-table .col-outcome{width:110px}.attempt-table .col-run{width:145px}.attempt-table .col-time{width:135px}.attempt-table .col-open{width:48px}.table-cover{width:58px;height:42px;object-fit:cover;border-radius:6px;background:#080d11}.table-title{font:650 14px system-ui;overflow-wrap:anywhere}.table-destination{color:var(--cyan);overflow-wrap:anywhere}
.attempt-table .attempt-select{position:static}.table-cover-wrap{width:58px;height:42px;border-radius:6px;overflow:hidden}.attempt-cover,.table-cover{pointer-events:none}.icon-button:disabled{cursor:not-allowed;opacity:.35}
.detail-panel{position:absolute;z-index:5;inset:0 0 0 auto;width:min(720px,52vw);display:grid;grid-template-rows:auto minmax(0,1fr);background:#10171f;box-shadow:-18px 0 44px #05080bad;transform:translateX(calc(100% + 24px));transition:transform .2s ease;pointer-events:none}.workspace.detail-open .detail-panel{transform:translateX(0);pointer-events:auto}.detail-panel-head{padding:9px 12px;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;color:var(--muted)}.detail-panel-head .icon-button{width:30px;height:30px}.detail-toggle[hidden]{display:none}#detail{padding:18px;max-height:none;overflow:auto;min-height:0}.detail-title{font-size:21px}.detail-links{display:flex;gap:8px;margin-top:7px}.detail-links .icon-link{width:32px;height:32px}.bookmark-preview{max-height:330px;margin:14px 0}.empty{min-height:0}.drawer-scrim{position:absolute;z-index:4;inset:0;background:#05080b99;opacity:0;pointer-events:none;transition:opacity .2s;border:0}.workspace.detail-open .drawer-scrim{opacity:1;pointer-events:auto}
@media(max-width:1100px){.filter-panel{grid-template-columns:repeat(3,minmax(140px,1fr))}.detail-panel{width:min(680px,92vw)}.workspace{grid-template-columns:240px minmax(0,1fr)}}
@media(max-width:700px){.shell{padding:8px 10px}.live{display:none}.toolbar{grid-template-columns:minmax(0,1fr) 36px 76px repeat(3,36px);grid-template-areas:"search filters view refresh control detail"}.filter-panel{grid-template-columns:repeat(2,minmax(0,1fr));max-height:42vh;overflow:auto}.filter-field-wide{grid-column:span 2}.workspace{grid-template-columns:190px minmax(0,1fr)}.attempt-grid{grid-template-columns:repeat(auto-fill,minmax(210px,1fr))}.action-bar,.sorter-panel{flex-wrap:wrap}.action-bar .control{min-width:0;flex:1}.attempt-table{min-width:760px}.detail-panel{width:100%}}
@media(max-height:520px){html,body{overflow:auto}.shell{height:auto;min-height:520px}.workspace{min-height:260px}}
</style></head><body><main class="shell">
<header class="top"><h1 class="brand">Raindrop Sorter</h1><div class="live"><i class="dot"></i><span id="updated">Connecting…</span></div></header>
<form class="toolbar" id="filters"><input class="control" id="search" aria-label="Search and filter sorter journal" placeholder="Search or use filters, e.g. outcome:review label:halo"><button class="icon-button filter-toggle" id="filter-toggle" type="button" aria-label="Show filters" aria-expanded="false" title="Show filters"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h16M7 12h10M10 18h4"/></svg><span class="filter-count" id="filter-count"></span></button><div class="view-switch" role="group" aria-label="Results layout"><button class="icon-button active" id="card-view" type="button" aria-label="Image card layout" title="Image card layout"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg></button><button class="icon-button" id="table-view" type="button" aria-label="Table layout" title="Table layout"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16"/><path d="M8 4v16"/></svg></button></div><button class="icon-button" type="submit" aria-label="Refresh dashboard" title="Refresh dashboard"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 6v5h-5"/><path d="M19 11a7.5 7.5 0 1 0 .2 5"/></svg></button><button class="icon-button" id="sorter-toggle" type="button" aria-label="Show sorter controls" title="Show sorter controls"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h10M18 6h2M4 12h2M10 12h10M4 18h7M15 18h5"/><circle cx="16" cy="6" r="2"/><circle cx="8" cy="12" r="2"/><circle cx="13" cy="18" r="2"/></svg></button><button class="icon-button detail-toggle" id="detail-toggle" type="button" aria-label="Show attempt details" title="Show attempt details" hidden><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M14 4v16"/></svg></button></form>
<section class="filter-panel" id="filter-panel" aria-label="Journal filters" hidden><div class="filter-field"><label for="outcome">Outcome</label><select class="control" id="outcome"><option value="">All outcomes</option></select></div><div class="filter-field"><label for="phase">Lifecycle phase</label><select class="control" id="phase"><option value="">All lifecycle phases</option></select></div><div class="filter-field"><label for="mode">Run mode</label><select class="control" id="mode"><option value="">All run modes</option><option value="dry-run">dry-run</option><option value="apply">apply</option><option value="manual-review">manual-review</option><option value="legacy-tag-migration">legacy-tag-migration</option></select></div><div class="filter-field"><label for="scope">Attempt scope</label><select class="control" id="scope"><option value="latest">Latest status</option><option value="history">Attempt history</option></select></div><div class="filter-field filter-field-wide"><label for="visual-labels">Visual labels · comma separated, all must match</label><input class="control" id="visual-labels" placeholder="halo, blue_hair" autocomplete="off"></div><div class="filter-field"><label for="title-filter">Title contains</label><input class="control" id="title-filter" placeholder="Hatsune Miku" autocomplete="off"></div><div class="filter-field"><label for="link-filter">Source URL contains</label><input class="control" id="link-filter" placeholder="x.com/" autocomplete="off"></div><div class="filter-field"><span class="filter-field-label">Current Raindrop location · choose from tree</span><div class="location-filter"><output id="location-filter">Any location</output><button class="filter-clear" id="location-clear" type="button" aria-label="Clear location filter" title="Clear location filter">×</button></div></div><div class="filter-field"><label for="date-filter">Processed on</label><input class="control" id="date-filter" type="date"></div><div class="filter-actions"><button class="control reset-filters" id="reset-filters" type="button">Reset filters</button></div></section>
<section class="action-bar" id="batch-bar" hidden><strong id="selection-count">0 selected</strong><div class="batch-picker"><input class="control" id="batch-destination-search" role="combobox" aria-label="Batch destination" aria-autocomplete="list" aria-controls="batch-destination-results" aria-expanded="false" autocomplete="off" placeholder="Search Art destinations…"><div class="batch-destination-results" id="batch-destination-results" role="listbox" hidden></div></div><button class="icon-button" id="batch-assign" type="button" aria-label="Assign selected Raindrops" title="Assign selected Raindrops" disabled><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h12M13 7l5 5-5 5"/><path d="M5 5v14"/></svg></button><button class="icon-button" id="selection-clear" type="button" aria-label="Clear selection" title="Clear selection"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18"/></svg></button><span class="action-message" id="batch-message"></span></section>
<section class="sorter-panel" id="sorter-panel" hidden><div class="sorter-status"><strong id="sorter-state">Loading…</strong><div class="explain" id="sorter-summary">Reading local sorter status</div></div><button class="icon-button" id="process-all" type="button" aria-label="Process all Unsorted Raindrops" title="Process all Unsorted Raindrops"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h16M4 12h10M4 18h7"/><path d="m15 15 3 3 4-5"/></svg></button><button class="icon-button" id="sorter-stop" type="button" aria-label="Stop processing Unsorted Raindrops" title="Stop processing after the current Raindrop"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="1"/></svg></button><button class="icon-button" id="sorter-start" type="button" aria-label="Start automatic sorter" title="Start automatic sorter"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m8 5 11 7-11 7z"/></svg></button><button class="icon-button" id="sorter-pause" type="button" aria-label="Pause automatic sorter" title="Pause automatic sorter"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 5v14M15 5v14"/></svg></button></section>
<section class="workspace" id="workspace"><aside class="panel library-tree-panel" aria-label="Current Raindrop location filter"><header class="panel-head"><span>Location</span><span id="tree-filter-state">All</span></header><div class="collection-tree" id="collection-tree"><div class="skeleton"></div></div></aside><div class="panel attempt-panel"><div class="panel-head"><span id="list-title">Latest Raindrop status</span><span id="count">—</span></div><div id="attempts" class="attempt-grid"><div class="skeleton"></div><div class="skeleton"></div></div></div><button class="drawer-scrim" id="detail-scrim" type="button" aria-label="Close attempt details" aria-hidden="true" tabindex="-1"></button><aside class="panel detail-panel" id="detail-panel" aria-hidden="true" inert><header class="detail-panel-head"><span>Attempt details</span><button class="icon-button" id="detail-close" type="button" aria-label="Close attempt details" title="Close attempt details"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18"/></svg></button></header><div id="detail" class="empty">Select a Raindrop to inspect its latest trace.</div></aside></section>
</main><script>
const select = selector => document.querySelector(selector);
const element = (tag, className, text) => {
  const created = document.createElement(tag);
  if (className) created.className = className;
  if (text !== undefined) created.textContent = text;
  return created;
};
let selectedAttemptId = null;
let detailSelectionRevision = 0;
const attemptTraceCache = new Map();
const previewUrlCache = new Map();
const attemptElementCache = new Map();
const MAX_CONCURRENT_PREVIEW_FETCHES = 2;
const previewFetchQueue = [];
let activePreviewFetches = 0;
let previewCacheGeneration = 0;
let artCollectionsPromise = null;
let resultLayout = localStorage.getItem('sorter-result-layout') === 'table' ? 'table' : 'cards';
let renderedAttempts = [];
const selectedAttempts = new Set();
const pendingAssignmentAttemptIds = new Set();
const pendingAssignmentBookmarkIds = new Set();
let pinnedRetry = null;
let selectionAnchorAttemptId = null;
let batchDestinationCollections = [];
let batchDestinationFocusIndex = 0;
let batchDestinationWantsOpen = false;
let batchMessageGeneration = 0;
const expandedCollectionsStorageKey = 'sorter-library-expanded-collections';
let collectionTreeGroups = [];
let journalSearchValue = '';
let freeSearchValue = '';
let selectedLocationPath = '';
let selectedLocationCollectionId = null;
let overviewRenderGeneration = 0;
let attemptsRenderGeneration = 0;
let activeForegroundAttemptsRenderGeneration = null;
let backgroundRefreshPending = false;
let expandedCollectionIds = new Set();
try {
  expandedCollectionIds = new Set(JSON.parse(localStorage.getItem(expandedCollectionsStorageKey) || '[]').map(String));
} catch (_error) {
  expandedCollectionIds = new Set();
}
const previewObserver = 'IntersectionObserver' in window ? new IntersectionObserver(entries => {
  entries.filter(entry => entry.isIntersecting).forEach(entry => {
    const image = entry.target;
    previewObserver.unobserve(image);
    loadPreviewImage(image);
  });
}, {rootMargin:'240px'}) : null;
const shortDateTime = new Intl.DateTimeFormat('en-US', {
  year:'2-digit', month:'2-digit', day:'2-digit',
  hour:'numeric', minute:'2-digit', hour12:true,
});
const formatTime = timestamp => timestamp
  ? shortDateTime.format(new Date(timestamp)).replace(', ', ' ')
  : 'running';
const formatDuration = milliseconds => milliseconds == null
  ? 'running'
  : milliseconds < 1000 ? `${Math.round(milliseconds)} ms` : `${(milliseconds / 1000).toFixed(1)} s`;
const raindropItemUrl = bookmarkId => `https://app.raindrop.io/my/0/item/${encodeURIComponent(bookmarkId)}/edit`;
function svgIcon(markup) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('aria-hidden', 'true');
  svg.innerHTML = markup;
  return svg;
}
function raindropLink(bookmarkId, label = 'Open in Raindrop.io') {
  const link = element('a', 'icon-link');
  link.href = raindropItemUrl(bookmarkId);
  link.target = '_blank';
  link.rel = 'noreferrer';
  link.setAttribute('aria-label', label);
  link.title = label;
  link.append(svgIcon('<path d="M14 4h6v6"/><path d="m20 4-9 9"/><path d="M18 13v6a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h6"/>'));
  link.onclick = event => event.stopPropagation();
  return link;
}
function directCoverUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === 'https:' ? url.href : '';
  } catch (_error) {
    return '';
  }
}
function previewImage(bookmarkId, title, className, coverUrl = '') {
  const image = element('img', className);
  image.alt = title ? `Preview of ${title}` : `Preview of Raindrop ${bookmarkId}`;
  image.loading = 'lazy';
  image.decoding = 'async';
  image.referrerPolicy = 'no-referrer';
  image.dataset.bookmarkId = String(bookmarkId);
  image.dataset.coverUrl = directCoverUrl(coverUrl);
  image.onerror = () => loadFallbackPreview(image);
  image.onload = () => image.parentElement?.classList.remove('missing');
  if (previewObserver) previewObserver.observe(image);
  else loadPreviewImage(image);
  return image;
}
function loadFallbackPreview(image) {
  if (image.dataset.fallbackStarted) {
    image.parentElement?.classList.add('missing');
    return;
  }
  image.dataset.fallbackStarted = 'true';
  previewUrl(image.dataset.bookmarkId)
    .then(url => { if (image.isConnected) image.src = url; })
    .catch(() => image.parentElement?.classList.add('missing'));
}
function loadPreviewImage(image) {
  if (image.dataset.coverUrl) {
    image.src = image.dataset.coverUrl;
    return;
  }
  loadFallbackPreview(image);
}
async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error((await response.json()).error || response.statusText);
  return response.json();
}
async function postJson(url, payload) {
  const response = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
  const result = await response.json();
  if (!response.ok) {
    const error = new Error(result.error || response.statusText);
    error.payload = result;
    throw error;
  }
  return result;
}
function artCollectionsFromTree() {
  const artGroup = collectionTreeGroups.find(
    group => String(group.title || '').trim().toLocaleLowerCase() === 'art'
  );
  if (!artGroup) return [];
  const collections = [];
  const visit = node => {
    collections.push({
      collection_id:Number(node.id),
      path:collectionFilterPath(artGroup, node),
    });
    (node.children || []).forEach(visit);
  };
  (artGroup.collections || []).forEach(visit);
  return collections;
}
function artCollections() {
  const treeCollections = artCollectionsFromTree();
  if (treeCollections.length) return Promise.resolve(treeCollections);
  if (!artCollectionsPromise) {
    artCollectionsPromise = fetchJson('/api/review/collections')
      .then(result => result.items)
      .catch(error => { artCollectionsPromise = null; throw error; });
  }
  return artCollectionsPromise;
}
async function attemptTrace(attemptId) {
  const cached = attemptTraceCache.get(attemptId);
  if (cached && cached.expiresAt > Date.now()) return cached.value;
  const pending = fetchJson('/api/attempts/' + encodeURIComponent(attemptId));
  const entry = {value: pending, expiresAt: Date.now() + 15_000};
  attemptTraceCache.set(attemptId, entry);
  try {
    const trace = await pending;
    if (attemptTraceCache.get(attemptId) === entry) {
      attemptTraceCache.set(attemptId, {value: trace, expiresAt: Date.now() + 15_000});
    }
    while (attemptTraceCache.size > 100) {
      attemptTraceCache.delete(attemptTraceCache.keys().next().value);
    }
    return trace;
  } catch (error) {
    if (attemptTraceCache.get(attemptId) === entry) attemptTraceCache.delete(attemptId);
    throw error;
  }
}
function drainPreviewFetchQueue() {
  while (activePreviewFetches < MAX_CONCURRENT_PREVIEW_FETCHES && previewFetchQueue.length) {
    const item = previewFetchQueue.shift();
    activePreviewFetches += 1;
    fetch(item.url)
      .then(response => {
        if (!response.ok) throw new Error(response.statusText);
        return response.blob();
      })
      .then(item.resolve, item.reject)
      .finally(() => {
        activePreviewFetches -= 1;
        drainPreviewFetchQueue();
      });
  }
}
function fetchPreviewBlob(bookmarkId) {
  return new Promise((resolve, reject) => {
    previewFetchQueue.push({
      url:`/api/bookmarks/${encodeURIComponent(bookmarkId)}/preview`,
      resolve,
      reject,
    });
    drainPreviewFetchQueue();
  });
}
async function previewUrl(bookmarkId) {
  if (previewUrlCache.has(bookmarkId)) return previewUrlCache.get(bookmarkId);
  const generation = previewCacheGeneration;
  const pending = fetchPreviewBlob(bookmarkId)
    .then(blob => URL.createObjectURL(blob));
  previewUrlCache.set(bookmarkId, pending);
  try {
    const url = await pending;
    if (generation !== previewCacheGeneration) {
      URL.revokeObjectURL(url);
      throw new Error('preview cache was refreshed');
    }
    previewUrlCache.set(bookmarkId, url);
    while (previewUrlCache.size > 50) {
      const oldest = previewUrlCache.keys().next().value;
      const oldUrl = previewUrlCache.get(oldest);
      previewUrlCache.delete(oldest);
      if (typeof oldUrl === 'string') URL.revokeObjectURL(oldUrl);
    }
    return url;
  } catch (error) {
    if (previewUrlCache.get(bookmarkId) === pending) previewUrlCache.delete(bookmarkId);
    throw error;
  }
}
function clearDataCaches() {
  attemptTraceCache.clear();
  artCollectionsPromise = null;
  const batchDestination = select('#batch-destination-search');
  batchDestination.dataset.loaded = 'false';
  batchDestinationCollections = [];
  closeBatchDestinationResults();
}
function clearPreviewCache() {
  previewCacheGeneration += 1;
  previewUrlCache.forEach(value => {
    if (typeof value === 'string') URL.revokeObjectURL(value);
  });
  previewUrlCache.clear();
}
function clearCaches() {
  clearDataCaches();
  clearPreviewCache();
}
function invalidateDetailSelection() {
  detailSelectionRevision += 1;
}
function setDetailOpen(open) {
  select('#workspace').classList.toggle('detail-open', open);
  const panel = select('#detail-panel');
  panel.setAttribute('aria-hidden', String(!open));
  panel.inert = !open;
  const toggle = select('#detail-toggle');
  toggle.hidden = !selectedAttemptId;
  toggle.classList.toggle('active', open);
  toggle.setAttribute('aria-pressed', String(open));
  toggle.setAttribute('aria-label', open ? 'Hide attempt details' : 'Show attempt details');
  toggle.title = open ? 'Hide attempt details' : 'Show attempt details';
  if (!open && panel.contains(document.activeElement)) {
    [...document.querySelectorAll('[data-attempt-id]')]
      .find(button => button.dataset.attemptId === selectedAttemptId)?.focus();
  }
}
function markSelectedAttempt() {
  document.querySelectorAll('[data-attempt-id]').forEach(button => {
    button.classList.toggle('active', button.dataset.attemptId === selectedAttemptId);
  });
}
function outcomeBadge(value) {
  return element('span', `badge ${value || 'pending'}`, value || 'pending');
}
const structuredFilterKeys = new Set([
  'outcome', 'phase', 'mode', 'scope', 'location', 'label', 'title', 'link', 'date',
]);
function decodeQueryValue(value) {
  if (value.startsWith('"') && value.endsWith('"')) {
    return value.slice(1, -1).replace(/\\"/g, '"').replace(/\\\\/g, '\\');
  }
  return value;
}
function parseFilterQuery(query) {
  const parsed = {
    text:'', outcome:'', phase:'', mode:'', scope:'latest', location:'',
    labels:[], title:'', link:'', date:'',
  };
  const general = [];
  const tokens = query.match(/[\w-]+:"(?:\\.|[^"])*"|[\w-]+:[^\s]+|"(?:\\.|[^"])*"|[^\s]+/g) || [];
  tokens.forEach(token => {
    const separator = token.indexOf(':');
    const key = separator > 0 ? token.slice(0, separator).toLocaleLowerCase() : '';
    if (!structuredFilterKeys.has(key)) {
      general.push(token);
      return;
    }
    const value = decodeQueryValue(token.slice(separator + 1));
    if (key === 'label') parsed.labels.push(value);
    else parsed[key] = value;
  });
  parsed.text = general.join(' ').trim();
  if (!['latest', 'history'].includes(parsed.scope)) parsed.scope = 'latest';
  return parsed;
}
function quoteQueryValue(value) {
  const normalized = String(value || '').trim();
  if (!normalized) return '';
  return /[\s"]/.test(normalized)
    ? `"${normalized.replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`
    : normalized;
}
function visualLabelValues() {
  return select('#visual-labels').value.split(/[,\s]+/).map(value => value.trim()).filter(Boolean);
}
function updateFilterUi() {
  select('#location-filter').textContent = selectedLocationPath || 'Any location';
  select('#tree-filter-state').textContent = selectedLocationPath || 'All';
  const activeCount = [
    select('#outcome').value,
    select('#phase').value,
    select('#mode').value,
    select('#scope').value === 'history' ? 'history' : '',
    selectedLocationPath,
    ...visualLabelValues(),
    select('#title-filter').value,
    select('#link-filter').value,
    select('#date-filter').value,
  ].filter(Boolean).length;
  select('#filter-count').textContent = activeCount ? String(activeCount) : '';
  select('#filter-toggle').classList.toggle('active', activeCount > 0);
}
function syncQueryFromFilterControls() {
  const parts = [];
  if (freeSearchValue) parts.push(freeSearchValue);
  const add = (key, value) => {
    const encoded = quoteQueryValue(value);
    if (encoded) parts.push(`${key}:${encoded}`);
  };
  add('outcome', select('#outcome').value);
  add('phase', select('#phase').value);
  add('mode', select('#mode').value);
  if (select('#scope').value === 'history') add('scope', 'history');
  add('location', selectedLocationPath);
  visualLabelValues().forEach(label => add('label', label));
  add('title', select('#title-filter').value);
  add('link', select('#link-filter').value);
  add('date', select('#date-filter').value);
  journalSearchValue = parts.join(' ');
  select('#search').value = journalSearchValue;
  updateFilterUi();
  renderCollectionTree();
}
function syncFilterControlsFromQuery(query) {
  const parsed = parseFilterQuery(query);
  const previousScope = select('#scope').value;
  const previousLocationPath = selectedLocationPath;
  freeSearchValue = parsed.text;
  select('#outcome').value = parsed.outcome;
  select('#phase').value = parsed.phase;
  select('#mode').value = parsed.mode;
  select('#scope').value = parsed.scope;
  selectedLocationPath = parsed.location;
  selectedLocationCollectionId = collectionIdForLocationPath(parsed.location);
  select('#visual-labels').value = parsed.labels.join(', ');
  select('#title-filter').value = parsed.title;
  select('#link-filter').value = parsed.link;
  select('#date-filter').value = parsed.date;
  journalSearchValue = query;
  updateFilterUi();
  renderCollectionTree();
  return previousScope !== parsed.scope || previousLocationPath !== parsed.location;
}
function updateOutcomeOptions(outcomes, total) {
  const outcomeSelect = select('#outcome');
  const selectedOutcome = outcomeSelect.value;
  const preferredOrder = ['confirmed', 'provisional', 'review', 'conflict', 'error', 'pending', 'failed'];
  const outcomeNames = [...new Set([...preferredOrder, ...Object.keys(outcomes)])];
  outcomeSelect.replaceChildren(new Option(`All outcomes · ${total}`, ''));
  outcomeNames.forEach(outcome => {
    outcomeSelect.append(new Option(`${outcome} · ${outcomes[outcome] || 0}`, outcome));
  });
  outcomeSelect.value = selectedOutcome;
}
async function renderOverview() {
  const renderGeneration = ++overviewRenderGeneration;
  let overviewData;
  if (selectedLocationPath && selectedLocationCollectionId === null) {
    overviewData = {
      total_bookmarks: 0,
      total_attempts: 0,
      outcomes: {},
      attempt_outcomes: {},
      phases: {},
      attempt_phases: {},
      latest_at: null,
    };
  } else {
    const params = new URLSearchParams();
    if (selectedLocationCollectionId !== null) {
      params.set('collection_id', String(selectedLocationCollectionId));
    }
    overviewData = await fetchJson(
      '/api/overview' + (params.size ? '?' + params : '')
    );
  }
  if (renderGeneration !== overviewRenderGeneration) return;
  const latestOnly = select('#scope').value === 'latest';
  const outcomes = latestOnly ? overviewData.outcomes : overviewData.attempt_outcomes;
  const phases = latestOnly ? overviewData.phases : overviewData.attempt_phases;
  updateOutcomeOptions(outcomes, latestOnly ? overviewData.total_bookmarks : overviewData.total_attempts);
  const phaseSelect = select('#phase');
  const selectedPhase = phaseSelect.value;
  [...phaseSelect.options].slice(1).forEach(option => option.remove());
  Object.keys(phases).forEach(phase => phaseSelect.append(new Option(`${phase} · ${phases[phase]}`, phase)));
  phaseSelect.value = selectedPhase;
  select('#updated').textContent = overviewData.latest_at ? `Latest ${formatTime(overviewData.latest_at)}` : 'No sorter runs yet';
}
function isAssignable(attempt) {
  const retrying = attempt.mode === 'manual-review' && !attempt.outcome
    && ['failed', 'manual_destination_selected'].includes(attempt.current_phase);
  return select('#scope').value === 'latest'
    && (['review', 'provisional', 'conflict'].includes(attempt.outcome) || retrying);
}
function discardPinnedRetry() {
  if (!pinnedRetry) return false;
  const attemptId = pinnedRetry.attempt.attempt_id;
  const wasSelected = selectedAttemptId === attemptId;
  pinnedRetry = null;
  renderedAttempts = renderedAttempts.filter(attempt => attempt.attempt_id !== attemptId);
  selectedAttempts.delete(attemptId);
  if (wasSelected) clearDetail();
  renderCurrentAttempts();
  return true;
}
function openAttempt(attemptId) {
  const discardedRetry = Boolean(
    pinnedRetry && pinnedRetry.attempt.attempt_id !== attemptId
  ) && discardPinnedRetry();
  invalidateDetailSelection();
  renderDetail(attemptId);
  if (discardedRetry) void renderAttempts();
}
function clearBatchMessage() {
  batchMessageGeneration += 1;
  select('#batch-message').textContent = '';
}
function selectionCheckbox(attempt) {
  const checkbox = element('input', 'attempt-select');
  checkbox.type = 'checkbox';
  checkbox.checked = selectedAttempts.has(attempt.attempt_id);
  checkbox.setAttribute('aria-label', `Select ${attempt.title || 'Raindrop ' + attempt.bookmark_id}`);
  checkbox.onclick = event => event.stopPropagation();
  checkbox.onchange = () => {
    clearBatchMessage();
    if (checkbox.checked) {
      selectedAttempts.add(attempt.attempt_id);
      selectionAnchorAttemptId = attempt.attempt_id;
    } else {
      selectedAttempts.delete(attempt.attempt_id);
      if (!selectedAttempts.size) selectionAnchorAttemptId = null;
    }
    if (checkbox.checked) void loadBatchDestinations();
    syncSelectionUi();
  };
  return checkbox;
}
function eligibleRangeTo(attemptId) {
  const eligibleIds = renderedAttempts.filter(isAssignable).map(item => item.attempt_id);
  const end = eligibleIds.indexOf(attemptId);
  const start = eligibleIds.indexOf(selectionAnchorAttemptId);
  if (end < 0) return [];
  if (start < 0) return [attemptId];
  return eligibleIds.slice(Math.min(start, end), Math.max(start, end) + 1);
}
function clearAttemptSelection() {
  selectedAttempts.clear();
  selectionAnchorAttemptId = null;
}
function handleAttemptActivation(event, attempt) {
  const modified = event.ctrlKey || event.metaKey;
  const selecting = selectedAttempts.size > 0 || modified || event.shiftKey;
  if (!selecting) {
    openAttempt(attempt.attempt_id);
    return;
  }
  event.preventDefault();
  if (!isAssignable(attempt)) return;
  clearBatchMessage();
  if (event.shiftKey) {
    const range = eligibleRangeTo(attempt.attempt_id);
    range.forEach(attemptId => selectedAttempts.add(attemptId));
    if (selectionAnchorAttemptId === null) selectionAnchorAttemptId = attempt.attempt_id;
  } else {
    if (selectedAttempts.has(attempt.attempt_id)) selectedAttempts.delete(attempt.attempt_id);
    else selectedAttempts.add(attempt.attempt_id);
    selectionAnchorAttemptId = selectedAttempts.size ? attempt.attempt_id : null;
  }
  syncSelectionUi();
}
function activateAttempt(container, attempt) {
  container.dataset.attemptId = attempt.attempt_id;
  container.tabIndex = 0;
  container.onclick = event => handleAttemptActivation(event, attempt);
  container.onkeydown = event => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      handleAttemptActivation(event, attempt);
    }
  };
}
function renderCard(attempt) {
  const card = element('article', 'attempt'
    + (attempt.attempt_id === selectedAttemptId ? ' active' : '')
    + (selectedAttempts.has(attempt.attempt_id) ? ' selected' : ''));
  activateAttempt(card, attempt);
  const cover = element('div', 'attempt-cover-wrap card-cover-wrap');
  cover.append(previewImage(attempt.bookmark_id, attempt.title, 'attempt-cover', attempt.cover));
  if (isAssignable(attempt)) card.append(selectionCheckbox(attempt));
  const body = element('div', 'attempt-body');
  const header = element('div', 'attempt-head');
  const tools = element('div', 'attempt-tools');
  tools.append(outcomeBadge(attempt.current_phase === 'failed' ? 'failed' : attempt.outcome), raindropLink(attempt.bookmark_id));
  header.append(element('div', 'attempt-title', attempt.title), tools);
  const meta = element('div', 'meta attempt-meta', `#${attempt.bookmark_id} · ${attempt.mode} · ${formatDuration(attempt.duration_ms)}`);
  const footer = element('div', 'attempt-footer');
  if (attempt.destination) footer.append(element('div', 'destination attempt-destination', '→ ' + attempt.destination));
  const startedAt = element('time', 'attempt-time', formatTime(attempt.started_at));
  if (attempt.started_at) startedAt.dateTime = attempt.started_at;
  footer.append(startedAt);
  body.append(header, meta, footer);
  card.append(cover, body);
  return card;
}
function renderTableRow(attempt) {
  const row = element('tr', (attempt.attempt_id === selectedAttemptId ? 'active' : '')
    + (selectedAttempts.has(attempt.attempt_id) ? ' selected' : ''));
  activateAttempt(row, attempt);
  const checkCell = element('td');
  if (isAssignable(attempt)) checkCell.append(selectionCheckbox(attempt));
  const coverCell = element('td');
  const coverWrap = element('div', 'attempt-cover-wrap table-cover-wrap');
  coverWrap.append(previewImage(attempt.bookmark_id, attempt.title, 'table-cover', attempt.cover));
  coverCell.append(coverWrap);
  const titleCell = element('td');
  titleCell.append(element('div', 'table-title', attempt.title), element('div', 'meta', `#${attempt.bookmark_id}`));
  const outcomeCell = element('td'); outcomeCell.append(outcomeBadge(attempt.current_phase === 'failed' ? 'failed' : attempt.outcome));
  const destinationCell = element('td', 'table-destination', attempt.destination ? '→ ' + attempt.destination : '—');
  const runCell = element('td', 'meta', `${attempt.mode} · ${formatDuration(attempt.duration_ms)}`);
  const timeCell = element('td', 'meta', formatTime(attempt.started_at));
  const openCell = element('td'); openCell.append(raindropLink(attempt.bookmark_id));
  row.append(checkCell, coverCell, titleCell, outcomeCell, destinationCell, runCell, timeCell, openCell);
  return row;
}
function cachedAttemptElement(attempt, layout, createElement) {
  const key = String(attempt.attempt_id);
  const signature = JSON.stringify(attempt);
  let cached = attemptElementCache.get(key);
  if (!cached || cached.layout !== layout || cached.signature !== signature) {
    cached = {layout, signature, node:createElement(attempt)};
    attemptElementCache.set(key, cached);
  } else {
    activateAttempt(cached.node, attempt);
    cached.node.classList.toggle('active', attempt.attempt_id === selectedAttemptId);
    cached.node.classList.toggle('selected', selectedAttempts.has(attempt.attempt_id));
  }
  return cached.node;
}
function reconcileChildren(parent, desiredChildren) {
  desiredChildren.forEach((child, index) => {
    const current = parent.children[index];
    if (current !== child) parent.insertBefore(child, current || null);
  });
  while (parent.children.length > desiredChildren.length) parent.lastElementChild.remove();
}
function pruneAttemptElementCache(attempts) {
  const visibleIds = new Set(attempts.map(attempt => String(attempt.attempt_id)));
  [...attemptElementCache.keys()].forEach(key => {
    if (!visibleIds.has(key)) attemptElementCache.delete(key);
  });
}
function renderTable(attempts) {
  const wrap = element('div', 'attempt-table-wrap');
  const table = element('table', 'attempt-table');
  const head = document.createElement('thead');
  const headRow = document.createElement('tr');
  const eligible = attempts.filter(isAssignable);
  const selectAll = element('input');
  selectAll.type = 'checkbox'; selectAll.setAttribute('aria-label', 'Select all assignable Raindrops');
  selectAll.checked = eligible.length > 0 && eligible.every(item => selectedAttempts.has(item.attempt_id));
  selectAll.onchange = () => {
    clearBatchMessage();
    eligible.forEach(item => selectAll.checked ? selectedAttempts.add(item.attempt_id) : selectedAttempts.delete(item.attempt_id));
    selectionAnchorAttemptId = selectAll.checked && eligible.length ? eligible[0].attempt_id : null;
    renderAttemptResults(); syncSelectionUi();
  };
  const headings = [['col-check', selectAll], ['col-cover', 'Image'], ['', 'Title'], ['col-outcome', 'Outcome'], ['', 'Destination'], ['col-run', 'Run'], ['col-time', 'Time'], ['col-open', '']];
  headings.forEach(([className, content]) => {
    const cell = element('th', className);
    cell.scope = 'col';
    if (typeof content === 'string') cell.textContent = content; else cell.append(content);
    headRow.append(cell);
  });
  head.append(headRow); table.append(head);
  const body = document.createElement('tbody');
  attempts.forEach(attempt => body.append(cachedAttemptElement(attempt, 'table', renderTableRow)));
  table.append(body); wrap.append(table); return wrap;
}
function renderAttemptResults() {
  const attemptList = select('#attempts');
  attemptList.className = resultLayout === 'cards' ? 'attempt-grid' : 'attempt-table-wrap';
  let children;
  if (!renderedAttempts.length) {
    children = [element('div', 'empty', 'No attempts match these filters.')];
  } else if (resultLayout === 'cards') {
    children = renderedAttempts.map(attempt => cachedAttemptElement(attempt, 'cards', renderCard));
  } else {
    children = [renderTable(renderedAttempts)];
  }
  reconcileChildren(attemptList, children);
  pruneAttemptElementCache(renderedAttempts);
  select('#card-view').classList.toggle('active', resultLayout === 'cards');
  select('#table-view').classList.toggle('active', resultLayout === 'table');
}
function renderCurrentAttempts() {
  select('#count').textContent = `${renderedAttempts.length} shown`;
  renderAttemptResults();
  syncSelectionUi();
}
function hidePendingAssignments(attempts) {
  const attemptIds = new Set(attempts.map(attempt => attempt.attempt_id));
  attempts.forEach(attempt => {
    pendingAssignmentAttemptIds.add(attempt.attempt_id);
    pendingAssignmentBookmarkIds.add(attempt.bookmark_id);
  });
  attemptsRenderGeneration += 1;
  renderedAttempts = renderedAttempts.filter(attempt => !attemptIds.has(attempt.attempt_id));
}
function releasePendingAssignments(attempts) {
  attemptsRenderGeneration += 1;
  attempts.forEach(attempt => {
    pendingAssignmentAttemptIds.delete(attempt.attempt_id);
    pendingAssignmentBookmarkIds.delete(attempt.bookmark_id);
  });
}
function syncSelectionUi() {
  const visibleIds = new Set(renderedAttempts.map(item => item.attempt_id));
  [...selectedAttempts].filter(id => !visibleIds.has(id)).forEach(id => selectedAttempts.delete(id));
  if (selectionAnchorAttemptId && !visibleIds.has(selectionAnchorAttemptId)) {
    selectionAnchorAttemptId = selectedAttempts.values().next().value || null;
  }
  const count = selectedAttempts.size;
  select('#batch-bar').hidden = count === 0;
  if (count) void loadBatchDestinations();
  syncBatchControls();
  document.querySelectorAll('.attempt-select').forEach(checkbox => {
    const item = checkbox.closest('[data-attempt-id]');
    if (item) checkbox.checked = selectedAttempts.has(item.dataset.attemptId);
  });
  document.querySelectorAll('[data-attempt-id]').forEach(item => {
    const selected = selectedAttempts.has(item.dataset.attemptId);
    item.classList.toggle('selected', selected);
  });
}
function syncBatchControls() {
  const count = selectedAttempts.size;
  select('#selection-count').textContent = `${count} selected`;
  select('#batch-assign').disabled = !count || !select('#batch-destination-search').dataset.collectionId;
}
function showAttemptsLoading() {
  renderedAttempts = [];
  clearAttemptSelection();
  clearDetail();
  select('#count').textContent = 'Loading…';
  const attemptList = select('#attempts');
  attemptList.className = resultLayout === 'cards' ? 'attempt-grid' : 'attempt-table-wrap';
  attemptList.replaceChildren(
    element('div', 'skeleton'),
    element('div', 'skeleton'),
    element('div', 'skeleton'),
  );
}
async function renderAttempts({progressive = false, clearBeforeLoad = true} = {}) {
  const renderGeneration = ++attemptsRenderGeneration;
  const foregroundLoad = progressive && clearBeforeLoad;
  if (foregroundLoad) activeForegroundAttemptsRenderGeneration = renderGeneration;
  try {
  if (selectedLocationPath && selectedLocationCollectionId === null) {
    renderedAttempts = [];
    renderCurrentAttempts();
    return;
  }
  if (progressive && clearBeforeLoad) showAttemptsLoading();
  const params = new URLSearchParams();
  const latestOnly = select('#scope').value === 'latest';
  params.set('latest', latestOnly ? '1' : '0');
  if (freeSearchValue) params.set('q', freeSearchValue);
  if (select('#outcome').value) params.set('outcome', select('#outcome').value);
  if (select('#phase').value) params.set('phase', select('#phase').value);
  if (select('#mode').value) params.set('mode', select('#mode').value);
  if (selectedLocationCollectionId !== null) {
    params.set('collection_id', String(selectedLocationCollectionId));
  }
  visualLabelValues().forEach(label => params.append('label', label));
  if (select('#title-filter').value) params.set('title', select('#title-filter').value);
  if (select('#link-filter').value) params.set('link', select('#link-filter').value);
  if (select('#date-filter').value) params.set('processed_on', select('#date-filter').value);
  params.set('utc_offset_minutes', String(-new Date().getTimezoneOffset()));
  let loadedItems = [];
  let beforeStartedAt = null;
  let beforeAttemptId = null;
  let snapshotStartedAt = null;
  let snapshotAttemptId = null;
  let loadedCount = 0;
  let pageLimit = progressive ? 24 : 500;
  const deferUntilComplete = progressive && !clearBeforeLoad;
  while (loadedCount < 500) {
    params.set('limit', String(Math.min(pageLimit, 500 - loadedCount)));
    if (beforeStartedAt && beforeAttemptId) {
      params.set('before_started_at', beforeStartedAt);
      params.set('before_attempt_id', beforeAttemptId);
    } else {
      params.delete('before_started_at');
      params.delete('before_attempt_id');
    }
    if (snapshotStartedAt && snapshotAttemptId) {
      params.set('snapshot_started_at', snapshotStartedAt);
      params.set('snapshot_attempt_id', snapshotAttemptId);
    }
    const result = await fetchJson('/api/attempts?' + params);
    if (renderGeneration !== attemptsRenderGeneration) return;
    const pageItems = result.items.filter(attempt => (
      !pendingAssignmentAttemptIds.has(attempt.attempt_id)
      && !pendingAssignmentBookmarkIds.has(attempt.bookmark_id)
    ));
    const loadedAttemptIds = new Set(loadedItems.map(attempt => attempt.attempt_id));
    loadedItems = [
      ...loadedItems,
      ...pageItems.filter(attempt => !loadedAttemptIds.has(attempt.attempt_id)),
    ];
    let visibleItems = loadedItems;
    const keepPinnedRetry = pinnedRetry
      && pinnedRetry.query === select('#search').value
      && pinnedRetry.attempt.attempt_id === selectedAttemptId
      && select('#workspace').classList.contains('detail-open')
      && !pendingAssignmentAttemptIds.has(pinnedRetry.attempt.attempt_id)
      && !pendingAssignmentBookmarkIds.has(pinnedRetry.attempt.bookmark_id);
    if (keepPinnedRetry && !visibleItems.some(attempt => attempt.attempt_id === selectedAttemptId)) {
      visibleItems = [pinnedRetry.attempt, ...visibleItems];
    } else if (pinnedRetry && !keepPinnedRetry) {
      pinnedRetry = null;
    }
    loadedCount += result.items.length;
    const hasMore = progressive && result.has_more && loadedCount < 500;
    if (!deferUntilComplete || !hasMore) {
      if (!hasMore && selectedAttemptId && !visibleItems.some(attempt => attempt.attempt_id === selectedAttemptId)) {
        clearDetail();
      }
      renderedAttempts = visibleItems;
      [...selectedAttempts]
        .filter(id => !visibleItems.some(attempt => attempt.attempt_id === id))
        .forEach(id => selectedAttempts.delete(id));
      select('#list-title').textContent = latestOnly ? 'Latest Raindrop status' : 'Attempt history';
      renderCurrentAttempts();
      select('#count').textContent = `${visibleItems.length}${hasMore ? '+' : ''} shown`;
    }
    if (!hasMore || !result.items.length) return;
    beforeStartedAt = result.next_before_started_at;
    beforeAttemptId = result.next_before_attempt_id;
    snapshotStartedAt = result.snapshot_started_at;
    snapshotAttemptId = result.snapshot_attempt_id;
    if (!beforeStartedAt || !beforeAttemptId) return;
    await new Promise(resolve => requestAnimationFrame(resolve));
    pageLimit = 100;
  }
  } finally {
    if (activeForegroundAttemptsRenderGeneration === renderGeneration) {
      activeForegroundAttemptsRenderGeneration = null;
      if (backgroundRefreshPending) {
        backgroundRefreshPending = false;
        void refreshDashboard({progressive:true, clearBeforeLoad:false});
      }
    }
  }
}
function clearDetail() {
  selectedAttemptId = null;
  setDetailOpen(false);
  const detailPanel = select('#detail');
  detailPanel.className = 'empty';
  detailPanel.textContent = select('#scope').value === 'latest'
    ? 'Select a Raindrop to inspect its latest trace.'
    : 'Select an attempt to inspect its complete trace.';
}
function detailSection(title) {
  const container = element('section', 'section');
  container.append(element('h3', '', title));
  return container;
}
function formattedJson(value) {
  const block = element('pre', 'json');
  block.textContent = JSON.stringify(value, null, 2);
  return block;
}
function evidenceDestinations(items) {
  return [...new Set(items.flatMap(item => [item.destination, ...(item.candidates || [])]).filter(Boolean))];
}
async function renderResolution(trace, detailPanel) {
  const attempt = trace.attempt;
  const retrying = attempt.mode === 'manual-review' && !attempt.outcome && ['failed', 'manual_destination_selected'].includes(attempt.current_phase);
  if ((!['review', 'provisional', 'conflict'].includes(attempt.outcome) && !retrying) || select('#scope').value !== 'latest') return;
  const previous = retrying ? [...trace.events].reverse().find(event => event.phase === 'manual_destination_selected')?.payload : null;
  const customOnly = attempt.outcome === 'review' || Boolean(previous?.custom_only);
  const section = element('section', 'resolution');
  section.append(element('h3', '', retrying ? (attempt.current_phase === 'failed' ? 'Retry failed review' : 'Resume interrupted review') : attempt.outcome === 'review' ? 'Assign destination' : attempt.outcome === 'conflict' ? 'Resolve conflict' : 'Approve provisional route'));
  section.append(element('div', 'explain', customOnly ? 'Search and choose a collection in the Art group. Nothing moves until you press Move & confirm.' : 'Choose an evidence destination or any collection in the Art group. Nothing moves until you press Move & confirm.'));
  detailPanel.append(section);
  try {
    const collections = await artCollections();
    const byPath = new Map(collections.map(item => [item.path, item]));
    let selectedCollection = null;
    const allChoiceButtons = [];
    const selection = element('div', 'selection', 'No destination selected');
    const applyButton = element('button', 'apply-choice', 'Move & confirm');
    applyButton.type = 'button'; applyButton.disabled = true;
    const errorBox = element('div', 'resolution-error');
    let selectionSource = 'custom';
    const choose = (collection, button, source) => {
      selectedCollection = collection;
      selectionSource = source;
      allChoiceButtons.forEach(item => item.classList.remove('selected'));
      if (button) button.classList.add('selected');
      selection.textContent = `Selected → ${collection.path}`;
      applyButton.textContent = `Move & confirm → ${collection.path}`;
      applyButton.disabled = false;
      errorBox.textContent = '';
    };
    const addEvidenceChoices = (label, source, destinations) => {
      if (!destinations.length) return;
      const group = element('div', 'choice-group');
      group.append(element('span', 'choice-label', label));
      const grid = element('div', 'choice-grid');
      destinations.forEach(destination => {
        const collection = byPath.get(destination);
        const button = element('button', 'choice', `${source} · ${destination}`);
        button.type = 'button'; button.disabled = !collection;
        if (!collection) button.title = 'This evidence destination is not a live Art collection.';
        else button.onclick = () => choose(collection, button, source.toLocaleLowerCase());
        allChoiceButtons.push(button); grid.append(button);
      });
      group.append(grid); section.append(group);
    };
    if (!customOnly) {
      addEvidenceChoices('Text evidence', 'Text', [...new Set([...evidenceDestinations(attempt.decision?.text_evidence || []), ...(previous?.review_choices?.text || [])])]);
      addEvidenceChoices('Visual evidence', 'Visual', [...new Set([...evidenceDestinations(attempt.decision?.visual_evidence || []), ...(previous?.review_choices?.visual || [])])]);
    }
    if (retrying && !customOnly) {
      if (previous?.destination) addEvidenceChoices('Previous choice', previous.selection_source || 'Custom', [previous.destination]);
    }

    const customGroup = element('div', 'choice-group');
    customGroup.append(element('label', 'choice-label', customOnly ? 'Choose an Art collection' : 'Choose another Art collection'));
    const search = element('input', 'control collection-search');
    search.placeholder = 'Search Art collections'; search.type = 'search';
    const results = element('div', 'collection-results');
    const renderCollections = () => {
      const needle = search.value.trim().toLocaleLowerCase();
      results.replaceChildren();
      collections.filter(item => !needle || item.path.toLocaleLowerCase().includes(needle)).slice(0, 30).forEach(collection => {
        const button = element('button', 'choice', collection.path);
        button.type = 'button'; button.onclick = () => choose(collection, button, 'custom');
        allChoiceButtons.push(button); results.append(button);
      });
      if (!results.children.length) results.append(element('div', 'explain', 'No Art collections match.'));
    };
    search.oninput = renderCollections;
    customGroup.append(search, results); section.append(customGroup);
    renderCollections();
    applyButton.onclick = async () => {
      if (!selectedCollection) return;
      const submittedAttempt = renderedAttempts.find(
        item => item.attempt_id === attempt.attempt_id
      ) || {
        attempt_id: attempt.attempt_id,
        bookmark_id: attempt.bookmark_id,
      };
      applyButton.disabled = true; search.disabled = true; errorBox.textContent = '';
      applyButton.textContent = 'Applying…';
      if (pinnedRetry?.attempt.attempt_id === attempt.attempt_id) pinnedRetry = null;
      hidePendingAssignments([submittedAttempt]);
      invalidateDetailSelection();
      const assignmentRevision = detailSelectionRevision;
      clearDetail();
      renderCurrentAttempts();
      try {
        await postJson(`/api/attempts/${encodeURIComponent(attempt.attempt_id)}/resolve`, {collection_id:selectedCollection.collection_id, selection_source:selectionSource});
        releasePendingAssignments([submittedAttempt]);
        attemptTraceCache.delete(attempt.attempt_id);
        artCollectionsPromise = null;
        refreshDashboardInBackground();
      } catch (error) {
        releasePendingAssignments([submittedAttempt]);
        const restoreSubmittedView = detailSelectionRevision === assignmentRevision;
        if (restoreSubmittedView) {
          const retryAttempt = error.payload?.retry_attempt || submittedAttempt;
          const retryTrace = error.payload?.retry_trace || trace;
          pinnedRetry = {attempt: retryAttempt, query: select('#search').value};
          const visibleAttemptIds = new Set(renderedAttempts.map(item => item.attempt_id));
          if (!visibleAttemptIds.has(retryAttempt.attempt_id)) {
            renderedAttempts = [retryAttempt, ...renderedAttempts];
          }
          attemptTraceCache.set(retryAttempt.attempt_id, {
            value: retryTrace,
            expiresAt: Date.now() + 15_000,
          });
          renderCurrentAttempts();
          const retryAttemptId = retryAttempt.attempt_id;
          await renderDetail(retryAttemptId);
          if (detailSelectionRevision === assignmentRevision) {
            const restoredError = select('#detail .resolution-error');
            if (restoredError) restoredError.textContent = error.message;
          }
        }
        if (!restoreSubmittedView) refreshDashboardInBackground();
      }
    };
    section.append(selection, applyButton, errorBox);
  } catch (error) {
    section.append(element('div', 'resolution-error', error.message));
  }
}
async function renderDetail(attemptId) {
  selectedAttemptId = attemptId;
  const renderRevision = detailSelectionRevision;
  const isStaleRender = () => selectedAttemptId !== attemptId
    || detailSelectionRevision !== renderRevision;
  markSelectedAttempt();
  setDetailOpen(true);
  const detailPanel = select('#detail');
  detailPanel.className = '';
  detailPanel.replaceChildren(element('div', 'skeleton'));
  detailPanel.scrollTop = 0;
  try {
    const trace = await attemptTrace(attemptId);
    if (isStaleRender()) return;
    const attempt = trace.attempt;
    const snapshot = attempt.bookmark_snapshot || {};
    detailPanel.replaceChildren();
    detailPanel.append(outcomeBadge(attempt.current_phase === 'failed' ? 'failed' : attempt.outcome), element('h2', 'detail-title', snapshot.title || `Bookmark ${attempt.bookmark_id}`));
    detailPanel.append(element('div', 'meta', `#${attempt.bookmark_id} · ${attempt.mode} · ${attempt.current_phase} · ${formatTime(attempt.started_at)}`));
    const links = element('div', 'detail-links');
    links.append(raindropLink(attempt.bookmark_id));
    if (snapshot.link) {
      const originalLink = element('a', 'icon-link');
      originalLink.href = snapshot.link; originalLink.target = '_blank'; originalLink.rel = 'noreferrer';
      originalLink.setAttribute('aria-label', 'Open original bookmark'); originalLink.title = 'Open original bookmark';
      originalLink.append(svgIcon('<path d="M5 12h14M13 6l6 6-6 6"/>'));
      links.append(originalLink);
    }
    detailPanel.append(links);
    const preview = previewImage(
      attempt.bookmark_id,
      snapshot.title,
      'bookmark-preview',
      attempt.cover,
    );
    detailPanel.append(preview);
    if (attempt.decision?.summary) detailPanel.append(element('div', 'summary', attempt.decision.summary));
    if (attempt.error) detailPanel.append(element('div', 'error', `${attempt.error.type}: ${attempt.error.message}`));
    await renderResolution(trace, detailPanel);
    if (isStaleRender()) return;
    const evidenceSection = detailSection(`Evidence · ${trace.evidence.length}`);
    trace.evidence.forEach(evidence => {
      const card = element('div', 'card');
      const heading = element('div', 'card-head');
      heading.append(element('strong', '', evidence.source_kind), outcomeBadge(evidence.status));
      card.append(heading);
      if (evidence.destination) card.append(element('div', 'destination', '→ ' + evidence.destination));
      card.append(element('p', 'explain', evidence.explanation));
      if (evidence.details) card.append(formattedJson(evidence.details));
      evidenceSection.append(card);
    });
    detailPanel.append(evidenceSection);
    const actionsSection = detailSection(`Actions · ${trace.actions.length}`);
    if (!trace.actions.length) actionsSection.append(element('div', 'explain', 'No Raindrop action was recorded.'));
    trace.actions.forEach(action => {
      const card = element('div', 'card');
      card.append(element('strong', '', `${action.action_kind} · ${action.status}`));
      if (action.destination) card.append(element('div', 'destination', '→ ' + action.destination));
      card.append(element('div', 'meta', `requests ${action.request_count} · retries ${action.retry_count}${action.latency_ms != null ? ' · ' + formatDuration(action.latency_ms) : ''}`));
      if (action.error_classification) card.append(element('div', 'error', action.error_classification));
      if (action.payload && Object.keys(action.payload).length) card.append(formattedJson(action.payload));
      actionsSection.append(card);
    });
    detailPanel.append(actionsSection);
    const timelineSection = detailSection(`Timeline · ${trace.events.length}`);
    const timeline = element('div', 'timeline');
    trace.events.forEach(event => {
      const eventItem = element('div', 'event');
      eventItem.append(element('strong', '', event.phase), element('div', 'meta', `${formatTime(event.recorded_at)}${event.duration_ms != null ? ' · ' + formatDuration(event.duration_ms) : ''}`));
      if (event.payload && Object.keys(event.payload).length) eventItem.append(formattedJson(event.payload));
      timeline.append(eventItem);
    });
    timelineSection.append(timeline);
    detailPanel.append(timelineSection);
  } catch (error) {
    if (isStaleRender()) return;
    detailPanel.replaceChildren(element('div', 'error', error.message));
  }
}
function persistExpandedCollections() {
  localStorage.setItem(expandedCollectionsStorageKey, JSON.stringify([...expandedCollectionIds]));
}
function collectionFilterPath(group, node) {
  const path = String(node.path || node.title || '').trim();
  const groupTitle = String(group.title || '').trim();
  if (!path || group.id === 'system' || !groupTitle || path === groupTitle || path.startsWith(groupTitle + '/')) return path;
  return `${groupTitle}/${path}`;
}
function collectionIdForLocationPath(locationPath) {
  if (!locationPath) return null;
  let match = null;
  const visit = (group, node) => {
    if (collectionFilterPath(group, node) === locationPath) match = Number(node.id);
    (node.children || []).forEach(child => visit(group, child));
  };
  collectionTreeGroups.forEach(group => {
    (group.collections || []).forEach(node => visit(group, node));
  });
  return match;
}
function selectLocationCollection(node, locationPath) {
  discardPinnedRetry();
  const clearing = selectedLocationPath === locationPath;
  selectedLocationPath = clearing ? '' : locationPath;
  selectedLocationCollectionId = clearing ? null : Number(node.id);
  syncQueryFromFilterControls();
  invalidateDetailSelection();
  clearAttemptSelection();
  clearDetail();
  void refreshDashboard({progressive:true});
}
function renderCollectionTree() {
  const tree = select('#collection-tree');
  tree.replaceChildren();
  const renderNode = (group, node, depth, parent) => {
    const locationPath = collectionFilterPath(group, node);
    const row = element('div', 'collection-row');
    row.style.setProperty('--depth', depth);
    const toggle = element('button', 'collection-toggle', expandedCollectionIds.has(String(node.id)) ? '▾' : '▸');
    toggle.type = 'button';
    toggle.setAttribute('aria-label', `${expandedCollectionIds.has(String(node.id)) ? 'Collapse' : 'Expand'} ${node.path}`);
    toggle.disabled = !(node.children || []).length;
    toggle.onclick = () => {
      const id = String(node.id);
      if (expandedCollectionIds.has(id)) expandedCollectionIds.delete(id); else expandedCollectionIds.add(id);
      persistExpandedCollections();
      renderCollectionTree();
    };
    const button = element('button', 'collection-select' + (selectedLocationPath === locationPath ? ' active' : ''), node.title);
    button.type = 'button'; button.title = locationPath;
    button.setAttribute('aria-pressed', String(selectedLocationPath === locationPath));
    button.onclick = () => selectLocationCollection(node, locationPath);
    row.append(toggle, button, element('span', 'collection-count', String(node.count ?? 0)));
    parent.append(row);
    if ((node.children || []).length && expandedCollectionIds.has(String(node.id))) {
      node.children.forEach(child => renderNode(group, child, depth + 1, parent));
    }
  };
  collectionTreeGroups.forEach(group => {
    const section = element('section', 'collection-group');
    section.append(element('div', 'collection-group-title', group.title));
    const list = element('div', 'collection-list');
    (group.collections || []).forEach(node => renderNode(group, node, 0, list));
    section.append(list); tree.append(section);
  });
  if (!collectionTreeGroups.length) tree.append(element('div', 'library-message', 'Destination tree unavailable.'));
  updateFilterUi();
}
async function loadCollectionTree() {
  try {
    const result = await fetchJson('/api/library/tree');
    collectionTreeGroups = result.groups || [];
    selectedLocationCollectionId = collectionIdForLocationPath(selectedLocationPath);
    renderCollectionTree();
    if (selectedLocationPath) void refreshDashboard({progressive:true});
  } catch (error) {
    select('#collection-tree').replaceChildren(element('div', 'library-message', error.message));
  }
}
async function refreshDashboard({progressive = false, clearBeforeLoad = true} = {}) {
  try {
    if (progressive) {
      await renderAttempts({progressive:true, clearBeforeLoad});
      await renderOverview();
    } else {
      await renderOverview();
      await renderAttempts();
    }
  }
  catch (error) { select('#attempts').replaceChildren(element('div', 'error', error.message)); }
}
function refreshDashboardInBackground() {
  if (activeForegroundAttemptsRenderGeneration !== null) {
    backgroundRefreshPending = true;
    return;
  }
  backgroundRefreshPending = false;
  void refreshDashboard({progressive:true, clearBeforeLoad:false});
}
function closeBatchDestinationResults() {
  const results = select('#batch-destination-results');
  const input = select('#batch-destination-search');
  batchDestinationWantsOpen = false;
  results.hidden = true;
  input.setAttribute('aria-expanded', 'false');
  input.removeAttribute('aria-activedescendant');
}
function chooseBatchDestination(collection) {
  clearBatchMessage();
  const input = select('#batch-destination-search');
  input.dataset.collectionId = String(collection.collection_id);
  input.value = collection.path;
  closeBatchDestinationResults();
  syncBatchControls();
}
function renderBatchDestinationResults() {
  const input = select('#batch-destination-search');
  const results = select('#batch-destination-results');
  batchDestinationWantsOpen = true;
  const terms = input.value.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  const matches = batchDestinationCollections
    .filter(collection => terms.every(term => collection.path.toLocaleLowerCase().includes(term)))
    .slice(0, 100);
  results.replaceChildren();
  if (!matches.length) {
    results.append(element('div', 'batch-destination-empty', 'No matching Art destinations'));
    batchDestinationFocusIndex = -1;
  } else {
    batchDestinationFocusIndex = Math.max(0, Math.min(batchDestinationFocusIndex, matches.length - 1));
    matches.forEach((collection, index) => {
      const option = element('button', 'batch-destination-option' + (index === batchDestinationFocusIndex ? ' active' : ''), collection.path);
      option.type = 'button';
      option.id = `batch-destination-option-${collection.collection_id}`;
      option.tabIndex = -1;
      option.setAttribute('role', 'option');
      option.setAttribute('aria-selected', String(String(collection.collection_id) === input.dataset.collectionId));
      option.onmousedown = event => event.preventDefault();
      option.onclick = () => chooseBatchDestination(collection);
      option.onmousemove = () => {
        batchDestinationFocusIndex = index;
        results.querySelectorAll('[role="option"]').forEach((item, itemIndex) => item.classList.toggle('active', itemIndex === index));
        input.setAttribute('aria-activedescendant', option.id);
      };
      results.append(option);
    });
    input.setAttribute('aria-activedescendant', results.querySelectorAll('[role="option"]')[batchDestinationFocusIndex].id);
  }
  results.hidden = false;
  input.setAttribute('aria-expanded', 'true');
}
async function loadBatchDestinations() {
  const destination = select('#batch-destination-search');
  if (destination.dataset.loaded === 'true') return;
  try {
    const collections = await artCollections();
    const selected = destination.dataset.collectionId || '';
    batchDestinationCollections = collections;
    const selectedCollection = collections.find(item => String(item.collection_id) === selected);
    if (selectedCollection) destination.value = selectedCollection.path;
    else if (selected) {
      delete destination.dataset.collectionId;
      destination.value = '';
      syncSelectionUi();
    }
    destination.dataset.loaded = 'true';
  } catch (error) {
    select('#batch-message').textContent = error.message;
  }
}
async function assignSelected() {
  const collectionId = Number(select('#batch-destination-search').dataset.collectionId);
  if (!collectionId || !selectedAttempts.size) return;
  const submittedAttemptIds = new Set(selectedAttempts);
  const submittedAttempts = renderedAttempts.filter(attempt => submittedAttemptIds.has(attempt.attempt_id));
  const previousSelectionAnchorAttemptId = selectionAnchorAttemptId;
  const messageGeneration = ++batchMessageGeneration;
  const button = select('#batch-assign');
  button.disabled = true;
  select('#batch-message').textContent = 'Assigning…';
  if (pinnedRetry && submittedAttemptIds.has(pinnedRetry.attempt.attempt_id)) {
    pinnedRetry = null;
  }
  hidePendingAssignments(submittedAttempts);
  clearAttemptSelection();
  renderCurrentAttempts();
  try {
    const result = await postJson('/api/attempts/resolve-batch', {
      attempt_ids:[...submittedAttemptIds], collection_id:collectionId,
    });
    const failedAttempts = new Map(result.errors.map(item => [item.attempt_id, item]));
    const successfulAttemptIds = new Set(
      [...submittedAttemptIds].filter(attemptId => !failedAttempts.has(attemptId))
    );
    const failedCards = submittedAttempts.flatMap(attempt => {
      const failure = failedAttempts.get(attempt.attempt_id);
      return failure?.retry_attempt ? [failure.retry_attempt] : [];
    });
    releasePendingAssignments(submittedAttempts);
    const visibleAttemptIds = new Set(renderedAttempts.map(attempt => attempt.attempt_id));
    renderedAttempts = [
      ...failedCards.filter(attempt => !visibleAttemptIds.has(attempt.attempt_id)),
      ...renderedAttempts,
    ];
    result.errors.forEach(item => selectedAttempts.add(item.retry_attempt_id || item.attempt_id));
    if (!selectionAnchorAttemptId) {
      selectionAnchorAttemptId = selectedAttempts.values().next().value || null;
    }
    if (selectedAttemptId && successfulAttemptIds.has(selectedAttemptId)) clearDetail();
    clearDataCaches();
    if (batchMessageGeneration === messageGeneration) {
      select('#batch-message').textContent = result.failed
        ? `${result.resolved} assigned · ${result.failed} failed`
        : `${result.resolved} assigned`;
    }
    renderCurrentAttempts();
    refreshDashboardInBackground();
  } catch (error) {
    releasePendingAssignments(submittedAttempts);
    const visibleAttemptIds = new Set(renderedAttempts.map(attempt => attempt.attempt_id));
    renderedAttempts = [
      ...submittedAttempts.filter(attempt => !visibleAttemptIds.has(attempt.attempt_id)),
      ...renderedAttempts,
    ];
    submittedAttemptIds.forEach(attemptId => selectedAttempts.add(attemptId));
    if (!selectionAnchorAttemptId) {
      selectionAnchorAttemptId = previousSelectionAnchorAttemptId;
    }
    renderCurrentAttempts();
    if (batchMessageGeneration === messageGeneration) {
      select('#batch-message').textContent = error.message;
    }
  }
}
function renderSorterStatus(status) {
  const state = status.state || 'unknown';
  select('#sorter-state').textContent = state;
  const completed = status.attempted == null ? (status.processed || 0) : status.attempted;
  const summary = status.available
    ? `${completed} completed · ${status.processed || 0} succeeded${status.failed ? ` · ${status.failed} failed` : ''}${status.last_count == null ? '' : ` · last batch ${status.last_count}`}${status.last_error ? ` · ${status.last_error}` : ''}`
    : (status.error || 'Sorter controls unavailable');
  select('#sorter-summary').textContent = summary;
  select('#process-all').disabled = !status.available || status.automatic || status.processing_all || state === 'running';
  select('#sorter-stop').disabled = !status.available || !status.processing_all;
  select('#sorter-start').disabled = !status.available || status.automatic || status.processing_all || state === 'stopping';
  select('#sorter-pause').disabled = !status.available || !status.automatic;
  select('#sorter-start').classList.toggle('active', Boolean(status.automatic));
}
async function refreshSorterStatus() {
  try { renderSorterStatus(await fetchJson('/api/sorter/status')); }
  catch (error) { renderSorterStatus({available:false, state:'error', error:error.message}); }
}
async function sorterAction(action) {
  try {
    renderSorterStatus(await postJson(`/api/sorter/${action}`, {}));
    setTimeout(refreshSorterStatus, 300);
  } catch (error) {
    select('#sorter-summary').textContent = error.message;
  }
}
select('#filters').onsubmit = event => {
  event.preventDefault();
  invalidateDetailSelection();
  clearCaches();
  refreshDashboard({progressive:true});
};
let searchTimer;
select('#search').oninput = () => {
  clearTimeout(searchTimer);
  discardPinnedRetry();
  const overviewChanged = syncFilterControlsFromQuery(select('#search').value);
  invalidateDetailSelection();
  if (overviewChanged) {
    clearAttemptSelection();
    clearDetail();
  }
  attemptsRenderGeneration += 1;
  showAttemptsLoading();
  const action = overviewChanged
    ? () => refreshDashboard({progressive:true})
    : () => renderAttempts({progressive:true});
  searchTimer = setTimeout(action, 250);
};
function applyFilterControlChange({overviewChanged = false, immediate = true} = {}) {
  clearTimeout(searchTimer);
  discardPinnedRetry();
  syncQueryFromFilterControls();
  invalidateDetailSelection();
  if (overviewChanged) {
    clearAttemptSelection();
    clearDetail();
  }
  const action = overviewChanged
    ? () => refreshDashboard({progressive:true})
    : () => renderAttempts({progressive:true});
  if (!immediate) {
    attemptsRenderGeneration += 1;
    showAttemptsLoading();
  }
  if (immediate) void action();
  else searchTimer = setTimeout(action, 250);
}
select('#outcome').onchange = () => applyFilterControlChange();
select('#phase').onchange = () => applyFilterControlChange();
select('#mode').onchange = () => applyFilterControlChange();
select('#scope').onchange = () => applyFilterControlChange({overviewChanged:true});
['#visual-labels', '#title-filter', '#link-filter', '#date-filter'].forEach(selector => {
  select(selector).oninput = () => applyFilterControlChange({immediate:false});
});
select('#location-clear').onclick = () => {
  selectedLocationPath = '';
  selectedLocationCollectionId = null;
  applyFilterControlChange({overviewChanged:true});
};
select('#reset-filters').onclick = () => {
  discardPinnedRetry();
  freeSearchValue = '';
  selectedLocationPath = '';
  selectedLocationCollectionId = null;
  select('#outcome').value = '';
  select('#phase').value = '';
  select('#mode').value = '';
  select('#scope').value = 'latest';
  select('#visual-labels').value = '';
  select('#title-filter').value = '';
  select('#link-filter').value = '';
  select('#date-filter').value = '';
  clearAttemptSelection();
  clearDetail();
  syncQueryFromFilterControls();
  void refreshDashboard({progressive:true});
};
select('#filter-toggle').onclick = () => {
  const panel = select('#filter-panel');
  panel.hidden = !panel.hidden;
  select('#filter-toggle').setAttribute('aria-expanded', String(!panel.hidden));
  select('#filter-toggle').setAttribute('aria-label', panel.hidden ? 'Show filters' : 'Hide filters');
  select('#filter-toggle').title = panel.hidden ? 'Show filters' : 'Hide filters';
};
select('#card-view').onclick = () => {
  resultLayout = 'cards'; localStorage.setItem('sorter-result-layout', resultLayout); renderAttemptResults(); syncSelectionUi();
};
select('#table-view').onclick = () => {
  resultLayout = 'table'; localStorage.setItem('sorter-result-layout', resultLayout); renderAttemptResults(); syncSelectionUi();
};
select('#batch-destination-search').onfocus = async event => {
  batchDestinationWantsOpen = true;
  await loadBatchDestinations();
  if (!batchDestinationWantsOpen || document.activeElement !== event.target) return;
  batchDestinationFocusIndex = 0;
  renderBatchDestinationResults();
  event.target.select();
};
select('#batch-destination-search').oninput = () => {
  clearBatchMessage();
  delete select('#batch-destination-search').dataset.collectionId;
  batchDestinationFocusIndex = 0;
  renderBatchDestinationResults();
  syncBatchControls();
};
select('#batch-destination-search').onkeydown = event => {
  const results = select('#batch-destination-results');
  if (event.key === 'Escape') { closeBatchDestinationResults(); return; }
  if (!['ArrowDown', 'ArrowUp', 'Enter'].includes(event.key)) return;
  event.preventDefault();
  if (results.hidden) renderBatchDestinationResults();
  const options = [...results.querySelectorAll('[role="option"]')];
  if (!options.length) return;
  if (event.key === 'Enter') { options[batchDestinationFocusIndex]?.click(); return; }
  const direction = event.key === 'ArrowDown' ? 1 : -1;
  batchDestinationFocusIndex = (batchDestinationFocusIndex + direction + options.length) % options.length;
  options.forEach((option, index) => option.classList.toggle('active', index === batchDestinationFocusIndex));
  select('#batch-destination-search').setAttribute('aria-activedescendant', options[batchDestinationFocusIndex].id);
  options[batchDestinationFocusIndex].scrollIntoView({block:'nearest'});
};
select('#batch-destination-search').onblur = () => setTimeout(closeBatchDestinationResults, 100);
select('#batch-assign').onclick = assignSelected;
select('#selection-clear').onclick = () => { clearBatchMessage(); clearAttemptSelection(); renderAttemptResults(); syncSelectionUi(); };
select('#sorter-toggle').onclick = () => {
  const panel = select('#sorter-panel');
  panel.hidden = !panel.hidden;
  select('#sorter-toggle').classList.toggle('active', !panel.hidden);
  select('#sorter-toggle').setAttribute('aria-label', panel.hidden ? 'Show sorter controls' : 'Hide sorter controls');
  if (!panel.hidden) refreshSorterStatus();
};
select('#process-all').onclick = () => {
  if (confirm('Process every actionable Raindrop in Unsorted now? This applies tags and may move items.')) sorterAction('process-all');
};
select('#sorter-stop').onclick = () => sorterAction('stop');
select('#sorter-start').onclick = () => {
  if (confirm('Start the automatic sorter? It applies tags and may move current and future Unsorted items.')) sorterAction('start');
};
select('#sorter-pause').onclick = () => sorterAction('pause');
select('#detail-toggle').onclick = () => {
  const opening = !select('#workspace').classList.contains('detail-open');
  if (opening) {
    setDetailOpen(true);
    return;
  }
  invalidateDetailSelection();
  if (pinnedRetry?.attempt.attempt_id === selectedAttemptId) {
    discardPinnedRetry();
    clearDetail();
    void renderAttempts();
  } else {
    setDetailOpen(false);
  }
};
function closeAttemptDetail() {
  invalidateDetailSelection();
  if (pinnedRetry?.attempt.attempt_id === selectedAttemptId) {
    discardPinnedRetry();
    clearDetail();
    void renderAttempts();
  } else {
    setDetailOpen(false);
  }
}
select('#detail-close').onclick = closeAttemptDetail;
select('#detail-scrim').onclick = closeAttemptDetail;
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && select('#workspace').classList.contains('detail-open')) {
    closeAttemptDetail();
  }
});
syncQueryFromFilterControls();
refreshDashboard({progressive:true});
refreshSorterStatus();
void loadCollectionTree();
setInterval(refreshDashboardInBackground, 15000);
setInterval(refreshSorterStatus, 1000);
</script></body></html>"""
