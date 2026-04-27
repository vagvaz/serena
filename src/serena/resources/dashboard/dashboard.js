/* ═══════════════════════════════════════════════════════════════════════════
   Serena Dashboard — Compact Dashboard Controller
   ═══════════════════════════════════════════════════════════════════════════ */
(function(){
'use strict';

const POLL_INTERVAL = 3000;
const LOG_POLL_INTERVAL = 2000;
const MAX_LOG_LINES = 5000;

const $ = jQuery;
let state = {
  config: null,
  logMaxIdx: 0,
  logAutoScroll: true,
  logFilter: { level: '', search: '' },
  darkMode: true,
  currentPage: 'overview',
};

/* ── API helpers ──────────────────────────────────────────────────────── */
function api(method, data) {
  const opts = { method: 'GET' };
  if (data) {
    opts.method = 'POST';
    opts.contentType = 'application/json';
    opts.data = JSON.stringify(data);
  }
  return $.ajax('/' + method, opts).then(r => r);
}
function getConfig() { return api('get_config_overview'); }
function getLogs() {
  return api('get_log_messages', {
    start_idx: state.logMaxIdx,
    levels: state.logFilter.level ? [state.logFilter.level] : null,
    project_name: state.logFilter.project || null,
  });
}
function getToolStats() { return api('get_tool_stats'); }
function getSessions() { return api('get_config_overview').then(r => r.active_sessions); }

/* ── Theme ────────────────────────────────────────────────────────────── */
function setTheme(dark) {
  state.darkMode = dark;
  document.documentElement.classList.toggle('light', !dark);
  $('#theme-btn').text(dark ? '🌙' : '☀️');
  $('.theme-aware').each(function(){
    const key = dark ? 'dark' : 'light';
    this.src = $(this).data(key);
  });
}

/* ── Navigation ───────────────────────────────────────────────────────── */
$(document).on('click', '.tab', function(){
  const page = $(this).data('page');
  $('.tab').removeClass('active');
  $(this).addClass('active');
  $('.page').removeClass('active');
  $('#page-' + page).addClass('active');
  state.currentPage = page;
});

/* ── Stat Display ─────────────────────────────────────────────────────── */
function updateStats(config) {
  const proj = config.active_projects || [];
  const sessions = config.active_sessions || [];
  const tools = config.active_tools || [];
  const stats = config.tool_stats_summary || {};
  const calls = Object.values(stats).reduce((s, t) => s + (t.num_calls || 0), 0);
  $('#stat-projects .stat-val').text(proj.length);
  $('#stat-sessions .stat-val').text(sessions.length);
  $('#stat-tools-active .stat-val').text(tools.length);
  $('#stat-tool-calls .stat-val').text(calls);
  const mems = config.available_memories;
  $('#stat-memories .stat-val').text(mems ? mems.length : '—');
}

/* ── Project Cards ────────────────────────────────────────────────────── */
function renderProjectCards(projects, container) {
  if (!projects.length) { $(container).html('<div class="config-section" style="color:var(--text-muted);padding:2rem;text-align:center">No active projects</div>'); return; }
  let html = '';
  projects.forEach(p => {
    const langs = (p.languages || []).map(l => `<span class="lang">${esc(l)}</span>`).join('');
    const lsp = p.lsp_running ? '<span class="lsp-on">LSP</span>' : '<span class="lsp-off">LSP</span>';
    const idle = p.idle_seconds != null ? `<span class="idle">${fmtTime(p.idle_seconds)} idle</span>` : '';
    const readonly = p.read_only ? '<span style="background:var(--orange);color:#fff;font-size:10px;padding:2px7px;border-radius:3px">RO</span>' : '';
      const sessions = p.session_count != null ? `<span class="idle" style="background:${p.session_count > 0 ? 'var(--accent-dim)' : 'var(--bg-elevated)'};color:${p.session_count > 0 ? 'var(--accent)' : 'var(--text-muted)'}">${p.session_count} session${p.session_count === 1 ? '' : 's'}</span>` : '';
      html += `<div class="project-card">
      <div class="proj-name">${esc(p.name)}</div>
      <div class="proj-path" title="${esc(p.path)}">${esc(p.path)}</div>
      <div class="proj-meta">${langs}${lsp}${idle}${sessions}${readonly}</div>
    </div>`;
  });
  $(container).html(html);
}

/* ── Session List ─────────────────────────────────────────────────────── */
function renderSessions(sessions) {
  if (!sessions || !sessions.length) { $('#sessions-list').html('<div class="config-section" style="text-align:center;padding:2rem;color:var(--text-muted)">No active sessions</div>'); return; }
  let html = '';
  sessions.forEach(s => {
    const idle = s.idle_seconds != null ? ` ${Math.round(s.idle_seconds)}s idle` : '';
    const proj = s.project_name ? `<span class="sproj">${esc(s.project_name)}</span>` : '<span class="sproj" style="color:var(--text-muted)">—</span>';
    html += `<div class="session-item">
      <span class="sid" title="${esc(s.session_id)}">${esc(s.session_id.substr(0,12))}…</span>
      ${proj}
      <span class="sinfo">${s.client_info || ''}${idle}</span>
    </div>`;
  });
  $('#sessions-list').html(html);
}

/* ── Logs ─────────────────────────────────────────────────────────────── */
function appendLogs(response) {
  const msgs = response.messages || [];
  if (!msgs.length) return;
  state.logMaxIdx = response.max_idx;
  const container = $('#log-container');
  const shouldScroll = state.logAutoScroll && Math.abs(container[0].scrollHeight - container[0].scrollTop - container[0].clientHeight) < 40;
  let html = '';
  msgs.forEach(m => {
    const level = m.level || 'INFO';
    const time = m.timestamp ? esc(m.timestamp) : '';
    const proj = m.project_name ? `<span class="log-project">[${esc(m.project_name)}]</span>` : '';
    const msg = esc(m.message || '');
    html += `<div class="log-entry log-${level}"><span class="log-time">${time}</span><span class="log-level">${level}</span>${proj}${msg}</div>`;
  });
  container.append(html);
  // Trim
  const lines = container.children();
  if (lines.length > MAX_LOG_LINES) lines.slice(0, lines.length - MAX_LOG_LINES).remove();
  if (shouldScroll) container.scrollTop(container[0].scrollHeight);
}
function clearLogs() {
  state.logMaxIdx = 0;
  $('#log-container').empty().append('<div class="log-placeholder">Logs cleared</div>');
  api('clear_logs');
}

/* ── Tools Stats ──────────────────────────────────────────────────────── */
function renderToolStats(stats) {
  if (!stats || !Object.keys(stats).length) { $('#tools-stats').html('<div class="config-section" style="text-align:center;padding:2rem;color:var(--text-muted)">No tool usage data yet</div>'); return; }
  const sorted = Object.entries(stats).sort((a,b) => (b[1].num_calls||0) - (a[1].num_calls||0));
  let html = '';
  sorted.forEach(([name, s]) => {
    html += `<div class="tool-stat-item"><span class="ts-name">${esc(name)}</span><span class="ts-count">${s.num_calls || 0}</span></div>`;
  });
  $('#tools-stats').html(html);
}

/* ── Config View ──────────────────────────────────────────────────────── */
function renderConfig(config) {
  let html = '';
  // Context
  html += `<div class="config-section"><h3>Context</h3><div class="config-items"><span class="config-tag active">${esc(config.context.name)}</span></div></div>`;
  // Modes
  html += `<div class="config-section"><h3>Modes</h3><div class="config-items">`;
  (config.modes || []).forEach(m => {
    html += `<span class="config-tag active">${esc(m.name)}</span>`;
  });
  html += `</div></div>`;
  // Active Tools
  html += `<div class="config-section"><h3>Active Tools (${(config.active_tools||[]).length})</h3><div class="config-items">`;
  (config.active_tools || []).forEach(t => {
    html += `<span class="config-tag active">${esc(t)}</span>`;
  });
  html += `</div></div>`;
  // Available Tools
  html += `<div class="config-section"><h3>Available Tools</h3><div class="config-items">`;
  (config.available_tools || []).forEach(t => {
    html += `<span class="config-tag">${esc(t.name)}</span>`;
  });
  html += `</div></div>`;
  // Available Modes
  html += `<div class="config-section"><h3>Available Modes</h3><div class="config-items">`;
  (config.available_modes || []).forEach(m => {
    html += `<span class="config-tag${m.is_active ? ' active' : ''}">${esc(m.name)}</span>`;
  });
  html += `</div></div>`;
  // Available Contexts
  html += `<div class="config-section"><h3>Available Contexts</h3><div class="config-items">`;
  (config.available_contexts || []).forEach(c => {
    html += `<span class="config-tag${c.is_active ? ' active' : ''}">${esc(c.name)}</span>`;
  });
  html += `</div></div>`;
  html += `<div class="config-section"><h3>Version</h3><div style="font-family:var(--mono);color:var(--text-dim);font-size:12px">${esc(config.serena_version)}</div></div>`;
  $('#config-detail').html(html);
}

/* ── Registered Projects ──────────────────────────────────────────────── */
function renderRegisteredProjects(config) {
  const reg = config.registered_projects || [];
  if (!reg.length) { $('#registered-projects').html('<div class="config-section" style="text-align:center;padding:1rem;color:var(--text-muted)">No registered projects</div>'); return; }
  let html = '';
  reg.forEach(p => {
    const sessions = p.session_count != null ? ` ${p.session_count} sess` : '';
    const status = p.is_active ? `<span class="rp-status rp-active">Active${sessions}</span>` : '<span class="rp-status rp-inactive">Inactive</span>';
    html += `<div class="reg-proj-item"><span class="rp-name">${esc(p.name)}</span><span class="rp-path">${esc(p.path)}</span>${status}</div>`;
  });
  $('#registered-projects').html(html);
}

/* ── Overview Projects (compact) ──────────────────────────────────────── */
function renderOverviewProjects(projects) {
  if (!projects || !projects.length) { $('#overview-projects').empty(); return; }
  renderProjectCards(projects, '#overview-projects');
}

/* ── Main Poll ────────────────────────────────────────────────────────── */
function pollConfig() {
  getConfig().then(cfg => {
    state.config = cfg;
    // header
    if (cfg.serena_version) $('#version-badge').text('v' + cfg.serena_version);
    if (cfg.current_client) $('#client-badge').text(esc(cfg.current_client));
    // update all pages
    updateStats(cfg);
    renderProjectCards(cfg.active_projects, '#projects-grid');
    renderSessions(cfg.active_sessions);
    renderToolStats(cfg.tool_stats_summary);
    renderConfig(cfg);
    renderRegisteredProjects(cfg);
    renderOverviewProjects(cfg.active_projects);
  }).fail(() => { /* server not ready */ });
}

function pollLogs() {
  if (state.currentPage !== 'logs') return;
  getLogs().then(r => appendLogs(r)).fail(() => {});
}

/* ── Event Bindings ───────────────────────────────────────────────────── */
$('#theme-btn').click(() => setTheme(!state.darkMode));
$('#clear-logs-btn').click(clearLogs);
$('#scroll-lock-btn').click(function(){
  state.logAutoScroll = !state.logAutoScroll;
  $(this).toggleClass('active');
});
$('#log-level-filter').change(function(){
  state.logFilter.level = this.value;
  state.logMaxIdx = 0;
  $('#log-container').empty().append('<div class="log-placeholder">Filter changed — reloading…</div>');
});
$('#log-search').on('input', function(){
  state.logFilter.search = this.value;
  // Simple client-side filter — just re-display from cached logs
  const container = $('#log-container');
  container.children('.log-entry').each(function(){
    const match = !state.logFilter.search || this.textContent.toLowerCase().includes(state.logFilter.search.toLowerCase());
    $(this).toggle(!!match);
  });
});

/* ── Init ─────────────────────────────────────────────────────────────── */
function init() {
  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  setTheme(prefersDark);
  // Initial polls
  pollConfig();
  // Start polling
  setInterval(pollConfig, POLL_INTERVAL);
  setInterval(pollLogs, LOG_POLL_INTERVAL);
}

/* ── Utilities ────────────────────────────────────────────────────────── */
function esc(s) {
  if (s == null) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
function fmtTime(seconds) {
  if (seconds < 60) return Math.round(seconds) + 's';
  if (seconds < 3600) return Math.round(seconds/60) + 'm';
  return Math.round(seconds/3600) + 'h';
}

$(init);
})();
