/**
 * Compare mode for the chat page: side-by-side multi-model comparison.
 *
 * This module layers a "Compare" mode on top of the existing single chat. It
 * reuses chat.js globals rather than duplicating them:
 *   - consumeChatStream()  : the shared SSE consumer (one call per lane)
 *   - addMessage / addStreamingMessage : render into a per-lane container
 *   - AVAILABLE_MODELS / MODEL_TIERS / getModelLogo / getModelProvider
 *   - generateSessionId / setConnectionState / refreshMemory / clearMemoryCache
 *
 * Design notes:
 *   - Each lane gets its own AgentCore session id so the runtime sessions and
 *     the conversation memory threads stay isolated. Lane session ids are
 *     `${compareBaseId}-l${slot}` where compareBaseId is a 36-char UUID, giving
 *     a 39-char id that satisfies the AgentCore runtimeSessionId constraint
 *     (min length 33, charset [a-zA-Z0-9][a-zA-Z0-9-_]*).
 *   - Single mode is left completely untouched; compare lives in #compare-root
 *     and is shown/hidden by setChatMode().
 *
 * Globals consumed by chat.js / header / sidebar:
 *   window.compareMode, setChatMode(), sendMessageCompare(),
 *   startNewChatCompare(), window.getCompareMemorySessionId()
 */

// ============================================================================
// Configuration & State
// ============================================================================

const COMPARE_MODE_KEY = 'agentcore-chat-mode';
const COMPARE_MODELS_KEY = 'agentcore-compare-models';
const COMPARE_MIN_LANES = 2;
const COMPARE_MAX_LANES = 3;
const COMPARE_DEFAULT_LANES = 2; // bump to 3 to default to a three-way compare

// Module state
window.compareMode = false;
let compareInitialized = false;
let compareBaseId = null;       // 36-char UUID base for the current comparison
let compareLanes = [];          // [{ slot, modelId, sessionId }]
let activeMemoryLane = 0;       // index into compareLanes shown in the sidebar
let laneSlotSeq = 0;            // monotonic, never reused within a comparison
let compareStreaming = false;   // guard against concurrent fan-outs

// ============================================================================
// Model helpers (built on chat.js globals)
// ============================================================================

/**
 * The selectable model catalog, defensively resolved from chat.js. Falls back
 * to an empty array so compare.js never throws if loaded out of order.
 *
 * @returns {Array<Object>} Array of {id, name, tier, provider, logo}
 */
function compareModels() {
    return (typeof AVAILABLE_MODELS !== 'undefined' && AVAILABLE_MODELS) ? AVAILABLE_MODELS : [];
}

/**
 * Resolve a model object by id, or null.
 *
 * @param {string} id - Model identifier
 * @returns {Object|null}
 */
function compareModelById(id) {
    return compareModels().find(function (m) { return m.id === id; }) || null;
}

/**
 * Cryptographically-secure RFC4122 v4 UUID. Used as the per-lane AgentCore
 * runtimeSessionId base, which is a security-sensitive identifier, so it must
 * come from a secure RNG (never Math.random). The hex+hyphen format also
 * satisfies the runtimeSessionId charset and length once the "-lN" suffix is
 * appended (36 + 3 = 39 chars, >= the 33-char minimum).
 */
function secureUuid() {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
        return crypto.randomUUID();
    }
    // Fallback for older browsers: still a CSPRNG via crypto.getRandomValues.
    const bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    bytes[6] = (bytes[6] & 0x0f) | 0x40; // version 4
    bytes[8] = (bytes[8] & 0x3f) | 0x80; // variant 10
    const hex = [];
    for (let i = 0; i < 16; i++) hex.push((bytes[i] + 0x100).toString(16).slice(1));
    return hex.slice(0, 4).join('') + '-' + hex.slice(4, 6).join('') + '-' +
           hex.slice(6, 8).join('') + '-' + hex.slice(8, 10).join('') + '-' +
           hex.slice(10, 16).join('');
}

// Monotonic counter for unique per-lane message element ids (no randomness).
let laneMsgSeq = 0;

/**
 * Choose N distinct default model ids for the initial lanes. Prefers the
 * single-mode selected model first, then fills with other distinct models.
 *
 * @param {number} n - Number of model ids to pick
 * @returns {Array<string>}
 */
function defaultLaneModelIds(n) {
    const chosen = [];
    const selected = (typeof getSelectedModel === 'function') ? getSelectedModel() : null;
    if (selected && selected.id) chosen.push(selected.id);
    const all = compareModels();
    for (let i = 0; i < all.length && chosen.length < n; i++) {
        if (chosen.indexOf(all[i].id) === -1) chosen.push(all[i].id);
    }
    return chosen.slice(0, n);
}

/**
 * Pick a model id for a newly added lane: the first catalog model not already
 * in use, falling back to the first model.
 *
 * @returns {string}
 */
function pickAdditionalModelId() {
    const used = compareLanes.map(function (l) { return l.modelId; });
    const all = compareModels();
    const unused = all.find(function (m) { return used.indexOf(m.id) === -1; });
    return unused ? unused.id : (all[0] ? all[0].id : '');
}

// ============================================================================
// Persistence (lane model selection only — never the chosen prompt/content)
// ============================================================================

function saveCompareModels() {
    try {
        localStorage.setItem(COMPARE_MODELS_KEY, JSON.stringify(compareLanes.map(function (l) { return l.modelId; })));
    } catch (e) {
        console.warn('Failed to persist compare models:', e);
    }
}

/**
 * Load persisted lane model ids, validated against the current catalog and
 * clamped to [MIN, MAX]. Returns null when nothing valid is stored.
 *
 * @returns {Array<string>|null}
 */
function loadCompareModels() {
    try {
        const raw = localStorage.getItem(COMPARE_MODELS_KEY);
        if (!raw) return null;
        const parsed = JSON.parse(raw);
        if (!Array.isArray(parsed)) return null;
        const valid = parsed.filter(function (id) { return !!compareModelById(id); });
        if (valid.length < COMPARE_MIN_LANES) return null;
        return valid.slice(0, COMPARE_MAX_LANES);
    } catch (e) {
        return null;
    }
}

// ============================================================================
// Lane factory
// ============================================================================

/**
 * Build a lane descriptor with an isolated, constraint-valid session id.
 *
 * @param {string} modelId - Model identifier for the lane
 * @returns {{slot:number, modelId:string, sessionId:string}}
 */
function makeLane(modelId) {
    laneSlotSeq += 1;
    return {
        slot: laneSlotSeq,
        modelId: modelId,
        sessionId: compareBaseId + '-l' + laneSlotSeq,
    };
}

function laneBySlot(slot) {
    return compareLanes.find(function (l) { return l.slot === slot; }) || null;
}

// ============================================================================
// Initialization
// ============================================================================

/**
 * Lazily initialize compare state and DOM on first entry into compare mode.
 * Does not invoke any model — only renders lanes and loads the active lane's
 * (cheap) memory.
 */
function initCompare() {
    if (compareInitialized) return;
    compareInitialized = true;

    compareBaseId = secureUuid();

    const saved = loadCompareModels();
    const modelIds = (saved && saved.length)
        ? saved
        : defaultLaneModelIds(COMPARE_DEFAULT_LANES);

    compareLanes = modelIds.map(function (id) { return makeLane(id); });
    activeMemoryLane = 0;

    renderCompareLanes();
    renderCompareLaneSwitcher();
}

// ============================================================================
// Mode toggle
// ============================================================================

/**
 * Switch between 'single' and 'compare' modes. Toggles the relevant containers
 * and the composer's single model selector (compare uses per-lane pickers).
 *
 * @param {string} mode - 'single' | 'compare'
 */
function setChatMode(mode) {
    const compare = (mode === 'compare');
    window.compareMode = compare;
    try { localStorage.setItem(COMPARE_MODE_KEY, compare ? 'compare' : 'single'); } catch (e) {}

    // Keep the <html> flag in sync with the active mode. The no-flash CSS in
    // chat.html keys off this class (with !important) to pre-hide the single
    // view on load; without keeping it current, switching back to single at
    // runtime would leave #message-list forced hidden.
    document.documentElement.classList.toggle('chat-mode-compare', compare);

    // Reflect state on the segmented toggle (CSS keys off aria-selected)
    const singleBtn = document.getElementById('mode-single-btn');
    const compareBtn = document.getElementById('mode-compare-btn');
    if (singleBtn) singleBtn.setAttribute('aria-selected', String(!compare));
    if (compareBtn) compareBtn.setAttribute('aria-selected', String(compare));

    const messageList = document.getElementById('message-list');
    const compareRoot = document.getElementById('compare-root');
    const modelWrap = document.getElementById('model-selector-wrap');
    const scrollBtn = document.getElementById('scroll-to-bottom-btn');

    if (compare) {
        if (!compareInitialized) initCompare();
        if (messageList) messageList.classList.add('hidden');
        if (compareRoot) compareRoot.classList.remove('hidden');
        if (modelWrap) modelWrap.classList.add('hidden');
        if (scrollBtn) scrollBtn.classList.add('hidden');
        showCompareLaneSwitcher(true);
        refreshActiveLaneMemory();
    } else {
        if (compareRoot) compareRoot.classList.add('hidden');
        if (messageList) messageList.classList.remove('hidden');
        if (modelWrap) modelWrap.classList.remove('hidden');
        showCompareLaneSwitcher(false);
        // Back to the single chat session's memory
        if (typeof clearMemoryCache === 'function') clearMemoryCache();
        if (typeof refreshMemory === 'function') refreshMemory(true);
    }
}

// ============================================================================
// Layout rendering
// ============================================================================

/**
 * Full (re)build of the compare layout inside #compare-root. Used on init and
 * on new-chat reset (both start with empty transcripts). Add/remove/model-change
 * are surgical so they never wipe in-progress transcripts.
 */
function renderCompareLanes() {
    const root = document.getElementById('compare-root');
    if (!root) return;

    root.textContent = '';

    const wrap = document.createElement('div');
    wrap.className = 'flex flex-col h-full';

    // Toolbar
    const toolbar = document.createElement('div');
    toolbar.id = 'compare-toolbar';
    toolbar.className = 'shrink-0 flex items-center justify-between gap-3 px-3 sm:px-4 md:px-6 py-2';
    toolbar.style.borderBottom = '1px solid var(--border)';
    toolbar.innerHTML =
        '<div class="text-xs min-w-0 truncate" style="color: var(--text-muted);">' +
            '<span id="compare-count" class="font-mono" style="color: var(--text);"></span> of ' + COMPARE_MAX_LANES + ' models' +
        '</div>' +
        '<button id="compare-add-btn" type="button" onclick="addLane()" ' +
            'class="shrink-0 px-2.5 py-1.5 text-xs font-medium rounded-lg flex items-center gap-1 transition-all active:scale-95" ' +
            'style="background: var(--surface-2); border: 1px solid var(--border); color: var(--text-muted);" ' +
            'title="Add a model lane">' +
            '<svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" /></svg>' +
            '<span>Add model</span>' +
        '</button>';
    wrap.appendChild(toolbar);

    // Grid (horizontal scroll on narrow screens)
    const grid = document.createElement('div');
    grid.className = 'flex-1 overflow-x-auto overflow-y-hidden px-3 sm:px-4 md:px-6 py-3';
    const columns = document.createElement('div');
    columns.id = 'compare-columns';
    columns.className = 'flex gap-3 h-full';
    compareLanes.forEach(function (lane) { columns.appendChild(buildLaneColumn(lane)); });
    grid.appendChild(columns);
    wrap.appendChild(grid);

    root.appendChild(wrap);

    updateCompareToolbar();
    updateLaneRemoveButtons();
}

/**
 * Build a single lane column element (header + empty transcript).
 *
 * @param {{slot:number, modelId:string}} lane
 * @returns {HTMLElement}
 */
function buildLaneColumn(lane) {
    const model = compareModelById(lane.modelId);
    const name = model ? model.name : lane.modelId;
    const logo = (typeof getModelLogo === 'function') ? getModelLogo(lane.modelId) : '';

    const col = document.createElement('div');
    col.className = 'compare-lane flex flex-col rounded-xl overflow-hidden flex-1 min-w-[280px]';
    col.dataset.slot = String(lane.slot);
    col.style.background = 'var(--surface)';
    col.style.border = '1px solid var(--border)';

    col.innerHTML =
        '<div class="lane-header shrink-0 flex items-center gap-2 px-3 py-2" style="border-bottom: 1px solid var(--border); background: var(--surface-2);">' +
            '<img class="lane-logo w-5 h-5 rounded object-contain ' + (logo ? '' : 'hidden') + '" src="' + escapeHtml(logo) + '" alt="">' +
            '<span class="lane-model-name text-sm font-medium truncate" style="color: var(--text);">' + escapeHtml(name) + '</span>' +
            '<button type="button" class="lane-change-btn ml-auto p-1.5 rounded-lg transition-colors hover:opacity-80" ' +
                'style="color: var(--text-muted);" onclick="openLaneModelMenu(event, ' + lane.slot + ')" title="Change model" aria-label="Change model">' +
                '<svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7" /></svg>' +
            '</button>' +
            '<button type="button" class="lane-remove-btn p-1.5 rounded-lg transition-colors hover:text-red-500" ' +
                'style="color: var(--text-subtle);" onclick="removeLane(' + lane.slot + ')" title="Remove model" aria-label="Remove model">' +
                '<svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" /></svg>' +
            '</button>' +
        '</div>' +
        '<div id="lane-transcript-' + lane.slot + '" class="lane-transcript flex-1 overflow-y-auto p-3 flex flex-col gap-1 scroll-smooth">' +
            laneEmptyStateHtml(lane) +
        '</div>';

    return col;
}

/**
 * Empty-state markup shown in a lane before its first prompt.
 *
 * @param {{modelId:string}} lane
 * @returns {string}
 */
function laneEmptyStateHtml(lane) {
    const model = compareModelById(lane.modelId);
    const name = model ? model.name : lane.modelId;
    return '<div class="lane-empty flex-1 flex items-center justify-center text-center px-4">' +
        '<div>' +
            '<p class="text-sm font-medium" style="color: var(--text-muted);">' + escapeHtml(name) + '</p>' +
            '<p class="text-xs mt-1" style="color: var(--text-subtle);">Awaiting your first prompt</p>' +
        '</div>' +
    '</div>';
}

/**
 * Render the lane empty-state into a container using DOM APIs (textContent),
 * so the model name/id is never reinterpreted as HTML. Used when re-labelling
 * an unused lane after a model change, where the id originates from a DOM
 * attribute read.
 *
 * @param {HTMLElement} container
 * @param {{modelId:string}} lane
 */
function renderLaneEmptyState(container, lane) {
    const model = compareModelById(lane.modelId);
    const name = model ? model.name : lane.modelId;

    const outer = document.createElement('div');
    outer.className = 'lane-empty flex-1 flex items-center justify-center text-center px-4';
    const inner = document.createElement('div');

    const title = document.createElement('p');
    title.className = 'text-sm font-medium';
    title.style.color = 'var(--text-muted)';
    title.textContent = name;

    const sub = document.createElement('p');
    sub.className = 'text-xs mt-1';
    sub.style.color = 'var(--text-subtle)';
    sub.textContent = 'Awaiting your first prompt';

    inner.appendChild(title);
    inner.appendChild(sub);
    outer.appendChild(inner);
    container.replaceChildren(outer);
}

/** Update the toolbar count + Add-button enabled/visibility. */
function updateCompareToolbar() {
    const count = document.getElementById('compare-count');
    if (count) count.textContent = String(compareLanes.length);
    const addBtn = document.getElementById('compare-add-btn');
    if (addBtn) {
        const atMax = compareLanes.length >= COMPARE_MAX_LANES;
        addBtn.classList.toggle('hidden', atMax);
    }
}

/** Enable/disable the per-lane remove buttons honoring the minimum lane count. */
function updateLaneRemoveButtons() {
    const canRemove = compareLanes.length > COMPARE_MIN_LANES;
    document.querySelectorAll('.compare-lane .lane-remove-btn').forEach(function (btn) {
        btn.disabled = !canRemove;
        btn.style.opacity = canRemove ? '' : '0.3';
        btn.style.cursor = canRemove ? '' : 'not-allowed';
    });
}

// ============================================================================
// Add / remove / change-model
// ============================================================================

/** Add a new lane (up to the max) without disturbing existing transcripts. */
function addLane() {
    if (compareLanes.length >= COMPARE_MAX_LANES) return;
    const lane = makeLane(pickAdditionalModelId());
    compareLanes.push(lane);

    const columns = document.getElementById('compare-columns');
    if (columns) columns.appendChild(buildLaneColumn(lane));

    saveCompareModels();
    updateCompareToolbar();
    updateLaneRemoveButtons();
    renderCompareLaneSwitcher();
}

/**
 * Remove a lane by slot (honoring the minimum), preserving other transcripts.
 *
 * @param {number} slot
 */
function removeLane(slot) {
    if (compareLanes.length <= COMPARE_MIN_LANES) return;
    const idx = compareLanes.findIndex(function (l) { return l.slot === slot; });
    if (idx === -1) return;

    compareLanes.splice(idx, 1);
    const col = document.querySelector('.compare-lane[data-slot="' + slot + '"]');
    if (col) col.remove();

    if (activeMemoryLane >= compareLanes.length) activeMemoryLane = compareLanes.length - 1;

    saveCompareModels();
    updateCompareToolbar();
    updateLaneRemoveButtons();
    renderCompareLaneSwitcher();
    refreshActiveLaneMemory();
}

/**
 * Apply a model change to a lane: update state + header only (keep transcript).
 *
 * @param {number} slot
 * @param {string} modelId
 */
function pickLaneModel(slot, modelId) {
    const lane = laneBySlot(slot);
    if (!lane) return;
    lane.modelId = modelId;

    const model = compareModelById(modelId);
    const name = model ? model.name : modelId;
    const logo = (typeof getModelLogo === 'function') ? getModelLogo(modelId) : '';

    const col = document.querySelector('.compare-lane[data-slot="' + slot + '"]');
    if (col) {
        const nameEl = col.querySelector('.lane-model-name');
        if (nameEl) nameEl.textContent = name;
        const logoEl = col.querySelector('.lane-logo');
        if (logoEl) {
            if (logo) { logoEl.src = logo; logoEl.classList.remove('hidden'); }
            else { logoEl.classList.add('hidden'); }
        }
        // Refresh the empty-state label if the lane hasn't been used yet
        const empty = col.querySelector('.lane-empty');
        if (empty) {
            const transcript = document.getElementById('lane-transcript-' + slot);
            if (transcript) renderLaneEmptyState(transcript, lane);
        }
    }

    saveCompareModels();
    renderCompareLaneSwitcher();
    closeLaneModelMenu();
}

// ============================================================================
// Per-lane model picker menu (single shared floating panel)
// ============================================================================

let laneMenuTargetSlot = null;

/**
 * Open the shared model menu anchored to a lane's change button.
 *
 * @param {Event} event
 * @param {number} slot
 */
function openLaneModelMenu(event, slot) {
    event.stopPropagation();
    laneMenuTargetSlot = slot;
    const menu = ensureLaneModelMenu();
    const lane = laneBySlot(slot);
    renderLaneModelMenuItems(menu, lane ? lane.modelId : null);

    // Position under the clicked button (fixed), kept within the viewport
    const rect = event.currentTarget.getBoundingClientRect();
    const menuWidth = 300;
    let left = rect.right - menuWidth;
    if (left < 8) left = 8;
    if (left + menuWidth > window.innerWidth - 8) left = window.innerWidth - menuWidth - 8;
    menu.style.left = left + 'px';
    menu.style.top = (rect.bottom + 6) + 'px';
    menu.classList.remove('hidden');
}

function closeLaneModelMenu() {
    const menu = document.getElementById('compare-model-menu');
    if (menu) menu.classList.add('hidden');
    laneMenuTargetSlot = null;
}

/** Create (once) the shared floating menu element appended to <body>. */
function ensureLaneModelMenu() {
    let menu = document.getElementById('compare-model-menu');
    if (menu) return menu;

    menu = document.createElement('div');
    menu.id = 'compare-model-menu';
    menu.className = 'hidden fixed z-[60] w-[300px] rounded-xl shadow-2xl max-h-[60vh] overflow-y-auto';
    menu.style.background = 'var(--surface)';
    menu.style.border = '1px solid var(--border)';

    // Event delegation: a click on a model row applies it to the target lane.
    // Resolve the raw data-model-id against the known catalog and forward only
    // the canonical id, keeping untrusted DOM attribute text out of the
    // downstream render path (and rejecting unknown ids).
    menu.addEventListener('click', function (e) {
        const row = e.target.closest ? e.target.closest('[data-model-id]') : null;
        if (!row) return;
        const known = compareModelById(row.getAttribute('data-model-id'));
        if (laneMenuTargetSlot != null && known) {
            pickLaneModel(laneMenuTargetSlot, known.id);
        }
    });

    document.body.appendChild(menu);
    return menu;
}

/**
 * Render the grouped model list into the menu, marking the lane's current model.
 *
 * @param {HTMLElement} menu
 * @param {string|null} currentModelId
 */
function renderLaneModelMenuItems(menu, currentModelId) {
    const tiers = (typeof MODEL_TIERS !== 'undefined' && MODEL_TIERS) ? MODEL_TIERS : [];
    const models = compareModels();

    let html = '<div class="px-3 py-2 sticky top-0" style="background: var(--surface); border-bottom: 1px solid var(--border);">' +
        '<p class="text-xs font-semibold uppercase tracking-wide" style="color: var(--text-subtle);">Select model for this lane</p></div>';

    const grouped = {};
    models.forEach(function (m) {
        const t = m.tier || 'other';
        (grouped[t] = grouped[t] || []).push(m);
    });

    const order = tiers.length ? tiers.map(function (t) { return t.id; }) : Object.keys(grouped);
    order.forEach(function (tierId) {
        const list = grouped[tierId];
        if (!list || !list.length) return;
        const tierMeta = tiers.find(function (t) { return t.id === tierId; });
        const label = tierMeta ? tierMeta.label : tierId;
        html += '<div class="px-3 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-wider" style="color: var(--text-subtle);">' + escapeHtml(label) + '</div>';
        list.forEach(function (m) {
            const selected = (m.id === currentModelId);
            const logo = (typeof getModelLogo === 'function') ? getModelLogo(m.id) : '';
            html += '<button type="button" data-model-id="' + escapeHtml(m.id) + '" ' +
                'class="w-full text-left px-3 py-2 flex items-center gap-2 transition-colors hover:bg-[color:var(--surface-2)]" ' +
                'style="' + (selected ? 'background: var(--surface-2);' : '') + '">' +
                (logo ? '<img src="' + escapeHtml(logo) + '" alt="" class="w-4 h-4 rounded object-contain shrink-0">' : '<span class="w-4 h-4 shrink-0"></span>') +
                '<span class="flex-1 min-w-0"><span class="block text-sm truncate" style="color: var(--text);">' + escapeHtml(m.name) + '</span>' +
                '<span class="block text-[11px] font-mono truncate" style="color: var(--text-subtle);">' + escapeHtml(m.description || '') + '</span></span>' +
                (selected ? '<svg class="w-4 h-4 shrink-0" style="color: var(--primary);" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" /></svg>' : '') +
                '</button>';
        });
    });

    menu.innerHTML = html;
}

// Close the menu on outside click or Escape
document.addEventListener('click', function (e) {
    const menu = document.getElementById('compare-model-menu');
    if (!menu || menu.classList.contains('hidden')) return;
    if (menu.contains(e.target)) return;
    if (e.target.closest && e.target.closest('.lane-change-btn')) return; // toggle handled by opener
    closeLaneModelMenu();
});
document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') closeLaneModelMenu();
});

// ============================================================================
// Fan-out streaming
// ============================================================================

/**
 * Send the composer prompt to every lane concurrently. Each lane streams into
 * its own transcript with its own session id + model via consumeChatStream.
 */
async function sendMessageCompare() {
    const input = document.getElementById('message-input');
    if (!input) return;
    const message = input.value.trim();
    if (!message || compareStreaming || compareLanes.length === 0) return;

    if (typeof hideError === 'function') hideError();

    compareStreaming = true;
    if (typeof setConnectionState === 'function') setConnectionState('connecting');

    // Snapshot lanes so add/remove mid-stream can't corrupt the fan-out
    const lanes = compareLanes.slice();
    const tasks = lanes.map(function (lane) { return streamLane(lane, message); });

    // Clear the composer once dispatched
    input.value = '';
    input.style.height = 'auto';

    await Promise.allSettled(tasks);

    compareStreaming = false;
    if (typeof setConnectionState === 'function') setConnectionState('ready');

    // Reflect the new turn in the sidebar for the active lane
    refreshActiveLaneMemory();
}

/**
 * Stream a single lane: append the shared user prompt, a streaming assistant
 * placeholder, then consume the SSE stream into this lane's transcript.
 *
 * @param {{slot:number, modelId:string, sessionId:string}} lane
 * @param {string} message
 */
async function streamLane(lane, message) {
    const transcript = document.getElementById('lane-transcript-' + lane.slot);
    if (!transcript) return;

    // Drop the lane empty-state on first use
    const empty = transcript.querySelector('.lane-empty');
    if (empty) empty.remove();

    addMessage('user', message, transcript);

    const assistantMsgId = 'msg-assistant-l' + lane.slot + '-' + Date.now() + '-' + (++laneMsgSeq);
    addStreamingMessage(assistantMsgId, transcript);

    const model = compareModelById(lane.modelId);
    const assistantEl = document.getElementById(assistantMsgId);
    if (assistantEl && model) assistantEl.dataset.modelName = model.name;

    try {
        const result = await consumeChatStream({
            prompt: message,
            sessionId: lane.sessionId,
            modelId: lane.modelId,
            assistantMsgId: assistantMsgId,
            onFirstEvent: function () {
                // Idempotent: the first lane to produce a token flips the shared
                // composer pill from 'connecting' to 'streaming'.
                if (typeof setConnectionState === 'function') setConnectionState('streaming');
            },
        });
        if (result.aborted) return;
        if (!result.hasReceivedContent) {
            markLaneMessageEmpty(assistantMsgId);
        }
    } catch (err) {
        console.error('Compare lane error [' + lane.modelId + ']:', err);
        markLaneMessageError(assistantMsgId, (err && err.message) ? err.message : 'Request failed');
    }
}

/**
 * Render a "no response" state inside a lane's streaming message.
 *
 * @param {string} assistantMsgId
 */
function markLaneMessageEmpty(assistantMsgId) {
    const msgEl = document.getElementById(assistantMsgId);
    if (!msgEl) return;
    const contentDiv = msgEl.querySelector('.message-content');
    const hasRendered = (contentDiv && contentDiv.textContent.trim().length > 0) || !!msgEl.querySelector('.reasoning-block');
    if (!hasRendered && contentDiv) {
        contentDiv.innerHTML = '<span class="text-red-500 text-sm">No response from this model.</span>';
    }
    stripStreamingAffordances(msgEl);
}

/**
 * Render an error state inside a lane's streaming message (keeps the comparison
 * usable even if one lane fails).
 *
 * @param {string} assistantMsgId
 * @param {string} message
 */
function markLaneMessageError(assistantMsgId, message) {
    const msgEl = document.getElementById(assistantMsgId);
    if (!msgEl) return;
    const contentDiv = msgEl.querySelector('.message-content');
    if (contentDiv) {
        contentDiv.innerHTML = '<span class="text-red-500 text-sm">' + escapeHtml(message) + '</span>';
    }
    stripStreamingAffordances(msgEl);
}

/** Remove the streaming pulse/progress/cursor from a message element. */
function stripStreamingAffordances(msgEl) {
    const bubble = msgEl.querySelector('.message-assistant');
    if (bubble) bubble.classList.remove('streaming-pulse');
    const progressBar = msgEl.querySelector('.streaming-progress-bar');
    if (progressBar) progressBar.remove();
    const cursor = msgEl.querySelector('.streaming-cursor');
    if (cursor) cursor.remove();
}

// ============================================================================
// New chat (compare)
// ============================================================================

/**
 * Reset the comparison: fresh base id + fresh per-lane sessions, same models,
 * cleared transcripts.
 */
function startNewChatCompare() {
    compareBaseId = secureUuid();

    // Keep the same models and slots, just hand each lane a fresh session id
    compareLanes = compareLanes.map(function (lane) {
        return { slot: lane.slot, modelId: lane.modelId, sessionId: compareBaseId + '-l' + lane.slot };
    });
    activeMemoryLane = 0;

    renderCompareLanes();
    renderCompareLaneSwitcher();
    if (typeof hideError === 'function') hideError();
    refreshActiveLaneMemory();
}

// ============================================================================
// Sidebar lane switcher + per-lane memory
// ============================================================================

/**
 * Active-lane session id for the memory sidebar. chat.js's
 * getActiveMemorySessionId() calls this when in compare mode.
 *
 * @returns {string|null}
 */
function getCompareMemorySessionId() {
    const lane = compareLanes[activeMemoryLane];
    return lane ? lane.sessionId : null;
}
window.getCompareMemorySessionId = getCompareMemorySessionId;

/** Clear the memory cache and reload memory for the active lane's session. */
function refreshActiveLaneMemory() {
    if (typeof clearMemoryCache === 'function') clearMemoryCache();
    if (typeof refreshMemory === 'function') refreshMemory(true);
}

/**
 * Switch which lane's memory the sidebar shows.
 *
 * @param {number} idx - Index into compareLanes
 */
function setActiveMemoryLane(idx) {
    if (idx < 0 || idx >= compareLanes.length) return;
    activeMemoryLane = idx;
    renderCompareLaneSwitcher();
    refreshActiveLaneMemory();
}

/** Show/hide the sidebar lane switcher block. */
function showCompareLaneSwitcher(show) {
    const el = document.getElementById('compare-lane-switcher');
    if (el) el.classList.toggle('hidden', !show);
}

/**
 * Build/update the lane switcher injected at the top of the memory sidebar.
 * Segmented control (one button per lane) + a session-id chip + a caption
 * clarifying which memory types isolate per lane.
 */
function renderCompareLaneSwitcher() {
    const tabs = document.getElementById('tab-events');
    if (!tabs || !tabs.parentNode) return;
    const tabsRow = tabs.parentNode;

    let switcher = document.getElementById('compare-lane-switcher');
    if (!switcher) {
        switcher = document.createElement('div');
        switcher.id = 'compare-lane-switcher';
        switcher.className = 'px-4 py-3 hidden';
        switcher.style.borderBottom = '1px solid var(--sidebar-border)';
        tabsRow.parentNode.insertBefore(switcher, tabsRow);
    }

    const activeLane = compareLanes[activeMemoryLane] || null;
    const shortSid = activeLane ? '…' + activeLane.sessionId.slice(-7) : '';

    let buttons = '';
    compareLanes.forEach(function (lane, idx) {
        const model = compareModelById(lane.modelId);
        const name = model ? model.name : lane.modelId;
        const isActive = (idx === activeMemoryLane);
        buttons += '<button type="button" onclick="setActiveMemoryLane(' + idx + ')" ' +
            'class="flex-1 min-w-0 px-2 py-1.5 text-xs font-medium rounded-md transition-colors truncate" ' +
            'style="' + (isActive
                ? 'background: var(--sidebar-tab-active-bg); color: var(--sidebar-tab-active-text);'
                : 'color: var(--sidebar-text-muted);') + '" ' +
            'title="' + escapeHtml(name) + '">' + escapeHtml(name) + '</button>';
    });

    switcher.innerHTML =
        // '<div class="flex items-center justify-between mb-2">' +
        //     '<span class="text-xs font-semibold uppercase tracking-wide" style="color: var(--sidebar-text-muted);">Lane memory</span>' +
        //     '<span class="text-[10px] font-mono px-1.5 py-0.5 rounded" style="background: var(--sidebar-badge-bg); color: var(--sidebar-badge-text);" title="' + escapeHtml(activeLane ? activeLane.sessionId : '') + '">' + escapeHtml(shortSid) + '</span>' +
        // '</div>' +
        '<div class="flex gap-1 p-0.5 rounded-lg" style="background: var(--sidebar-card-bg); border: 1px solid var(--sidebar-card-border);">' + buttons + '</div>' +
        '<p class="text-[11px] mt-2 leading-snug" style="color: var(--sidebar-text-muted);">Events &amp; summaries are isolated per lane. Facts &amp; preferences are user-level, so they read the same across lanes.</p>';
}

// ============================================================================
// Boot
// ============================================================================

/**
 * Restore the saved mode on load. Entering compare only renders lanes and
 * loads memory (no model is invoked until the user sends).
 */
function initCompareMode() {
    let saved = 'single';
    try { saved = localStorage.getItem(COMPARE_MODE_KEY) || 'single'; } catch (e) {}
    if (saved === 'compare') {
        setChatMode('compare');
    } else {
        // Ensure toggle reflects single without triggering a memory reload
        const singleBtn = document.getElementById('mode-single-btn');
        const compareBtn = document.getElementById('mode-compare-btn');
        if (singleBtn) singleBtn.setAttribute('aria-selected', 'true');
        if (compareBtn) compareBtn.setAttribute('aria-selected', 'false');
    }
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initCompareMode);
} else {
    initCompareMode();
}
