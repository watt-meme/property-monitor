// app.js — Property Monitor v4.1
// No Python f-string escaping. Edit freely.

const DISCARD_REASONS = [
  "Too expensive for what it is",
  "Wrong / poor location",
  "Poor layout",
  "Condition / needs too much work",
  "Not enough natural light",
  "Too small",
  "Modern / new build",
  "Traffic road — not acceptable",
  "Already seen / viewing done",
  "Went under offer",
  "Other"
];

// ── Persisted state ──────────────────────────────────────────────────────────────────
const LS_KEY   = 'pm_feedback_v1';
const LS_NOTES = 'pm_notes_v1';
let feedbackState = {};
let notesState    = {};
try { feedbackState = JSON.parse(localStorage.getItem(LS_KEY)   || '{}'); } catch(e) {}
try { notesState    = JSON.parse(localStorage.getItem(LS_NOTES) || '{}'); } catch(e) {}

function _saveFeedback() {
  try { localStorage.setItem(LS_KEY, JSON.stringify(feedbackState)); } catch(e) {}
}
function saveNote(id, val) {
  notesState[id] = val;
  try { localStorage.setItem(LS_NOTES, JSON.stringify(notesState)); } catch(e) {}
}

// ── Build cards ─────────────────────────────────────────────────────────────────────
function buildCard(l) {
  const scoreCol    = l.score_colour;
  const periodBadge = l.period_label
    ? `<span class="badge badge-period" style="background:${l.period_colour}">${l.period_label}</span>` : '';
  const tenureBadge = l.tenure === 'freehold'
    ? '<span class="badge badge-tenure-fh">Freehold</span>'
    : l.tenure === 'leasehold' ? '<span class="badge badge-tenure-lh">Leasehold</span>' : '';
  const reducedBadge = l.is_reduced
    ? `<span class="badge badge-reduced">&#8595;${Math.abs(l.reduction_pct).toFixed(1)}%</span>` : '';
  const trafficBadge = l.traffic_road
    ? `<span class="badge badge-traffic" title="${l.traffic_road} (${l.traffic_penalty}pts)">&#128675; ${l.traffic_road}</span>` : '';
  const staleBadge = l.stale_unmotivated
    ? `<span class="badge badge-stale" title="${l.days_num} days listed, no price cut">${l.days_num}d no cut</span>` : '';

  const ppsfHtml = l.ppsf
    ? `<span class="card-ppsf" style="color:${l.ppsf_colour}">&#163;${l.ppsf.toLocaleString()}/sqft</span>`
      + (l.sqft ? ` <span class="dot">·</span> ${l.sqft.toLocaleString()} sqft` : '')
    : '<span style="color:#5a5652">no sqft</span>';

  const streetHtml = l.street_ppsf ? (() => {
    const diff    = l.ppsf ? l.ppsf - l.street_ppsf : null;
    const diffCol = diff > 50 ? '#e05252' : diff < -50 ? '#4caf82' : '#5a5652';
    const diffStr = diff !== null
      ? ` <span class="vs-street" style="color:${diffCol}">${diff >= 0 ? '+' : ''}${diff} vs street</span>`
      : '';
    return `<div class="street-comp">Street avg &#163;${l.street_ppsf.toLocaleString()}/sqft${diffStr}</div>`;
  })() : '';

  const oppHtml = (l.opp_score && l.opp_score - l.score > 2)
    ? `<div style="margin-top:3px"><span class="opp-score opp-high" title="Opportunity score">opp ${l.opp_score}</span></div>` : '';

  const ai = l.ai || {};
  let aiHtml = '';
  if (ai.flags && ai.flags.length) {
    const iconMap = {
      'Kitchen on different floor':     ['🍳', '⚠', 'warn'],
      'Kitchen: structural move needed': ['🍳', '~', 'info'],
      'Kitchen opens to reception':     ['🍳', '✓', 'good'],
      'Through reception':              ['🚪', '✓', 'good'],
      'Extension potential':            ['📐', '+', 'good'],
      'Large garden':                   ['🌿', 'L', 'good'],
      'Medium garden':                  ['🌿', 'M', 'good'],
      'Small garden':                   ['🌿', 'S', 'info'],
      'Patio only':                     ['🌿', '~', 'info'],
      'No garden':                      ['🌿', '✗', 'warn'],
    };
    const iconRow = ai.flags.map(f => {
      const m = iconMap[f.text];
      if (m) return `<span class="ai-icon ${m[2]}" title="${f.text}">${m[0]}${m[1]}</span>`;
      return `<span class="ai-icon ${f.sev}">${f.text}</span>`;
    }).join('');
    const verdictLabel = ai.headline_sev
      ? `<span class="ai-verdict ${ai.headline_sev}">${ai.headline_sev}</span>` : '';
    const prose = ai.prose
      ? `<div class="ai-prose ai-prose-${ai.headline_sev}">${ai.prose}</div>` : '';
    aiHtml = `<div class="ai-icon-row">${verdictLabel}${iconRow}</div>${prose}`;
  }

  const tooltipRows = l.breakdown_tooltip
    ? l.breakdown_tooltip.split(' | ').map(r => {
        const colon = r.indexOf(':');
        return `<div class="score-tooltip-row"><span class="score-tooltip-label">${r.slice(0, colon)}</span><span class="score-tooltip-val">${r.slice(colon + 1)}</span></div>`;
      }).join('') : '';
  const tooltipHtml = tooltipRows ? `<div class="score-tooltip">${tooltipRows}</div>` : '';

  const imgHtml = l.image_url
    ? `<img src="${l.image_url}" onerror="this.parentElement.style.display='none'" loading="lazy">` : '';

  const metaParts = [l.beds_display];
  if (l.area)       metaParts.push(l.area);
  if (l.agent)      metaParts.push(l.agent);
  if (l.days_label) metaParts.push(l.days_label);

  const reasonBtns  = DISCARD_REASONS.map(r =>
    `<button onclick="confirmDiscard('${l.id}','${r}')">${r}</button>`
  ).join('');
  const discardPopup = `<div class="discard-popup" id="dp-${l.id}">${reasonBtns}</div>`;
  const trafficClass = l.traffic_road ? ' traffic-road' : '';
  const savedNote    = notesState[l.id] || '';

  return `
<div class="card${trafficClass}" id="card-${l.id}"
  data-id="${l.id}" data-score="${l.score}" data-opp="${l.opp_score || l.score}"
  data-beds="${l.beds}" data-period="${l.period}" data-quality="${l.quality}"
  data-price="${l.price_num}" data-ppsf="${l.ppsf || 0}" data-sqft="${l.sqft || 0}"
  data-area="${l.area}" data-days="${l.days_num}" data-reduced="${l.is_reduced ? '1' : '0'}"
>
  <div class="card-score score-wrap">
    <div class="score-num" style="color:${scoreCol}">${l.score}</div>
    <div class="score-label">score</div>
    ${oppHtml}
    ${tooltipHtml}
  </div>
  <div class="card-img">${imgHtml}</div>
  <div class="card-body">
    <div class="card-row1">
      <a class="card-addr" href="${l.url}" target="_blank">${l.address}</a>
      <a class="card-rm" href="${l.rm_url}" target="_blank" title="Rightmove sold prices">RM</a>
    </div>
    <div class="card-row2">
      <span class="card-price">&#163;${l.price_num.toLocaleString()}</span>
      ${reducedBadge}${staleBadge}${periodBadge}${tenureBadge}${trafficBadge}
    </div>
    <div class="card-row3">
      ${ppsfHtml}<span class="dot">·</span>
      ${metaParts.join('<span class="dot"> · </span>')}
    </div>
    ${aiHtml}
    ${streetHtml}
    <div class="card-notes">
      <textarea class="notes-input" placeholder="Viewing notes…" rows="1"
        onchange="saveNote('${l.id}', this.value)"
        oninput="this.style.height='auto';this.style.height=this.scrollHeight+'px'"
      >${savedNote}</textarea>
    </div>
  </div>
  <div class="card-actions" style="position:relative">
    ${discardPopup}
    <button class="btn-action btn-shortlist" id="sl-${l.id}" title="Shortlist" onclick="toggleShortlist('${l.id}')">&#10003;</button>
    <button class="btn-action btn-discard"   id="dc-${l.id}" title="Discard"    onclick="toggleDiscardMenu('${l.id}')">&#10005;</button>
  </div>
</div>`;
}

// ── Render ────────────────────────────────────────────────────────────────────────
let currentSort = 'score';
let currentDir  = 'desc';

function sortedData() {
  const data = [...RAW];
  data.sort((a, b) => {
    let va, vb;
    switch (currentSort) {
      case 'score': va = a.score;        vb = b.score;        break;
      case 'opp':   va = a.opp_score||0; vb = b.opp_score||0; break;
      case 'price': va = a.price_num;    vb = b.price_num;    break;
      case 'ppsf':  va = a.ppsf||9999;   vb = b.ppsf||9999;   break;
      case 'days':  va = a.days_num;     vb = b.days_num;     break;
      case 'sqft':  va = a.sqft||0;      vb = b.sqft||0;      break;
      default: return 0;
    }
    return currentDir === 'desc' ? vb - va : va - vb;
  });
  return data;
}

function renderCards() {
  const container = document.getElementById('cards-container');
  container.innerHTML = sortedData().map(buildCard).join('');
  restoreFeedbackVisuals();
  applyFilters();
}

// ── Filters ───────────────────────────────────────────────────────────────────────
function getFilters() {
  const checked = {};
  document.querySelectorAll('.filter-cb').forEach(cb => {
    const g = cb.dataset.filter;
    if (!checked[g]) checked[g] = new Set();
    if (cb.checked) checked[g].add(cb.value);
  });
  return {
    minScore:      parseInt(document.getElementById('score-min').value),
    maxDays:       parseInt(document.getElementById('days-max').value),
    area:          document.getElementById('area-filter').value,
    reducedOnly:   document.getElementById('reduced-only').checked,
    hideDiscarded: document.getElementById('hide-discarded').checked,
    checked,
  };
}

function passesFilter(el, f) {
  const d = el.dataset;
  if (parseInt(d.score) < f.minScore)                            return false;
  if (parseInt(d.days)  > f.maxDays)                             return false;
  if (f.checked.beds    && !f.checked.beds.has(d.beds))          return false;
  if (f.checked.period  && !f.checked.period.has(d.period))      return false;
  if (f.checked.quality && !f.checked.quality.has(d.quality))    return false;
  if (f.area && d.area !== f.area)                               return false;
  if (f.reducedOnly   && d.reduced !== '1')                      return false;
  if (f.hideDiscarded && el.classList.contains('discarded'))     return false;
  return true;
}

function applyFilters() {
  const f = getFilters();
  let visible = 0;
  document.querySelectorAll('.card').forEach(el => {
    const show = passesFilter(el, f);
    el.style.display = show ? '' : 'none';
    if (show) visible++;
  });
  document.getElementById('visible-count').textContent = visible;
}

document.querySelectorAll('.filter-cb').forEach(cb => cb.addEventListener('change', applyFilters));

document.querySelectorAll('#sort-btns .sort-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const key = btn.dataset.sort;
    if (currentSort === key) {
      currentDir = currentDir === 'desc' ? 'asc' : 'desc';
    } else {
      currentSort = key;
      currentDir  = key === 'days' ? 'asc' : 'desc';
    }
    document.querySelectorAll('#sort-btns .sort-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    renderCards();
  });
});

function syncRange(el, valId, suffix = '') {
  document.getElementById(valId).textContent = el.value + suffix;
}

function toggleExcl() {
  const list  = document.getElementById('excl-list');
  const arrow = document.getElementById('excl-arrow');
  list.style.display = list.style.display === 'block' ? 'none' : 'block';
  arrow.textContent  = list.style.display === 'block' ? '▼' : '▶';
}

// Map removed (not functional in file:// context)

// ── Feedback ──────────────────────────────────────────────────────────────────────
function recordFeedback(id, action, reason) {
  const listing = RAW.find(l => l.id === id);
  if (!listing) return;
  if (action.startsWith('undo_')) {
    delete feedbackState[id];
  } else {
    feedbackState[id] = {
      id, action, reason: reason || null,
      address: listing.address, score: listing.score,
      price: listing.price_num, area: listing.area,
      ts: new Date().toISOString(),
    };
  }
  _saveFeedback();
}

function toggleShortlist(id) {
  const card = document.getElementById('card-' + id);
  const btn  = document.getElementById('sl-'   + id);
  const fb   = feedbackState[id];
  if (fb && fb.action === 'shortlist') {
    recordFeedback(id, 'undo_shortlist', null);
    card.classList.remove('shortlisted');
    btn.classList.remove('active');
    showBanner('Shortlist removed');
  } else {
    recordFeedback(id, 'shortlist', null);
    card.classList.add('shortlisted');
    card.classList.remove('discarded');
    btn.classList.add('active');
    document.getElementById('dc-' + id).classList.remove('active');
    document.getElementById('dp-' + id).style.display = 'none';
    showBanner('✓ Shortlisted');
  }
}

function toggleDiscardMenu(id) {
  const popup  = document.getElementById('dp-' + id);
  const btn    = document.getElementById('dc-' + id);
  const isOpen = popup.style.display === 'block';
  document.querySelectorAll('.discard-popup').forEach(p => p.style.display = 'none');
  if (!isOpen) {
    popup.style.display = 'block';
    const rect = btn.getBoundingClientRect();
    const ph   = popup.offsetHeight;
    let top    = rect.top + rect.height / 2 - ph / 2;
    top = Math.max(8, Math.min(top, window.innerHeight - ph - 8));
    popup.style.top  = top + 'px';
    popup.style.left = (rect.left - popup.offsetWidth - 8) + 'px';
  }
}

function confirmDiscard(id, reason) {
  const card  = document.getElementById('card-' + id);
  const btn   = document.getElementById('dc-'   + id);
  const slBtn = document.getElementById('sl-'   + id);
  const popup = document.getElementById('dp-'   + id);
  if (feedbackState[id] && feedbackState[id].action === 'discard' && feedbackState[id].reason === reason) {
    recordFeedback(id, 'undo_discard', reason);
    card.classList.remove('discarded');
    btn.classList.remove('active');
    popup.style.display = 'none';
    applyFilters();
    showBanner('Discard undone');
    return;
  }
  recordFeedback(id, 'discard', reason);
  card.classList.add('discarded');
  card.classList.remove('shortlisted');
  btn.classList.add('active');
  slBtn.classList.remove('active');
  popup.style.display = 'none';
  applyFilters();
  showBanner('Discarded: ' + reason);
}

document.addEventListener('click', e => {
  if (!e.target.closest('.card-actions'))
    document.querySelectorAll('.discard-popup').forEach(p => p.style.display = 'none');
});

function restoreFeedbackVisuals() {
  Object.entries(feedbackState).forEach(([id, fb]) => {
    const card = document.getElementById('card-' + id);
    if (!card) return;
    if (fb.action === 'shortlist') {
      card.classList.add('shortlisted');
      const btn = document.getElementById('sl-' + id);
      if (btn) btn.classList.add('active');
    } else if (fb.action === 'discard') {
      card.classList.add('discarded');
      const btn = document.getElementById('dc-' + id);
      if (btn) btn.classList.add('active');
    }
  });
  Object.entries(notesState).forEach(([id, note]) => {
    const ta = document.querySelector(`#card-${id} .notes-input`);
    if (ta && note) { ta.value = note; ta.style.height = ta.scrollHeight + 'px'; }
  });
}

function showBanner(msg) {
  const b = document.getElementById('feedback-banner');
  b.innerHTML = msg;
  b.style.display = 'block';
  clearTimeout(b._t);
  b._t = setTimeout(() => b.style.display = 'none', 2200);
}

// ── Triage ────────────────────────────────────────────────────────────────────────
let triageQueue  = [];
let triageIdx    = 0;
let triageActive = false;

function startTriage() {
  const f = getFilters();
  triageQueue = sortedData().filter(l => {
    const fb = feedbackState[l.id];
    return !(fb && fb.action === 'discard') &&
      l.score    >= f.minScore &&
      l.days_num <= f.maxDays  &&
      (!f.area || l.area === f.area) &&
      (!f.reducedOnly || l.is_reduced);
  });
  if (!triageQueue.length) { showBanner('No visible listings to triage'); return; }
  triageIdx    = 0;
  triageActive = true;
  document.getElementById('triage-overlay').classList.add('active');
  renderTriageCard();
  document.addEventListener('keydown', handleTriageKey);
}

function endTriage() {
  triageActive = false;
  document.getElementById('triage-overlay').classList.remove('active');
  document.removeEventListener('keydown', handleTriageKey);
  renderCards();
}

function renderTriageCard() {
  const l = triageQueue[triageIdx];
  if (!l) { endTriage(); showBanner('Triage complete'); return; }
  document.getElementById('triage-progress').textContent = `${triageIdx + 1} / ${triageQueue.length}`;
  const fb         = feedbackState[l.id];
  const statusStr  = fb ? (fb.action === 'shortlist' ? '✓ Shortlisted' : '✕ Discarded') : '';
  const statusCol  = fb ? (fb.action === 'shortlist' ? 'var(--green)' : 'var(--red)') : '';
  const ai         = l.ai || {};
  const ppsf       = l.ppsf ? `£${l.ppsf.toLocaleString()}/sqft` : 'no sqft';
  const streetDiff = l.street_ppsf && l.ppsf
    ? (() => { const d = l.ppsf - l.street_ppsf; return ` <span style="color:${d > 50 ? '#e05252' : d < -50 ? '#4caf82' : '#8a8680'}">${d >= 0 ? '+' : ''}£${d} vs street</span>`; })()
    : '';
  const img = l.image_url
    ? `<img src="${l.image_url}" style="width:100%;height:160px;object-fit:cover;border-radius:4px;margin-bottom:12px" onerror="this.style.display='none'">` : '';

  // Score breakdown rows
  const breakdownRows = l.breakdown_tooltip
    ? l.breakdown_tooltip.split(' | ').map(r => {
        const colon = r.indexOf(':');
        return `<div style="display:flex;justify-content:space-between;font-size:10px;padding:1px 0"><span style="color:#5a5652">${r.slice(0,colon)}</span><span style="color:#8a8680;font-family:'DM Mono',monospace">${r.slice(colon+1)}</span></div>`;
      }).join('') : '';

  // AI flag row
  const aiFlags = (ai.flags || []).map(f =>
    `<span class="ai-icon ${f.sev}" style="font-size:10px">${f.text}</span>`
  ).join(' ');
  const aiBlock = ai.prose
    ? `<div style="font-size:10.5px;color:#8a8680;margin-top:8px;padding:6px 8px;background:#0e0e10;border-radius:3px;line-height:1.5;border-left:2px solid var(--border2)">${ai.prose}</div>` : '';

  // Period badge
  const periodBadge = l.period_label
    ? `<span class="badge badge-period" style="background:${l.period_colour}">${l.period_label}</span>` : '';
  const tenureBadge = l.tenure === 'freehold'
    ? '<span class="badge badge-tenure-fh">Freehold</span>' : '';
  const reducedBadge = l.is_reduced
    ? `<span class="badge badge-reduced">&#8595;${Math.abs(l.reduction_pct).toFixed(1)}%</span>` : '';
  const staleBadge = l.stale_unmotivated
    ? `<span class="badge badge-stale">${l.days_num}d no cut</span>` : '';

  document.getElementById('triage-content').innerHTML = `
    ${img}
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px">
      <span style="font-family:'DM Mono',monospace;font-size:32px;font-weight:500;color:${l.score_colour};line-height:1">${l.score}</span>
      <div>
        <a href="${l.url}" target="_blank" style="font-size:14px;font-weight:500;color:#e8e4dc;text-decoration:none;display:block">${l.address}</a>
        <div style="font-size:11px;color:#8a8680;margin-top:2px">${l.area} · ${l.agent}</div>
      </div>
    </div>
    <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-bottom:8px">
      <span style="font-family:'DM Mono',monospace;font-size:17px;font-weight:500">£${l.price_num.toLocaleString()}</span>
      ${reducedBadge}${staleBadge}${periodBadge}${tenureBadge}
    </div>
    <div style="font-size:11px;color:#8a8680;margin-bottom:6px;font-family:'DM Mono',monospace">
      ${l.beds_display} · ${ppsf}${streetDiff} · ${l.days_label}
      ${l.sqft ? ' · ' + l.sqft.toLocaleString() + ' sqft' : ''}
    </div>
    ${aiFlags ? `<div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:6px">${aiFlags}</div>` : ''}
    ${aiBlock}
    ${breakdownRows ? `<div style="margin-top:8px;background:#0e0e10;border-radius:3px;padding:6px 8px">${breakdownRows}</div>` : ''}
    ${statusStr ? `<div style="margin-top:8px;font-size:11px;font-weight:600;color:${statusCol}">${statusStr}</div>` : ''}
  `;
}

function handleTriageKey(e) {
  if (!triageActive) return;
  const l = triageQueue[triageIdx];
  if (!l) return;
  if (e.key === 'Escape') { endTriage(); return; }
  if (e.key === 's' || e.key === 'S') {
    recordFeedback(l.id, 'shortlist', null);
    showBanner('✓ Shortlisted: ' + l.address);
    triageIdx++; renderTriageCard();
  } else if (e.key === 'd' || e.key === 'D') {
    recordFeedback(l.id, 'discard', 'Other');
    showBanner('✕ Discarded');
    triageIdx++; renderTriageCard();
  } else if (e.key === 'ArrowRight') {
    triageIdx = Math.min(triageIdx + 1, triageQueue.length - 1);
    renderTriageCard();
  } else if (e.key === 'ArrowLeft') {
    triageIdx = Math.max(triageIdx - 1, 0);
    renderTriageCard();
  }
}

// ── Compare ──────────────────────────────────────────────────────────────────────
function openCompare() {
  const shortlisted = RAW.filter(l => feedbackState[l.id] && feedbackState[l.id].action === 'shortlist');
  if (!shortlisted.length) { showBanner('No shortlisted properties — use ✓ first'); return; }
  const rows = [
    ['Address',    l => `<a href="${l.url}" target="_blank" style="color:var(--gold)">${l.address}</a>`],
    ['Score',      l => `<span style="color:${l.score_colour};font-family:'DM Mono',monospace">${l.score}</span>`
                       + (l.opp_score > l.score + 2 ? ` <span style="color:#c9a84c;font-size:9px">opp ${l.opp_score}</span>` : '')],
    ['Price',      l => '£' + l.price_num.toLocaleString()],
    ['£/sqft',     l => l.ppsf ? `<span style="color:${l.ppsf_colour}">£${l.ppsf.toLocaleString()}</span>` : '—'],
    ['vs street',  l => {
      if (!l.ppsf || !l.street_ppsf) return '—';
      const d = l.ppsf - l.street_ppsf;
      return `<span style="color:${d > 50 ? '#e05252' : d < -50 ? '#4caf82' : '#8a8680'}">${d >= 0 ? '+' : ''}£${d}</span>`;
    }],
    ['Sqft',       l => l.sqft ? l.sqft.toLocaleString() : '—'],
    ['Beds',       l => l.beds_display],
    ['Period',     l => l.period_label || l.period],
    ['Tenure',     l => l.tenure],
    ['Location',   l => `${l.area} (${l.quality})`],
    ['Listed',     l => l.days_label],
    ['Traffic',    l => l.traffic_road || '—'],
    ['AI verdict', l => l.ai && l.ai.headline_sev
      ? `<span class="ai-verdict ${l.ai.headline_sev}">${l.ai.headline_sev}</span>` : '—'],
    ['Notes',      l => notesState[l.id] || ''],
    ['Agent',      l => l.agent],
  ];
  const headers   = ['<th></th>'].concat(shortlisted.map(l => `<th>${l.address.split(',')[0]}</th>`)).join('');
  const tableRows = rows.map(([label, fn]) =>
    `<tr><td>${label}</td>${shortlisted.map(l => `<td>${fn(l)}</td>`).join('')}</tr>`
  ).join('');
  document.getElementById('compare-content').innerHTML =
    `<table id="compare-table"><thead><tr>${headers}</tr></thead><tbody>${tableRows}</tbody></table>`;
  document.getElementById('compare-overlay').classList.add('active');
}

function closeCompare() {
  document.getElementById('compare-overlay').classList.remove('active');
}

// ── Copy enquiry ───────────────────────────────────────────────────────────────
function copyEnquiry() {
  const shortlisted = RAW.filter(l => feedbackState[l.id] && feedbackState[l.id].action === 'shortlist');
  if (!shortlisted.length) { showBanner('No shortlisted properties — use ✓ first'); return; }
  const byAgent = {};
  shortlisted.forEach(l => {
    const agent = l.agent || 'the agent';
    if (!byAgent[agent]) byAgent[agent] = [];
    byAgent[agent].push(l);
  });
  const agents    = Object.keys(byAgent);
  const agent     = agents[0];
  const props     = byAgent[agent];
  const propLines = props.map(l => `  - ${l.address} (${l.price})`).join('\n');
  const msg = `Dear ${agent},\n\nI would like to arrange viewings for the following `
    + `${props.length === 1 ? 'property' : 'properties'}:\n\n${propLines}`
    + `\n\nPlease let me know your available times.\n\nKind regards`;
  navigator.clipboard.writeText(msg)
    .then(() => {
      showBanner('✓ Enquiry copied — paste into Gmail compose');
      if (agents.length > 1)
        setTimeout(() => showBanner(`Note: ${agents.length - 1} more agent(s) also shortlisted`), 2500);
    })
    .catch(() => window.prompt('Copy enquiry:', msg));
}

// ── Export feedback ──────────────────────────────────────────────────────────────
function exportFeedback() {
  const entries = Object.values(feedbackState);
  if (!entries.length) { showBanner('No feedback recorded yet'); return; }
  const blob = new Blob([JSON.stringify(entries, null, 2)], { type: 'application/json' });
  const a    = document.createElement('a');
  a.href     = URL.createObjectURL(blob);
  a.download = 'feedback_' + new Date().toISOString().slice(0, 10) + '.json';
  a.click();
  showBanner('Downloaded ' + entries.length + ' entries');
}

// ── Init ───────────────────────────────────────────────────────────────────────────
renderCards();