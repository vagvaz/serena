/* ═══════════════════════════════════════════════════════════════════════════
   Serena Dashboard — Synthwave REPL Controller
   Wired to the existing Flask API with polling, tab navigation, and
   real-time log streaming.
   ═══════════════════════════════════════════════════════════════════════════ */
(function(){
'use strict';

const POLL_INTERVAL = 3000;
const LOG_POLL_INTERVAL = 2000;
const MAX_LOG_LINES = 5000;
const MAX_GAUGE_SEGMENTS = 10;

const $ = jQuery;

/* ── State ────────────────────────────────────────────────────────────── */
const state = {
  config: null,
  logMaxIdx: 0,
  allLogMessages: [],
  logAutoScroll: true,
  logFilter: { level: '', search: '' },
  darkMode: true,
  currentPage: 'overview',
};

/* ── API Helpers ──────────────────────────────────────────────────────── */
function api(method, data) {
  const opts = { method: 'GET' };
  if (data) {
    opts.method = 'POST';
    opts.contentType = 'application/json';
    opts.data = JSON.stringify(data);
  }
  return $.ajax('/' + method, opts).then(function(r) { return r; });
}

function getConfig() {
  return api('get_config_overview');
}

function getLogs() {
  return api('get_log_messages', {
    start_idx: state.logMaxIdx,
    levels: state.logFilter.level ? [state.logFilter.level] : null,
    project_name: null,
  });
}

function getToolStats() {
  return api('get_tool_stats');
}

/* ── Theme ────────────────────────────────────────────────────────────── */
function setTheme(dark) {
  state.darkMode = dark;
  document.documentElement.classList.toggle('light', !dark);
  $('#theme-btn').text(dark ? '\u{1F319}' : '\u{2600}\u{FE0F}');
  $('.theme-aware').each(function () {
    var key = dark ? 'dark' : 'light';
    this.src = $(this).data(key);
  });
}

/* ── Navigation ───────────────────────────────────────────────────────── */
function switchToPage(pageId) {
  state.currentPage = pageId;

  // Tabs
  $('.tab').removeClass('active');
  $('.tab[data-page="' + pageId + '"]').addClass('active');

  // Key hints
  $('.key-hint').removeClass('active');
  $('.key-hint[data-page="' + pageId + '"]').addClass('active');

  // Pages
  $('.page').removeClass('active');
  $('#page-' + pageId).addClass('active');

  // When switching to logs page, render all cached messages with current filter
  if (pageId === 'logs') {
    renderMainLogsFromCache();
  }
}

$(document).on('click', '.tab', function () {
  switchToPage($(this).data('page'));
});

$(document).on('click', '.key-hint', function () {
  switchToPage($(this).data('page'));
});

// Keyboard navigation F1–F6
$(document).on('keydown', function (e) {
  var pageMap = {
    F1: 'overview',
    F2: 'projects',
    F3: 'sessions',
    F4: 'logs',
    F5: 'tools',
    F6: 'config',
  };
  if (pageMap[e.key]) {
    e.preventDefault();
    switchToPage(pageMap[e.key]);
  }
});

/* ── Status Line ──────────────────────────────────────────────────────── */
function updateStatusLine(config) {
  $('#core-status').text('ONLINE');

  var projs = config.active_projects || [];
  var sesss = config.active_sessions || [];
  var mems = config.available_memories || [];

  $('#status-projects').text(projs.length);
  $('#status-sessions').text(sesss.length);
  $('#status-memories').text(mems.length > 100
    ? Math.round(mems.length / 100) + '00+'
    : mems.length || '—');

  if (config.serena_version) {
    $('#version-badge').text('v' + config.serena_version);
  }
  if (config.current_client) {
    $('#client-badge').text(esc(config.current_client));
  }
}

/* ── Gauges ──────────────────────────────────────────────────────────── */
function updateGauges(config) {
  var stats = config.tool_stats_summary || {};
  var totalCalls = 0;
  Object.keys(stats).forEach(function (k) {
    totalCalls += stats[k].num_calls || 0;
  });
  $('#gauge-tool-calls').text(totalCalls.toLocaleString());

  var sessions = config.active_sessions || [];
  $('#gauge-sessions').text(sessions.length);
  renderGaugeBar('#sessions-bar', sessions.length, MAX_GAUGE_SEGMENTS, '');

  var activeProjs = config.active_projects || [];
  var regProjs = config.registered_projects || [];
  var activeCnt = regProjs.filter(function (p) { return p.is_active; }).length;
  var idleCnt = regProjs.length - activeCnt;
  $('#gauge-projects').text(activeProjs.length);
  $('#gauge-projects-sub').text(activeCnt + ' active / ' + idleCnt + ' idle');

  var mems = config.available_memories || [];
  $('#gauge-memories').text(mems.length.toLocaleString());
  renderGaugeBar('#memories-bar', Math.min(mems.length, 50), MAX_GAUGE_SEGMENTS, 'warning');
}

function renderGaugeBar(selector, value, maxSegments, cls) {
  var filled = Math.min(value, maxSegments);
  var html = '';
  for (var i = 0; i < maxSegments; i++) {
    var classes = 'gauge-bar-segment';
    if (i < filled) classes += ' filled';
    if (cls && i < filled) classes += ' ' + cls;
    html += '<div class="' + classes + '"></div>';
  }
  $(selector).html(html);
}

/* ── Recent Sessions (Overview) ───────────────────────────────────────── */
function renderRecentSessions(sessions) {
  var $tbody = $('#recent-sessions-body');
  if (!sessions || !sessions.length) {
    $tbody.html('<tr><td colspan="5" class="cell-muted" style="text-align:center;padding:2rem;">No active sessions</td></tr>');
    return;
  }
  var html = '';
  sessions.forEach(function (s) {
    var statusClass = (s.idle_seconds || 0) > 60 ? 'amber' : 'green';
    var idleLabel = s.idle_seconds != null ? fmtDuration(s.idle_seconds) : '—';
    var client = s.client_info || '—';
    var proj = s.project_name || '—';
    html += '<tr>'
      + '<td class="cell-highlight">' + esc(s.session_id || '').substr(0, 12) + '…</td>'
      + '<td>' + esc(proj) + '</td>'
      + '<td><span class="tag ' + statusClass + '">'
      + (statusClass === 'green' ? 'Active' : 'Idle') + '</span></td>'
      + '<td class="cell-' + statusClass + '">' + idleLabel + '</td>'
      + '<td class="cell-muted">' + esc(client) + '</td>'
      + '</tr>';
  });
  $tbody.html(html);
  $('#recent-sessions-count').text(sessions.length + ' entries');
}

/* ── Active Projects (Projects page) ──────────────────────────────────── */
function renderProjects(projects) {
  var $tbody = $('#projects-body');
  if (!projects || !projects.length) {
    $tbody.html('<tr><td colspan="6" class="cell-muted" style="text-align:center;padding:2rem;">No active projects</td></tr>');
    return;
  }
  var html = '';
  projects.forEach(function (p) {
    var langs = (p.languages || []).join(', ') || '—';
    var lsp = p.lsp_running
      ? '<span class="tag green" style="padding:2px 8px;">LSP</span>'
      : '<span class="cell-muted">off</span>';
    var sessions = p.session_count != null ? p.session_count : '—';
    var idle = p.idle_seconds != null ? fmtDuration(p.idle_seconds) : '—';
    html += '<tr>'
      + '<td class="cell-highlight">' + esc(p.name) + '</td>'
      + '<td class="cell-muted" title="' + esc(p.path) + '">' + esc(p.path || '') + '</td>'
      + '<td class="cell-code">' + langs + '</td>'
      + '<td>' + lsp + '</td>'
      + '<td class="cell-code">' + sessions + '</td>'
      + '<td class="cell-muted">' + idle + '</td>'
      + '</tr>';
  });
  $tbody.html(html);
  $('#projects-count').text(projects.length + ' total');
}

/* ── Registered Projects ──────────────────────────────────────────────── */
function renderRegisteredProjects(config) {
  var reg = config.registered_projects || [];
  var $tbody = $('#registered-projects-body');
  if (!reg.length) {
    $tbody.html('<tr><td colspan="4" class="cell-muted" style="text-align:center;padding:2rem;">No registered projects</td></tr>');
    return;
  }
  var html = '';
  reg.forEach(function (p) {
    var statusClass = p.is_active ? 'green' : 'amber';
    var statusLabel = p.is_active ? 'Active' : 'Inactive';
    var sessions = p.session_count != null ? p.session_count : '—';
    html += '<tr>'
      + '<td class="cell-highlight">' + esc(p.name) + '</td>'
      + '<td class="cell-muted" title="' + esc(p.path) + '">' + esc(p.path || '') + '</td>'
      + '<td><span class="tag ' + statusClass + '">' + statusLabel + '</span></td>'
      + '<td class="cell-code">' + sessions + '</td>'
      + '</tr>';
  });
  $tbody.html(html);
  $('#registered-projects-count').text(reg.length + ' total');
}

/* ── Sessions Page ────────────────────────────────────────────────────── */
function renderSessionsPage(sessions) {
  var $tbody = $('#sessions-body');
  if (!sessions || !sessions.length) {
    $tbody.html('<tr><td colspan="4" class="cell-muted" style="text-align:center;padding:2rem;">No active sessions</td></tr>');
    return;
  }
  var html = '';
  sessions.forEach(function (s) {
    var proj = s.project_name || '—';
    var client = s.client_info || '—';
    var idle = s.idle_seconds != null ? fmtDuration(s.idle_seconds) : '—';
    var idleClass = (s.idle_seconds || 0) > 60 ? 'cell-amber' : 'cell-green';
    html += '<tr>'
      + '<td class="cell-highlight" title="' + esc(s.session_id || '') + '">' + esc(s.session_id || '').substr(0, 12) + '…</td>'
      + '<td>' + esc(proj) + '</td>'
      + '<td class="cell-muted">' + esc(client) + '</td>'
      + '<td class="' + idleClass + '">' + idle + '</td>'
      + '</tr>';
  });
  $tbody.html(html);
  $('#sessions-count').text(sessions.length + ' active');
}

/* ── Tools Page ───────────────────────────────────────────────────────── */
function renderTools(stats) {
  var $list = $('#tools-list');
  if (!stats || !Object.keys(stats).length) {
    $list.html('<div class="config-section" style="text-align:center;padding:2rem;color:var(--text-dim)">No tool usage data yet</div>');
    return;
  }
  var entries = Object.keys(stats).map(function (k) {
    return { name: k, calls: stats[k].num_calls || 0 };
  });
  entries.sort(function (a, b) { return b.calls - a.calls; });

  var maxCalls = entries.length > 0 ? entries[0].calls : 1;

  var html = '';
  entries.forEach(function (e) {
    var pct = maxCalls > 0 ? Math.round((e.calls / maxCalls) * 100) : 0;
    html += '<div class="tool-row">'
      + '<span class="tool-name">' + esc(e.name) + '</span>'
      + '<span class="tool-count">' + e.calls.toLocaleString() + '</span>'
      + '<div class="tool-bar-container"><div class="tool-bar">'
      + '<div class="tool-bar-fill" style="width: ' + pct + '%;"></div>'
      + '</div></div>'
      + '<span class="tool-percent">' + pct + '%</span>'
      + '</div>';
  });
  $list.html(html);
  $('#tools-count').text(entries.length + ' tools');

  // Animate bars
  setTimeout(function () {
    $list.find('.tool-bar-fill').each(function () {
      var w = this.style.width;
      this.style.width = '0%';
      var self = this;
      setTimeout(function () { self.style.width = w; }, 50);
    });
  }, 100);
}

/* ── Config Page ──────────────────────────────────────────────────────── */
function renderConfig(config) {
  // Server section
  $('#cfg-version').text(config.serena_version || '—');
  $('#cfg-client').text(config.current_client || '—');
  $('#cfg-context').text((config.context && config.context.name) || (config.context) || '—');
  $('#cfg-languages').text(Array.isArray(config.languages) ? config.languages.join(', ') : (config.languages || '—'));
  $('#cfg-encoding').text(config.encoding || '—');
  $('#cfg-jetbrains').text(config.jetbrains_mode ? 'enabled' : 'disabled');

  // Active tools
  var activeTools = config.active_tools || [];
  renderConfigTags('#cfg-active-tools', activeTools, true);

  // Available tools
  var availTools = config.available_tools || [];
  var toolNames = availTools.map(function (t) { return t.name || t; });
  renderConfigTags('#cfg-tools', toolNames, false);

  // Available modes
  var availModes = config.available_modes || [];
  var modeHtml = '';
  availModes.forEach(function (m) {
    var active = m.is_active ? ' active' : '';
    modeHtml += '<span class="config-tag' + active + '">' + esc(m.name || m) + '</span>';
  });
  $('#cfg-modes').html(modeHtml || '<span class="cell-muted">—</span>');

  // Available contexts
  var availCtx = config.available_contexts || [];
  var ctxHtml = '';
  availCtx.forEach(function (c) {
    var active = c.is_active ? ' active' : '';
    ctxHtml += '<span class="config-tag' + active + '">' + esc(c.name || c) + '</span>';
  });
  $('#cfg-contexts').html(ctxHtml || '<span class="cell-muted">—</span>');

  // Active modes
  var modes = config.modes || [];
  var modeNames = modes.map(function (m) { return m.name || m; });
  renderConfigTags('#cfg-active-modes', modeNames, true);
}

function renderConfigTags(selector, items, active) {
  var $el = $(selector);
  if (!items || !items.length) {
    $el.html('<span class="cell-muted">—</span>');
    return;
  }
  var html = '';
  items.forEach(function (item) {
    html += '<span class="config-tag' + (active ? ' active' : '') + '">' + esc(item) + '</span>';
  });
  $el.html(html);
}

/* ── Log Helpers ──────────────────────────────────────────────────────── */
function logLevelClass(level) {
  var l = (level || 'INFO').toLowerCase();
  if (l === 'warn' || l === 'warning') return 'warn';
  return l;
}

function matchesFilter(msg, levelFilter, searchFilter) {
  if (levelFilter) {
    var lvl = (msg.level || 'INFO').toUpperCase();
    if (lvl !== levelFilter) return false;
  }
  if (searchFilter) {
    if (!(msg.message || '').toLowerCase().includes(searchFilter.toLowerCase())) return false;
  }
  return true;
}

function buildLogHtml(msg) {
  var level = (msg.level || 'INFO').toUpperCase();
  var time = esc(msg.timestamp || '');
  var text = esc(msg.message || '');
  var lc = logLevelClass(level);
  return '<div class="log-entry">'
    + '<span class="log-time">' + time + '</span>'
    + '<span class="log-level"><span class="log-tag ' + lc + '">' + level + '</span></span>'
    + '<span class="log-text">' + text + '</span>'
    + '</div>';
}

function appendLogs(container, msgs, autoScroll) {
  if (!msgs || !msgs.length) return;
  var $c = $(container);
  var before = $c[0].scrollHeight - $c[0].scrollTop - $c[0].clientHeight;
  var shouldScroll = autoScroll && before < 40;

  var html = '';
  msgs.forEach(function (m) {
    html += buildLogHtml(m);
  });
  $c.append(html);

  // Trim to max lines
  var children = $c.children('.log-entry');
  if (children.length > MAX_LOG_LINES) {
    children.slice(0, children.length - MAX_LOG_LINES).remove();
  }

  if (shouldScroll) {
    $c.scrollTop($c[0].scrollHeight);
  }
}

function renderMainLogsFromCache() {
  var $c = $('#main-log-stream');
  $c.empty();

  var filtered = [];
  state.allLogMessages.forEach(function (m) {
    if (matchesFilter(m, state.logFilter.level, state.logFilter.search)) {
      filtered.push(m);
    }
  });
  $('#logs-count').text(filtered.length + ' entries');

  if (!filtered.length) {
    $c.html('<div class="log-placeholder">' + (state.allLogMessages.length
      ? 'No messages match current filter'
      : 'Waiting for logs…') + '</div>');
    return;
  }

  var html = '';
  filtered.forEach(function (m) {
    html += buildLogHtml(m);
  });
  $c.html(html);

  if (state.logAutoScroll) {
    $c.scrollTop($c[0].scrollHeight);
  }
}

/* ── Polling: Config ──────────────────────────────────────────────────── */
function pollConfig() {
  getConfig().then(function (cfg) {
    state.config = cfg;
    updateStatusLine(cfg);
    updateGauges(cfg);
    renderRecentSessions(cfg.active_sessions);
    renderProjects(cfg.active_projects);
    renderSessionsPage(cfg.active_sessions);
    renderRegisteredProjects(cfg);
    renderTools(cfg.tool_stats_summary);
    renderConfig(cfg);
  }).fail(function () {
    // Server not ready
  });
}

/* ── Polling: Logs ────────────────────────────────────────────────────── */
function pollLogs() {
  getLogs().then(function (r) {
    var msgs = r.messages || [];
    if (!msgs.length) return;
    state.logMaxIdx = r.max_idx;

    // Add to global cache
    state.allLogMessages = state.allLogMessages.concat(msgs);
    if (state.allLogMessages.length > MAX_LOG_LINES) {
      state.allLogMessages = state.allLogMessages.slice(-MAX_LOG_LINES);
    }

    // Always update right pane (no filter)
    appendLogs('#right-log-stream', msgs, true);

    // Update main logs page if visible
    if (state.currentPage === 'logs') {
      var filtered = msgs.filter(function (m) {
        return matchesFilter(m, state.logFilter.level, state.logFilter.search);
      });
      appendLogs('#main-log-stream', filtered, state.logAutoScroll);
      var totalFiltered = state.allLogMessages.filter(function (m) {
        return matchesFilter(m, state.logFilter.level, '');
      });
      $('#logs-count').text(totalFiltered.length + ' entries');
    }
  }).fail(function () {});
}

/* ── Event Bindings ──────────────────────────────────────────────────── */
$('#theme-btn').click(function () {
  setTheme(!state.darkMode);
});

// Log level filter
$('#log-level-filter').change(function () {
  state.logFilter.level = this.value;
  state.logMaxIdx = 0;
  state.allLogMessages = [];
  $('#main-log-stream').empty().html('<div class="log-placeholder">Filter changed — reloading…</div>');
  $('#right-log-stream').empty().html('<div class="log-placeholder">Waiting for logs…</div>');
});

// Log search (client-side filtering)
$('#log-search').on('input', function () {
  state.logFilter.search = this.value;
  if (state.currentPage === 'logs') {
    renderMainLogsFromCache();
  }
});

// Clear logs
$('#clear-logs-btn').click(function () {
  state.logMaxIdx = 0;
  state.allLogMessages = [];
  $('#main-log-stream').empty().html('<div class="log-placeholder">Logs cleared</div>');
  api('clear_logs');
});

// Right pane clear
$('#right-pane-clear').click(function () {
  $('#right-log-stream').empty().html('<div class="log-placeholder">Cleared</div>');
});

// Scroll lock toggle
$('#scroll-lock-btn').click(function () {
  state.logAutoScroll = !state.logAutoScroll;
  $(this).toggleClass('active');
  if (state.logAutoScroll && state.currentPage === 'logs') {
    var $c = $('#main-log-stream');
    $c.scrollTop($c[0].scrollHeight);
  }
});

/* ── Init ────────────────────────────────────────────────────────────── */
function init() {
  var prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  setTheme(prefersDark);

  // Initial fetch
  pollConfig();
  pollLogs();

  // Start polling
  setInterval(pollConfig, POLL_INTERVAL);
  setInterval(pollLogs, LOG_POLL_INTERVAL);
}

/* ── Utilities ───────────────────────────────────────────────────────── */
function esc(s) {
  if (s == null) return '';
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function fmtDuration(seconds) {
  if (seconds == null) return '—';
  seconds = Math.round(seconds);
  if (seconds < 60) return seconds + 's';
  if (seconds < 3600) return Math.floor(seconds / 60) + 'm ' + (seconds % 60) + 's';
  return Math.floor(seconds / 3600) + 'h ' + Math.floor((seconds % 3600) / 60) + 'm';
}

$(init);
})();
