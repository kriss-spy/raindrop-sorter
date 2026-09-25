"""Self-contained browser asset for the local journal dashboard."""

DASHBOARD_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Raindrop Journal</title>
<style>
:root{color-scheme:dark;--bg:#0a0f14;--panel:#111820;--line:#26323d;--muted:#8fa0ae;--text:#edf4f7;--cyan:#61d7d7;--lime:#a8db67;--amber:#f2bd62;--red:#f07878;--violet:#b9a0ff}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 10% 0,#12252a 0,transparent 32rem),var(--bg);color:var(--text);font:14px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace}button,input,select{font:inherit}.shell{max-width:1500px;margin:auto;padding:30px}.top{display:flex;justify-content:space-between;gap:24px;align-items:flex-start;margin-bottom:24px}.eyebrow{color:var(--cyan);letter-spacing:.15em;text-transform:uppercase;font-size:11px}.brand{font:700 clamp(28px,4vw,48px)/1.1 system-ui;margin:7px 0}.sub{color:var(--muted);max-width:650px}.live{display:flex;align-items:center;gap:8px;color:var(--muted);white-space:nowrap}.dot{width:9px;height:9px;border-radius:50%;background:var(--lime);box-shadow:0 0 14px var(--lime)}.stats{display:grid;grid-template-columns:repeat(6,1fr);gap:12px;margin-bottom:18px}.stat,.panel{background:color-mix(in srgb,var(--panel) 94%,transparent);border:1px solid var(--line);border-radius:12px}.stat{padding:15px}.stat b{display:block;font:700 26px system-ui;margin-top:5px}.stat span{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.08em}.toolbar{display:grid;grid-template-columns:minmax(220px,1fr) 170px 190px 170px auto;gap:10px;margin-bottom:14px}.control{border:1px solid var(--line);background:#0e151c;color:var(--text);border-radius:9px;padding:11px 13px;outline:none}.control:focus{border-color:var(--cyan)}button.control{cursor:pointer;color:var(--cyan)}.workspace{display:grid;grid-template-columns:minmax(430px,.9fr) minmax(480px,1.1fr);gap:14px;min-height:560px}.panel{overflow:hidden}.panel-head{padding:13px 16px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;color:var(--muted)}#attempts{max-height:72vh;overflow:auto}.attempt{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;padding:15px 16px;border:0;border-bottom:1px solid var(--line);background:transparent;color:inherit;width:100%;text-align:left;cursor:pointer}.attempt:hover,.attempt.active{background:#17232b}.attempt.active{box-shadow:inset 3px 0 var(--cyan)}.attempt-title{font:650 15px system-ui;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.meta,.when{color:var(--muted);font-size:12px}.destination{color:var(--cyan)}.badge{align-self:start;border:1px solid currentColor;border-radius:99px;padding:2px 8px;font-size:10px;text-transform:uppercase}.confirmed{color:var(--lime)}.provisional{color:var(--amber)}.review,.pending{color:var(--violet)}.conflict,.failed{color:var(--red)}#detail{padding:22px;max-height:72vh;overflow:auto}.empty{display:grid;place-content:center;text-align:center;color:var(--muted);min-height:400px}.detail-title{font:700 24px system-ui;margin:4px 0}.external{color:var(--cyan);text-decoration:none}.bookmark-preview{display:block;width:100%;max-height:430px;object-fit:contain;background:#070b0f;border:1px solid var(--line);border-radius:10px;margin:18px 0}.summary{border-left:3px solid var(--cyan);padding:10px 14px;background:#0c151b;margin:18px 0}.section{margin-top:24px}.section h3{font:650 13px system-ui;text-transform:uppercase;letter-spacing:.1em;color:var(--muted)}.card{border:1px solid var(--line);border-radius:9px;padding:12px;margin:9px 0;background:#0d141a}.card-head{display:flex;justify-content:space-between;gap:8px}.explain{color:var(--muted);margin:6px 0 0}.timeline{border-left:1px solid var(--line);margin-left:6px;padding-left:18px}.event{position:relative;margin:13px 0}.event:before{content:"";position:absolute;width:7px;height:7px;border-radius:50%;background:var(--cyan);left:-22px;top:7px}.json{white-space:pre-wrap;overflow-wrap:anywhere;color:var(--muted);font-size:11px;background:#080d11;padding:10px;border-radius:7px}.error{color:var(--red);padding:20px}.skeleton{height:72px;background:linear-gradient(90deg,#111820,#18242c,#111820);background-size:200%;animation:p 1.2s infinite}@keyframes p{to{background-position:-200%}}@media(max-width:1100px){.toolbar{grid-template-columns:1fr 1fr 1fr}.toolbar button{grid-column:span 3}}@media(max-width:950px){.stats{grid-template-columns:repeat(2,1fr)}.toolbar,.workspace{grid-template-columns:1fr}.toolbar button{grid-column:auto}.workspace{min-height:0}#attempts,#detail{max-height:none}.live{display:none}}@media(max-width:520px){.shell{padding:18px}.stats{grid-template-columns:1fr 1fr}.top{margin-bottom:18px}}
.resolution{border:1px solid color-mix(in srgb,var(--amber) 55%,var(--line));border-radius:11px;padding:16px;margin:18px 0;background:#17150f}.resolution h3{margin:0 0 7px;font:700 16px system-ui}.choice-group{margin-top:14px}.choice-label{display:block;color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.08em;margin-bottom:7px}.choice-grid,.collection-results{display:flex;flex-wrap:wrap;gap:7px}.choice{border:1px solid var(--line);background:#101820;color:var(--text);border-radius:8px;padding:8px 10px;cursor:pointer;text-align:left}.choice:hover,.choice.selected{border-color:var(--cyan);color:var(--cyan);background:#102126}.choice:disabled{cursor:not-allowed;opacity:.45}.collection-search{width:100%;margin-bottom:8px}.collection-results{max-height:155px;overflow:auto}.selection{color:var(--cyan);margin:14px 0 9px}.apply-choice{width:100%;background:var(--cyan);color:#071013;border:0;border-radius:8px;padding:11px;font-weight:750;cursor:pointer}.apply-choice:disabled{cursor:not-allowed;opacity:.45}.resolution-error{color:var(--red);margin-top:9px}
</style></head><body><main class="shell">
<header class="top"><div><div class="eyebrow">local operator view</div><h1 class="brand">Raindrop Journal</h1><div class="sub">Every routing decision, its evidence, and what the sorter did next.</div></div><div class="live"><i class="dot"></i><span id="updated">Connecting…</span></div></header>
<section class="stats" id="stats"></section>
<form class="toolbar" id="filters"><input class="control" id="search" placeholder="Search bookmarks, destinations, summaries"><select class="control" id="outcome"><option value="">All outcomes</option><option>confirmed</option><option>provisional</option><option>review</option><option>conflict</option><option>pending</option></select><select class="control" id="phase"><option value="">All lifecycle phases</option></select><select class="control" id="scope" aria-label="Journal view"><option value="latest">Latest status</option><option value="history">Attempt history</option></select><button class="control" type="submit">Refresh journal</button></form>
<section class="workspace"><div class="panel"><div class="panel-head"><span id="list-title">Latest Raindrop status</span><span id="count">—</span></div><div id="attempts"><div class="skeleton"></div><div class="skeleton"></div></div></div><div class="panel"><div id="detail" class="empty">Select a Raindrop to inspect its latest trace.</div></div></section>
</main><script>
const select = selector => document.querySelector(selector);
const element = (tag, className, text) => {
  const created = document.createElement(tag);
  if (className) created.className = className;
  if (text !== undefined) created.textContent = text;
  return created;
};
let selectedAttemptId = null;
const formatTime = timestamp => timestamp
  ? new Intl.DateTimeFormat(undefined, {dateStyle:'medium', timeStyle:'short'}).format(new Date(timestamp))
  : 'running';
const formatDuration = milliseconds => milliseconds == null
  ? 'running'
  : milliseconds < 1000 ? `${Math.round(milliseconds)} ms` : `${(milliseconds / 1000).toFixed(1)} s`;
async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error((await response.json()).error || response.statusText);
  return response.json();
}
async function postJson(url, payload) {
  const response = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
  if (!response.ok) throw new Error((await response.json()).error || response.statusText);
  return response.json();
}
function artCollections() {
  return fetchJson('/api/review/collections').then(result => result.items);
}
function outcomeBadge(value) {
  return element('span', `badge ${value || 'pending'}`, value || 'pending');
}
async function renderOverview() {
  const overviewData = await fetchJson('/api/overview');
  const statsPanel = select('#stats');
  statsPanel.replaceChildren();
  const latestOnly = select('#scope').value === 'latest';
  const outcomes = latestOnly ? overviewData.outcomes : overviewData.attempt_outcomes;
  const phases = latestOnly ? overviewData.phases : overviewData.attempt_phases;
  const stats = [[latestOnly ? 'Raindrops' : 'Attempts', latestOnly ? overviewData.total_bookmarks : overviewData.total_attempts], ['Confirmed', outcomes.confirmed || 0], ['Provisional', outcomes.provisional || 0], ['Review', outcomes.review || 0], ['Conflict', outcomes.conflict || 0], ['Failed', outcomes.failed || 0]];
  stats.forEach(([label, value]) => {
    const card = element('div', 'stat');
    card.append(element('span', '', label), element('b', '', value));
    statsPanel.append(card);
  });
  const phaseSelect = select('#phase');
  const selectedPhase = phaseSelect.value;
  [...phaseSelect.options].slice(1).forEach(option => option.remove());
  Object.keys(phases).forEach(phase => phaseSelect.append(new Option(`${phase} · ${phases[phase]}`, phase)));
  phaseSelect.value = selectedPhase;
  select('#updated').textContent = overviewData.latest_at ? `Latest ${formatTime(overviewData.latest_at)}` : 'Journal is empty';
}
async function renderAttempts() {
  const params = new URLSearchParams({limit:'500'});
  const latestOnly = select('#scope').value === 'latest';
  params.set('latest', latestOnly ? '1' : '0');
  if (select('#search').value) params.set('q', select('#search').value);
  if (select('#outcome').value) params.set('outcome', select('#outcome').value);
  if (select('#phase').value) params.set('phase', select('#phase').value);
  const result = await fetchJson('/api/attempts?' + params);
  if (selectedAttemptId && !result.items.some(attempt => attempt.attempt_id === selectedAttemptId)) clearDetail();
  const attemptList = select('#attempts');
  attemptList.replaceChildren();
  select('#list-title').textContent = latestOnly ? 'Latest Raindrop status' : 'Attempt history';
  select('#count').textContent = `${result.count} shown`;
  if (!result.items.length) {
    attemptList.append(element('div', 'empty', 'No attempts match these filters.'));
    return;
  }
  result.items.forEach(attempt => {
    const button = element('button', 'attempt' + (attempt.attempt_id === selectedAttemptId ? ' active' : ''));
    button.type = 'button';
    const identity = element('div');
    identity.append(element('div', 'attempt-title', attempt.title), element('div', 'meta', `#${attempt.bookmark_id} · ${attempt.mode} · ${formatDuration(attempt.duration_ms)}`));
    if (attempt.destination) identity.append(element('div', 'destination', '→ ' + attempt.destination));
    const resultMeta = element('div');
    resultMeta.append(outcomeBadge(attempt.current_phase === 'failed' ? 'failed' : attempt.outcome), element('div', 'when', formatTime(attempt.started_at)));
    button.append(identity, resultMeta);
    button.onclick = () => renderDetail(attempt.attempt_id);
    attemptList.append(button);
  });
}
function clearDetail() {
  selectedAttemptId = null;
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
  if ((!['provisional', 'conflict'].includes(attempt.outcome) && !retrying) || select('#scope').value !== 'latest') return;
  const section = element('section', 'resolution');
  section.append(element('h3', '', retrying ? (attempt.current_phase === 'failed' ? 'Retry failed review' : 'Resume interrupted review') : attempt.outcome === 'conflict' ? 'Resolve conflict' : 'Approve provisional route'));
  section.append(element('div', 'explain', 'Choose an evidence destination or any collection in the Art group. Nothing moves until you press Move & confirm.'));
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
    const previous = retrying ? [...trace.events].reverse().find(event => event.phase === 'manual_destination_selected')?.payload : null;
    addEvidenceChoices('Text evidence', 'Text', [...new Set([...evidenceDestinations(attempt.decision?.text_evidence || []), ...(previous?.review_choices?.text || [])])]);
    addEvidenceChoices('Visual evidence', 'Visual', [...new Set([...evidenceDestinations(attempt.decision?.visual_evidence || []), ...(previous?.review_choices?.visual || [])])]);
    if (retrying) {
      if (previous?.destination) addEvidenceChoices('Previous choice', previous.selection_source || 'Custom', [previous.destination]);
    }

    const customGroup = element('div', 'choice-group');
    customGroup.append(element('label', 'choice-label', 'Choose another Art collection'));
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
      applyButton.disabled = true; search.disabled = true; errorBox.textContent = '';
      applyButton.textContent = 'Applying…';
      try {
        const result = await postJson(`/api/attempts/${encodeURIComponent(attempt.attempt_id)}/resolve`, {collection_id:selectedCollection.collection_id, selection_source:selectionSource});
        await refreshDashboard();
        await renderDetail(result.attempt_id);
      } catch (error) {
        errorBox.textContent = error.message;
        try {
          const latest = await fetchJson(`/api/attempts?latest=1&limit=10&q=${encodeURIComponent(attempt.bookmark_id)}`);
          const latestAttempt = latest.items.find(item => item.bookmark_id === attempt.bookmark_id);
          if (latestAttempt && latestAttempt.attempt_id !== attempt.attempt_id) {
            await refreshDashboard();
            await renderDetail(latestAttempt.attempt_id);
            return;
          }
        } catch (_refreshError) {
          // Keep the original error visible and let the user retry refreshing manually.
        }
        applyButton.disabled = false; search.disabled = false;
        applyButton.textContent = `Move & confirm → ${selectedCollection.path}`;
      }
    };
    section.append(selection, applyButton, errorBox);
  } catch (error) {
    section.append(element('div', 'resolution-error', error.message));
  }
}
async function renderDetail(attemptId) {
  selectedAttemptId = attemptId;
  await renderAttempts();
  const detailPanel = select('#detail');
  detailPanel.className = '';
  detailPanel.replaceChildren(element('div', 'skeleton'));
  try {
    const trace = await fetchJson('/api/attempts/' + encodeURIComponent(attemptId));
    const attempt = trace.attempt;
    const snapshot = attempt.bookmark_snapshot || {};
    detailPanel.replaceChildren();
    detailPanel.append(outcomeBadge(attempt.current_phase === 'failed' ? 'failed' : attempt.outcome), element('h2', 'detail-title', snapshot.title || `Bookmark ${attempt.bookmark_id}`));
    detailPanel.append(element('div', 'meta', `#${attempt.bookmark_id} · ${attempt.mode} · ${attempt.current_phase} · ${formatTime(attempt.started_at)}`));
    if (snapshot.link) {
      const originalLink = element('a', 'external', 'Open original ↗');
      originalLink.href = snapshot.link; originalLink.target = '_blank'; originalLink.rel = 'noreferrer';
      detailPanel.append(originalLink);
    }
    const preview = element('img', 'bookmark-preview');
    preview.src = `/api/bookmarks/${attempt.bookmark_id}/preview`;
    preview.alt = snapshot.title ? `Preview of ${snapshot.title}` : `Preview of bookmark ${attempt.bookmark_id}`;
    preview.loading = 'lazy';
    preview.onerror = () => preview.remove();
    detailPanel.append(preview);
    if (attempt.decision?.summary) detailPanel.append(element('div', 'summary', attempt.decision.summary));
    if (attempt.error) detailPanel.append(element('div', 'error', `${attempt.error.type}: ${attempt.error.message}`));
    await renderResolution(trace, detailPanel);
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
    detailPanel.replaceChildren(element('div', 'error', error.message));
  }
}
async function refreshDashboard() {
  try { await renderOverview(); await renderAttempts(); }
  catch (error) { select('#attempts').replaceChildren(element('div', 'error', error.message)); }
}
select('#filters').onsubmit = event => { event.preventDefault(); refreshDashboard(); };
let searchTimer;
select('#search').oninput = () => { clearTimeout(searchTimer); searchTimer = setTimeout(renderAttempts, 250); };
select('#outcome').onchange = renderAttempts;
select('#phase').onchange = renderAttempts;
select('#scope').onchange = () => {
  clearDetail();
  refreshDashboard();
};
refreshDashboard();
setInterval(refreshDashboard, 15000);
</script></body></html>"""
