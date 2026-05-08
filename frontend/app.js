'use strict';

function esc(str) {
  const d = document.createElement('div');
  d.textContent = str;
  return d.innerHTML;
}

if (typeof marked !== 'undefined') {
  marked.use({
    renderer: {
      html: (token) => esc(token.text),
      link: ({ href, title, tokens }) => {
        if (href && /^javascript:/i.test(href.replace(/\s/g, ''))) {
          return esc(tokens.map(t => t.raw).join(''));
        }
        const titleAttr = title ? ' title="' + esc(title) + '"' : '';
        return '<a href="' + esc(href) + '"' + titleAttr + ' rel="noopener noreferrer">' + marked.Parser.parseInline(tokens) + '</a>';
      },
    },
  });
}

const API = '/api';

const state = {
  view: 'session-list',
  sessions: [],
  templates: [],
  users: [],
  currentSession: null,
  activeSection: null,
  sectionContent: {},
  sectionComments: {},
  sectionProposals: {},
  plugins: [],
  userId: null,
  token: null,
  ws: null,
  aiLogOpen: false,
  aiLogHasNew: false,
  aiLogAutoOpened: false,
};

// --- Utilities ---

async function apiFetch(path, options = {}) {
  const resp = await fetch(`${API}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(err.detail || resp.statusText);
  }
  if (resp.status === 204) return null;
  return resp.json();
}

function showView(name) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  const el = document.getElementById('view-' + name);
  if (el) {
    el.style.removeProperty('display');
    el.classList.add('active');
  }
  state.view = name;
}

function formatTime(iso) {
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}

let _aiLogCurrent = null;
let _aiLogEntriesEl = null;
let _scrollRafPending = false;

function _getLogEntries() {
  if (!_aiLogEntriesEl) _aiLogEntriesEl = document.getElementById('ai-log-entries');
  return _aiLogEntriesEl;
}

function _aiLogScroll() {
  if (_scrollRafPending) return;
  _scrollRafPending = true;
  requestAnimationFrame(() => {
    _scrollRafPending = false;
    const body = document.getElementById('ai-log-body');
    if (body) {
      const near = body.scrollHeight - body.scrollTop - body.clientHeight < 30;
      if (near) body.scrollTop = body.scrollHeight;
    }
  });
}

function _aiLogNewEntry(className) {
  const entries = _getLogEntries();
  if (!entries) return null;
  const el = document.createElement('div');
  el.className = 'ai-log-entry' + (className ? ' ' + className : '');
  entries.appendChild(el);
  while (entries.children.length > 500) entries.firstChild.remove();
  return el;
}

function badgeClass(status) {
  return 'badge badge-' + status.replace('_', '-');
}

function appendAiLogStream(text) {
  if (!_getLogEntries()) return;
  const lines = text.split('\n');
  for (let i = 0; i < lines.length; i++) {
    if (i > 0) _aiLogCurrent = null;
    if (!lines[i]) continue;
    if (!_aiLogCurrent) _aiLogCurrent = _aiLogNewEntry('');
    _aiLogCurrent.textContent += lines[i];
  }
  _aiLogScroll();
}

function appendAiLog(text, className) {
  _aiLogCurrent = null;
  const el = _aiLogNewEntry(className);
  if (el) el.textContent = text;
  _aiLogScroll();
}

function openAiLog() {
  state.aiLogAutoOpened = true;
  state.aiLogOpen = true;
  document.getElementById('ai-log-panel').classList.remove('ai-log-collapsed');
}

function toggleAiLog() {
  const panel = document.getElementById('ai-log-panel');
  if (!panel) return;
  state.aiLogOpen = !state.aiLogOpen;
  panel.classList.toggle('ai-log-collapsed', !state.aiLogOpen);
  if (state.aiLogOpen) {
    state.aiLogHasNew = false;
    document.getElementById('ai-log-dot').style.display = 'none';
  }
}

function clearAiLog() {
  _aiLogCurrent = null;
  const entries = _getLogEntries();
  if (entries) entries.textContent = '';
  state.aiLogAutoOpened = false;
  state.aiLogHasNew = false;
  state.aiLogOpen = false;
  const panel = document.getElementById('ai-log-panel');
  if (panel) panel.classList.add('ai-log-collapsed');
  const dot = document.getElementById('ai-log-dot');
  if (dot) dot.style.display = 'none';
}

// --- Session List ---

async function loadSessionList() {
  [state.sessions, state.templates, state.users] = await Promise.all([
    apiFetch('/sessions'),
    apiFetch('/templates'),
    apiFetch('/users'),
  ]);
  renderSessionList();
  showView('session-list');
  document.getElementById('session-info').textContent = '';
  document.getElementById('progress-indicator').textContent = '';
  document.getElementById('publish-btn').style.display = 'none';
}

function renderSessionList() {
  const container = document.getElementById('sessions-container');
  if (state.sessions.length === 0) {
    container.textContent = '';
    const p = document.createElement('p');
    p.style.color = 'var(--text-secondary)';
    p.textContent = 'No sessions yet. Create one to get started.';
    container.appendChild(p);
    return;
  }
  container.textContent = '';
  state.sessions.forEach(s => {
    const card = document.createElement('div');
    card.className = 'session-card';
    card.dataset.id = s.id;

    const info = document.createElement('div');
    info.className = 'session-card-info';
    const h3 = document.createElement('h3');
    h3.textContent = s.id;
    const span = document.createElement('span');
    span.textContent = s.template + ' · ' + s.status + ' · ' + formatTime(s.created_at);
    info.appendChild(h3);
    info.appendChild(span);
    card.appendChild(info);

    const badge = document.createElement('span');
    badge.className = 'badge badge-' + s.status;
    badge.textContent = s.status;
    card.appendChild(badge);

    card.addEventListener('click', () => openSession(s.id));
    container.appendChild(card);
  });
}

// --- Session Creation ---

function showCreateForm() {
  const coordSelect = document.getElementById('coordinator-select');
  coordSelect.textContent = '';
  state.users.forEach(u => {
    const opt = document.createElement('option');
    opt.value = u.id;
    opt.textContent = u.name + ' (' + u.id + ')';
    coordSelect.appendChild(opt);
  });

  const select = document.getElementById('template-select');
  select.textContent = '';
  state.templates.forEach(t => {
    const opt = document.createElement('option');
    opt.value = t.slug || t.name;
    opt.textContent = t.name + ' — ' + t.description;
    select.appendChild(opt);
  });
  document.getElementById('seed-text').value = '';

  select.onchange = renderSectionOwnersGrid;
  renderSectionOwnersGrid();
  showView('create-session');
}

function renderSectionOwnersGrid() {
  const slug = document.getElementById('template-select').value;
  const template = state.templates.find(t => (t.slug || t.name) === slug);
  const container = document.getElementById('section-owners-grid');
  container.textContent = '';

  if (!template) return;

  const table = document.createElement('div');
  table.className = 'section-owners-table';

  const header = document.createElement('div');
  header.className = 'section-owners-header';
  header.appendChild(Object.assign(document.createElement('span'), { textContent: 'Section' }));
  header.appendChild(Object.assign(document.createElement('span'), { textContent: 'Priority' }));
  header.appendChild(Object.assign(document.createElement('span'), { textContent: 'Owner' }));
  table.appendChild(header);

  template.sections.forEach(section => {
    const row = document.createElement('div');
    row.className = 'section-owner-row';
    row.dataset.sectionId = section.id;

    const titleCell = document.createElement('div');
    const title = document.createElement('div');
    title.className = 'section-owner-title';
    title.textContent = section.title;
    titleCell.appendChild(title);
    if (section.suggested_roles && section.suggested_roles.length > 0) {
      const hint = document.createElement('div');
      hint.className = 'section-owner-hint';
      hint.textContent = 'Suggested: ' + section.suggested_roles.join(', ');
      titleCell.appendChild(hint);
    }
    row.appendChild(titleCell);

    const badgeCell = document.createElement('div');
    const badge = document.createElement('span');
    badge.className = 'badge badge-' + section.priority;
    badge.textContent = section.priority;
    badgeCell.appendChild(badge);
    row.appendChild(badgeCell);

    const ownerCell = document.createElement('div');
    const ownerSelect = document.createElement('select');
    ownerSelect.className = 'section-owner-select';
    ownerSelect.dataset.sectionId = section.id;

    const emptyOpt = document.createElement('option');
    emptyOpt.value = '';
    emptyOpt.textContent = '— unassigned —';
    ownerSelect.appendChild(emptyOpt);

    let autoSelected = '';
    state.users.forEach(u => {
      const opt = document.createElement('option');
      opt.value = u.id;
      opt.textContent = u.name + ' (' + u.id + ')';
      ownerSelect.appendChild(opt);

      if (!autoSelected && section.suggested_roles && section.suggested_roles.length > 0) {
        const userRoles = u.default_roles || [];
        if (section.suggested_roles.some(r => userRoles.includes(r))) {
          autoSelected = u.id;
        }
      }
    });

    if (autoSelected) {
      ownerSelect.value = autoSelected;
    } else {
      row.classList.add('unassigned');
    }

    ownerSelect.addEventListener('change', () => {
      row.classList.toggle('unassigned', ownerSelect.value === '');
    });

    ownerCell.appendChild(ownerSelect);
    row.appendChild(ownerCell);
    table.appendChild(row);
  });

  container.appendChild(table);
}

async function handleCreateSession(e) {
  e.preventDefault();
  const submitBtn = e.target.querySelector('button[type="submit"]');
  submitBtn.disabled = true;
  submitBtn.textContent = '';
  const spinner = document.createElement('span');
  spinner.className = 'spinner';
  submitBtn.appendChild(spinner);
  submitBtn.appendChild(document.createTextNode('Creating…'));

  const slug = document.getElementById('template-select').value;
  const seedText = document.getElementById('seed-text').value.trim();

  const template = state.templates.find(t => (t.slug || t.name) === slug);
  const coordinatorId = document.getElementById('coordinator-select').value;

  const assignments = {};
  document.querySelectorAll('.section-owner-select').forEach(sel => {
    const sectionId = sel.dataset.sectionId;
    let userId = sel.value;
    if (!userId) {
      const sectionDef = template && template.sections.find(s => s.id === sectionId);
      if (sectionDef && sectionDef.priority === 'required') {
        userId = coordinatorId;
      }
    }
    if (userId) {
      if (!assignments[userId]) assignments[userId] = [];
      assignments[userId].push(sectionId);
    }
  });

  const participants = Object.entries(assignments).map(([userId, sections]) => {
    const user = state.users.find(u => u.id === userId);
    const role = (user && user.default_roles && user.default_roles[0]) || 'participant';
    return { user_id: userId, assigned_sections: sections, role };
  });

  try {
    const session = await apiFetch('/sessions', {
      method: 'POST',
      body: JSON.stringify({
        template: slug,
        coordinator: coordinatorId,
        participants: participants,
        seed_text: seedText || undefined,
      }),
    });

    if (session) {
      const coordP = session.participants.find(p => p.user_id === coordinatorId);
      if (coordP && coordP.token) {
        state.token = coordP.token;
        localStorage.setItem('dc-token-' + session.id, coordP.token);
      }
      showInviteLinks(session);
      window.history.pushState({}, '', '/session/' + session.id);
      await openSession(session.id);
    }
  } catch (err) {
    alert('Error: ' + err.message);
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = 'Create Session';
  }
}

function showInviteLinks(session) {
  if (!session.participants || session.participants.length === 0) return;
  const list = document.getElementById('invite-links-list');
  list.textContent = '';
  const base = window.location.origin;

  session.participants.forEach(p => {
    const url = base + '/session/' + session.id + '?token=' + p.token;
    const item = document.createElement('div');
    item.className = 'invite-link-item';

    const info = document.createElement('div');
    const strong = document.createElement('strong');
    strong.textContent = p.user_id;
    const roleSpan = document.createTextNode(' (' + p.role + ')');
    const urlDiv = document.createElement('div');
    urlDiv.className = 'invite-link-url';
    urlDiv.textContent = url;
    info.appendChild(strong);
    info.appendChild(roleSpan);
    info.appendChild(urlDiv);

    const copyBtn = document.createElement('button');
    copyBtn.className = 'btn btn-secondary';
    copyBtn.textContent = 'Copy';
    copyBtn.addEventListener('click', () => navigator.clipboard.writeText(url));

    item.appendChild(info);
    item.appendChild(copyBtn);
    list.appendChild(item);
  });

  const copyAllBtn = document.createElement('button');
  copyAllBtn.className = 'btn btn-primary';
  copyAllBtn.textContent = 'Copy All';
  copyAllBtn.style.marginTop = '0.75rem';
  copyAllBtn.addEventListener('click', () => {
    const allLinks = session.participants.map(p =>
      p.user_id + ' (' + p.role + '): ' + base + '/session/' + session.id + '?token=' + p.token
    ).join('\n');
    navigator.clipboard.writeText(allLinks);
    copyAllBtn.textContent = 'Copied!';
    setTimeout(() => { copyAllBtn.textContent = 'Copy All'; }, 1500);
  });
  list.appendChild(copyAllBtn);

  document.getElementById('invite-modal').style.display = 'flex';
}

// --- Workspace ---

async function openSession(sessionId) {
  if (window.location.pathname !== '/session/' + sessionId) {
    window.history.pushState({}, '', '/session/' + sessionId);
  }
  state.token = localStorage.getItem('dc-token-' + sessionId) || null;
  state.currentSession = await apiFetch(sessionPath(sessionId));
  state.sectionContent = {};
  state.sectionComments = {};
  state.sectionProposals = {};
  state.activeSection = null;
  clearAiLog();
  connectWebSocket(sessionId);

  const hasDrafting = Object.values(state.currentSession.section_meta)
    .some(m => m.status === 'drafting');
  if (hasDrafting) {
    appendAiLog('AI drafting in progress...', '');
    openAiLog();
  }

  const meta = state.currentSession.section_meta;
  await Promise.all(
    Object.keys(meta).map(async sid => {
      const base = '/sessions/' + sessionId + '/sections/' + sid;
      const [content, comments, proposals] = await Promise.all([
        apiFetch(base),
        apiFetch(base + '/comments'),
        apiFetch(base + '/proposals'),
      ]);
      state.sectionContent[sid] = content;
      state.sectionComments[sid] = comments;
      state.sectionProposals[sid] = proposals;
    })
  );

  if (state.templates.length === 0) {
    state.templates = await apiFetch('/templates');
  }

  resolveUserId();
  renderWorkspace();
  showView('workspace');
  updateHeader();
}

function updateHeader() {
  const s = state.currentSession;
  if (!s) return;
  const info = s.id + ' — ' + s.template;
  document.getElementById('session-info').textContent =
    state.userId ? info + ' · logged in as ' + state.userId : info;

  const p = s.progress;
  let progressText = p.approved + '/' + p.total + ' approved';
  if (p.skipped > 0) progressText += ', ' + p.skipped + ' skipped';
  if (p.required_remaining > 0) progressText += ' (' + p.required_remaining + ' required left)';
  document.getElementById('progress-indicator').textContent = progressText;

  const publishBtn = document.getElementById('publish-btn');
  publishBtn.style.display = 'inline-block';
  publishBtn.disabled = !s.ready_to_publish || s.status === 'published';
}

function renderWorkspace() {
  const firstSection = Object.keys(state.currentSession.section_meta)[0];
  if (!state.activeSection && firstSection) {
    state.activeSection = firstSection;
  }
  renderSidebar();
  renderReviewArea();
}

function findTemplate() {
  const s = state.currentSession;
  return state.templates.find(
    t => (t.slug || t.name) === s.template
  );
}

function renderSidebar() {
  const s = state.currentSession;
  const template = findTemplate();
  const list = document.getElementById('section-list');
  list.textContent = '';

  Object.entries(s.section_meta).forEach(([sid, meta]) => {
    const sectionDef = template ? template.sections.find(sec => sec.id === sid) : null;
    const participants = s.participants || [];
    const owner = participants.find(p => p.role !== 'coordinator' && p.assigned_sections.includes(sid))
      || participants.find(p => p.assigned_sections.includes(sid));
    const pendingCount = (state.sectionProposals[sid] || []).filter(p => p.status === 'pending').length;

    const item = document.createElement('div');
    item.className = 'sidebar-item' + (state.activeSection === sid ? ' active' : '');
    item.dataset.section = sid;

    const header = document.createElement('div');
    header.className = 'sidebar-item-header';
    const title = document.createElement('span');
    title.className = 'sidebar-item-title';
    const titleText = sectionDef ? sectionDef.title : sid;
    title.textContent = titleText;
    title.title = titleText;
    const badge = document.createElement('span');
    badge.className = badgeClass(meta.status);
    badge.textContent = meta.status;
    header.appendChild(title);
    header.appendChild(badge);
    item.appendChild(header);

    if (pendingCount > 0) {
      const pending = document.createElement('div');
      pending.style.cssText = 'font-size:0.7rem;color:var(--primary);margin-top:0.15rem';
      pending.textContent = pendingCount + ' pending';
      item.appendChild(pending);
    }

    const ownerDiv = document.createElement('div');
    ownerDiv.className = 'sidebar-item-owner';
    ownerDiv.textContent = owner ? owner.user_id : '— unassigned —';
    ownerDiv.addEventListener('click', (e) => {
      e.stopPropagation();
      showOwnerDropdown(sid, ownerDiv);
    });
    item.appendChild(ownerDiv);

    item.addEventListener('click', () => selectSection(sid));
    list.appendChild(item);
  });
}

function selectSection(sectionId) {
  state.activeSection = sectionId;
  renderSidebar();
  renderReviewArea();
}

function showOwnerDropdown(sectionId, container) {
  if (container.querySelector('select')) return;
  const s = state.currentSession;
  const participants = s.participants || [];
  const currentOwner = participants.find(p => p.role !== 'coordinator' && p.assigned_sections.includes(sectionId))
    || participants.find(p => p.assigned_sections.includes(sectionId));

  const sel = document.createElement('select');
  const emptyOpt = document.createElement('option');
  emptyOpt.value = '';
  emptyOpt.textContent = '— unassigned —';
  sel.appendChild(emptyOpt);

  state.users.forEach(u => {
    const opt = document.createElement('option');
    opt.value = u.id;
    opt.textContent = u.name + ' (' + u.id + ')';
    if (currentOwner && currentOwner.user_id === u.id) opt.selected = true;
    sel.appendChild(opt);
  });

  container.textContent = '';
  container.appendChild(sel);
  sel.focus();

  let changed = false;
  sel.addEventListener('change', async () => {
    const userId = sel.value;
    if (!userId) return;
    try {
      await apiFetch('/sessions/' + state.currentSession.id + '/sections/' + sectionId + '/assign', {
        method: 'POST',
        body: JSON.stringify({ user_id: userId }),
      });
      changed = true;
      container.textContent = userId;
    } catch (err) {
      alert('Error: ' + err.message);
    }
  });

  sel.addEventListener('blur', () => {
    if (!changed) {
      container.textContent = currentOwner ? currentOwner.user_id : '— unassigned —';
    }
  });
}

// --- Review Area ---

function renderReviewArea() {
  const sid = state.activeSection;
  const emptyEl = document.getElementById('review-empty');

  if (!sid) {
    emptyEl.style.display = 'flex';
    document.getElementById('review-header').style.display = 'none';
    document.getElementById('review-status').style.display = 'none';
    document.getElementById('review-draft').style.display = 'none';
    document.getElementById('review-proposals').style.display = 'none';
    document.getElementById('review-comments').style.display = 'none';
    return;
  }

  emptyEl.style.display = 'none';
  document.getElementById('review-header').style.display = 'flex';
  document.getElementById('review-status').style.display = 'block';
  document.getElementById('review-draft').style.display = 'block';
  document.getElementById('review-proposals').style.display = 'block';
  document.getElementById('review-comments').style.display = 'block';

  const s = state.currentSession;
  const meta = s.section_meta[sid];
  const template = findTemplate();
  const sectionDef = template ? template.sections.find(sec => sec.id === sid) : null;
  const content = state.sectionContent[sid] ? state.sectionContent[sid].content : '';
  const comments = state.sectionComments[sid] || [];
  const proposals = state.sectionProposals[sid] || [];
  const isOwner = canActOnSection(sid);

  document.getElementById('review-title').textContent = sectionDef ? sectionDef.title : sid;

  const statusDiv = document.getElementById('review-status');
  statusDiv.textContent = '';
  const badge = document.createElement('span');
  badge.className = badgeClass(meta.status);
  badge.textContent = meta.status;
  statusDiv.appendChild(badge);

  const frozen = meta.status === 'approved' || meta.status === 'skipped' || meta.status === 'drafting';
  document.getElementById('review-approve-btn').style.display =
    (isOwner && !frozen) ? 'inline-block' : 'none';
  document.getElementById('review-skip-btn').style.display =
    (isOwner && sectionDef && sectionDef.priority !== 'required' && !frozen) ? 'inline-block' : 'none';
  document.getElementById('review-reopen-btn').style.display =
    (isOwner && meta.status === 'approved') ? 'inline-block' : 'none';

  const draftEl = document.getElementById('review-draft');
  draftEl.textContent = '';
  const draftH4 = document.createElement('h4');
  draftH4.textContent = 'Draft';
  draftEl.appendChild(draftH4);
  const draftContent = document.createElement('div');
  draftContent.className = 'draft-content';
  if (content) {
    const rendered = typeof marked !== 'undefined' ? marked.parse(content) : esc(content);
    const temp = document.createElement('template');
    temp.innerHTML = rendered;
    draftContent.appendChild(temp.content);
  } else {
    const em = document.createElement('em');
    em.textContent = 'No content yet.';
    draftContent.appendChild(em);
  }
  draftEl.appendChild(draftContent);

  const proposalsEl = document.getElementById('review-proposals');
  proposalsEl.textContent = '';
  const pendingProposals = proposals.filter(p => p.status === 'pending');
  const pastProposals = proposals.filter(p => p.status !== 'pending');
  if (pendingProposals.length > 0) {
    const h4 = document.createElement('h4');
    h4.textContent = 'Pending Proposals';
    proposalsEl.appendChild(h4);
    pendingProposals.forEach(p => proposalsEl.appendChild(buildProposalEl(p, content, isOwner)));
  }
  if (pastProposals.length > 0) {
    const h4 = document.createElement('h4');
    h4.textContent = 'Past Proposals';
    h4.style.marginTop = '0.5rem';
    proposalsEl.appendChild(h4);
    pastProposals.forEach(p => proposalsEl.appendChild(buildProposalEl(p, content, false)));
  }

  const thread = document.getElementById('comments-thread');
  thread.textContent = '';
  comments.forEach(c => {
    const div = document.createElement('div');
    div.className = 'comment' + (c.author === 'ai' ? ' comment-ai' : '');
    const headerDiv = document.createElement('div');
    headerDiv.className = 'comment-header';
    const authorSpan = document.createElement('span');
    authorSpan.className = 'comment-author';
    authorSpan.textContent = c.author === 'ai' ? 'AI Assistant' : c.author;
    const timeSpan = document.createElement('span');
    timeSpan.className = 'comment-time';
    timeSpan.textContent = formatTime(c.timestamp);
    headerDiv.appendChild(authorSpan);
    headerDiv.appendChild(timeSpan);
    const textDiv = document.createElement('div');
    textDiv.className = 'comment-text';
    textDiv.textContent = c.text;
    div.appendChild(headerDiv);
    div.appendChild(textDiv);
    thread.appendChild(div);
  });

  const commentInput = document.getElementById('comment-input');
  const commentBtn = document.getElementById('submit-comment-btn');
  const commentDisabled = meta.status === 'approved' || meta.status === 'drafting';
  commentInput.disabled = commentDisabled;
  commentBtn.disabled = commentDisabled;
}

function buildUnifiedDiff(oldText, newText) {
  const container = document.createElement('div');
  container.className = 'diff-unified';

  const oldParagraphs = (oldText || '').split(/\n\n+/);
  const newParagraphs = (newText || '').split(/\n\n+/);
  const maxLen = Math.max(oldParagraphs.length, newParagraphs.length);

  const elements = [];
  let unchangedRun = [];

  function flushUnchanged() {
    if (unchangedRun.length === 0) return;
    const collapsed = document.createElement('div');
    collapsed.className = 'diff-collapsed';
    const count = unchangedRun.length;
    collapsed.textContent = '— ' + count + ' unchanged paragraph' + (count > 1 ? 's' : '') + ' —';
    const hiddenParagraphs = unchangedRun.slice();
    collapsed.addEventListener('click', () => {
      if (collapsed.nextSibling && collapsed.nextSibling.classList &&
          collapsed.nextSibling.classList.contains('diff-collapsed-content')) {
        collapsed.nextSibling.remove();
        collapsed.textContent = '— ' + count + ' unchanged paragraph' + (count > 1 ? 's' : '') + ' —';
        return;
      }
      const expanded = document.createElement('div');
      expanded.className = 'diff-collapsed-content';
      hiddenParagraphs.forEach(text => {
        const p = document.createElement('div');
        p.className = 'diff-paragraph';
        p.textContent = text;
        expanded.appendChild(p);
      });
      collapsed.after(expanded);
      collapsed.textContent = '— collapse —';
    });
    elements.push(collapsed);
    unchangedRun = [];
  }

  for (let i = 0; i < maxLen; i++) {
    const oldP = i < oldParagraphs.length ? oldParagraphs[i] : null;
    const newP = i < newParagraphs.length ? newParagraphs[i] : null;

    if (oldP !== null && newP !== null && oldP === newP) {
      unchangedRun.push(oldP);
      continue;
    }

    flushUnchanged();

    if (oldP !== null && newP === null) {
      const p = document.createElement('div');
      p.className = 'diff-paragraph diff-paragraph-removed';
      p.textContent = oldP;
      elements.push(p);
    } else if (oldP === null && newP !== null) {
      const p = document.createElement('div');
      p.className = 'diff-paragraph diff-paragraph-added';
      p.textContent = newP;
      elements.push(p);
    } else {
      const p = document.createElement('div');
      p.className = 'diff-paragraph';
      const diff = Diff.diffWords(oldP, newP);
      diff.forEach(part => {
        const span = document.createElement('span');
        if (part.added) {
          span.className = 'diff-word-added';
        } else if (part.removed) {
          span.className = 'diff-word-removed';
        }
        span.textContent = part.value;
        p.appendChild(span);
      });
      elements.push(p);
    }
  }

  flushUnchanged();

  if (elements.length === 0) {
    const p = document.createElement('div');
    p.className = 'diff-paragraph';
    p.style.color = 'var(--text-secondary)';
    p.textContent = 'No changes';
    elements.push(p);
  }

  elements.forEach(el => container.appendChild(el));
  return container;
}

function buildProposalEl(proposal, currentContent, showActions) {
  const div = document.createElement('div');
  div.className = 'proposal';

  const header = document.createElement('div');
  header.className = 'proposal-header';
  const idSpan = document.createElement('span');
  idSpan.className = 'proposal-id';
  idSpan.textContent = proposal.id;
  const statusSpan = document.createElement('span');
  statusSpan.className = 'proposal-status';
  statusSpan.textContent = proposal.status;
  header.appendChild(idSpan);
  header.appendChild(statusSpan);
  div.appendChild(header);

  const summary = document.createElement('div');
  summary.className = 'proposal-summary';
  summary.textContent = proposal.summary;
  div.appendChild(summary);

  if (proposal.status === 'pending') {
    const fullTextView = document.createElement('div');
    fullTextView.className = 'proposal-diff';
    fullTextView.style.display = 'none';

    const currentLabel = document.createElement('div');
    currentLabel.className = 'diff-label';
    currentLabel.textContent = 'Current';
    const currentDiv = document.createElement('div');
    currentDiv.className = 'diff-content diff-current';
    currentDiv.textContent = currentContent || '(empty)';

    const proposedLabel = document.createElement('div');
    proposedLabel.className = 'diff-label';
    proposedLabel.textContent = 'Proposed';
    const proposedDiv = document.createElement('div');
    proposedDiv.className = 'diff-content diff-proposed';
    proposedDiv.textContent = proposal.revised_text;

    fullTextView.appendChild(currentLabel);
    fullTextView.appendChild(currentDiv);
    fullTextView.appendChild(proposedLabel);
    fullTextView.appendChild(proposedDiv);

    const unifiedView = buildUnifiedDiff(currentContent, proposal.revised_text);

    const toggle = document.createElement('div');
    toggle.className = 'diff-toggle';
    const changesBtn = document.createElement('button');
    changesBtn.textContent = 'Changes';
    changesBtn.className = 'active';
    const fullBtn = document.createElement('button');
    fullBtn.textContent = 'Full text';

    changesBtn.addEventListener('click', () => {
      unifiedView.style.display = '';
      fullTextView.style.display = 'none';
      changesBtn.classList.add('active');
      fullBtn.classList.remove('active');
    });
    fullBtn.addEventListener('click', () => {
      unifiedView.style.display = 'none';
      fullTextView.style.display = '';
      fullBtn.classList.add('active');
      changesBtn.classList.remove('active');
    });

    toggle.appendChild(changesBtn);
    toggle.appendChild(fullBtn);
    div.appendChild(toggle);
    div.appendChild(unifiedView);
    div.appendChild(fullTextView);
  }

  if (showActions && proposal.status === 'pending') {
    const actions = document.createElement('div');
    actions.className = 'proposal-actions';

    const acceptBtn = document.createElement('button');
    acceptBtn.className = 'btn btn-success';
    acceptBtn.textContent = 'Accept';
    acceptBtn.addEventListener('click', (e) => { e.stopPropagation(); acceptProposal(proposal.id); });

    const rejectBtn = document.createElement('button');
    rejectBtn.className = 'btn btn-danger';
    rejectBtn.textContent = 'Reject';
    rejectBtn.addEventListener('click', (e) => { e.stopPropagation(); rejectProposal(proposal.id); });

    actions.appendChild(acceptBtn);
    actions.appendChild(rejectBtn);
    div.appendChild(actions);
  }

  return div;
}

function canActOnSection(sectionId) {
  const s = state.currentSession;
  if (!state.userId) return false;
  if (s.coordinator === state.userId) return true;
  return (s.participants || []).some(
    p => p.user_id === state.userId && p.assigned_sections.includes(sectionId)
  );
}

// --- Actions ---

async function submitComment() {
  const input = document.getElementById('comment-input');
  const text = input.value.trim();
  if (!text || !state.activeSection || !state.userId) return;

  input.value = '';
  try {
    await apiFetch('/sessions/' + state.currentSession.id + '/comments', {
      method: 'POST',
      body: JSON.stringify({
        section_id: state.activeSection,
        author: state.userId,
        text: text,
      }),
    });
  } catch (err) {
    input.value = text;
    alert('Error: ' + err.message);
  }
}

async function acceptProposal(proposalId) {
  if (!state.userId) return;
  try {
    await apiFetch('/sessions/' + state.currentSession.id + '/proposals/' + proposalId + '/accept', {
      method: 'POST',
      body: JSON.stringify({ user_id: state.userId }),
    });
  } catch (err) {
    alert('Error: ' + err.message);
  }
}

async function rejectProposal(proposalId) {
  if (!state.userId) return;
  try {
    await apiFetch('/sessions/' + state.currentSession.id + '/proposals/' + proposalId + '/reject', {
      method: 'POST',
      body: JSON.stringify({ user_id: state.userId }),
    });
  } catch (err) {
    alert('Error: ' + err.message);
  }
}

async function approveSection() {
  if (!state.activeSection || !state.userId) return;
  try {
    await apiFetch('/sessions/' + state.currentSession.id + '/sections/' + state.activeSection + '/approve', {
      method: 'POST',
      body: JSON.stringify({ user_id: state.userId }),
    });
  } catch (err) {
    alert('Error: ' + err.message);
  }
}

async function reopenSection() {
  if (!state.activeSection || !state.userId) return;
  try {
    await apiFetch('/sessions/' + state.currentSession.id + '/sections/' + state.activeSection + '/reopen', {
      method: 'POST',
      body: JSON.stringify({ user_id: state.userId }),
    });
  } catch (err) {
    alert('Error: ' + err.message);
  }
}

async function skipSection() {
  if (!state.activeSection || !state.userId) return;
  try {
    await apiFetch('/sessions/' + state.currentSession.id + '/sections/' + state.activeSection + '/skip', {
      method: 'POST',
      body: JSON.stringify({ user_id: state.userId }),
    });
  } catch (err) {
    alert('Error: ' + err.message);
  }
}

function renderPluginFields(schema) {
  var container = document.getElementById('publish-plugin-fields');
  while (container.firstChild) container.removeChild(container.firstChild);
  if (!schema || schema.length === 0) return;
  schema.forEach(function(field) {
    var fieldId = 'plugin-field-' + field.name;
    var label = document.createElement('label');
    label.textContent = field.label;
    label.htmlFor = fieldId;
    container.appendChild(label);
    if (field.type === 'select') {
      var select = document.createElement('select');
      select.id = fieldId;
      select.dataset.fieldName = field.name;
      if (field.required) select.required = true;
      if (!field.required) {
        var blank = document.createElement('option');
        blank.value = '';
        blank.textContent = 'Select…';
        select.appendChild(blank);
      }
      (field.options || []).forEach(function(opt) {
        var option = document.createElement('option');
        option.value = opt;
        option.textContent = opt;
        if (field.default === opt) option.selected = true;
        select.appendChild(option);
      });
      container.appendChild(select);
    } else {
      var input = document.createElement('input');
      input.type = 'text';
      input.id = fieldId;
      input.dataset.fieldName = field.name;
      if (field.placeholder) input.placeholder = field.placeholder;
      if (field.default) input.value = field.default;
      if (field.required) input.required = true;
      container.appendChild(input);
      if (field.type === 'list') {
        var hint = document.createElement('small');
        hint.textContent = '(comma-separated)';
        hint.style.display = 'block';
        hint.style.marginTop = '-0.25rem';
        hint.style.marginBottom = '0.5rem';
        hint.style.opacity = '0.7';
        container.appendChild(hint);
      }
    }
  });
}

function collectPluginConfig(schema) {
  var config = {};
  if (!schema) return config;
  var container = document.getElementById('publish-plugin-fields');
  schema.forEach(function(field) {
    var el = container.querySelector('[data-field-name="' + field.name + '"]');
    if (!el) return;
    var raw = el.value.trim();
    if (field.type === 'list') {
      config[field.name] = raw ? raw.split(',').map(function(s) { return s.trim(); }).filter(Boolean) : [];
    } else {
      config[field.name] = raw;
    }
  });
  return config;
}

async function showPublishModal() {
  if (state.plugins.length === 0) {
    state.plugins = await apiFetch('/plugins');
  }

  var select = document.getElementById('publish-plugin-select');
  select.textContent = '';
  state.plugins.forEach(function(p) {
    var opt = document.createElement('option');
    opt.value = p.name;
    opt.textContent = p.name.replace(/_/g, ' ');
    select.appendChild(opt);
  });

  function onPluginChange() {
    var plugin = state.plugins.find(function(p) { return p.name === select.value; });
    renderPluginFields(plugin ? plugin.config_schema : []);
    var sessionId = state.currentSession ? state.currentSession.id : '';
    var summaryInput = document.querySelector('[data-field-name="summary"]');
    if (summaryInput && !summaryInput.value) summaryInput.value = sessionId;
    var filenameInput = document.querySelector('[data-field-name="filename"]');
    if (filenameInput && !filenameInput.value) filenameInput.value = sessionId + '.md';
  }

  select.onchange = onPluginChange;
  onPluginChange();

  document.getElementById('publish-modal').style.display = 'flex';
}

async function handlePublish(e) {
  e.preventDefault();
  var pluginName = document.getElementById('publish-plugin-select').value;
  var pluginMeta = state.plugins.find(function(p) { return p.name === pluginName; });
  var config = collectPluginConfig(pluginMeta ? pluginMeta.config_schema : []);

  const submitBtn = e.target.querySelector('button[type="submit"]');
  submitBtn.disabled = true;
  submitBtn.textContent = 'Publishing…';

  try {
    const resp = await fetch(API + '/sessions/' + state.currentSession.id + '/publish', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ plugin: pluginName, config }),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: resp.statusText }));
      var msg = Array.isArray(err.detail) ? err.detail.join('\n') : (err.detail || resp.statusText);
      throw new Error(msg);
    }

    if (pluginMeta && pluginMeta.download) {
      const filename = config.filename || state.currentSession.id + '.md';
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } else {
      const result = await resp.json();
      alert('Published. Reference: ' + result.output_ref);
    }

    document.getElementById('publish-modal').style.display = 'none';
    await openSession(state.currentSession.id);
  } catch (err) {
    alert('Error: ' + err.message);
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = 'Publish';
  }
}

// --- WebSocket ---

function connectWebSocket(sessionId) {
  if (state.ws) {
    state.ws.close();
    state.ws = null;
  }
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const url = proto + '//' + window.location.host + '/ws/sessions/' + sessionId +
    (state.token ? '?token=' + encodeURIComponent(state.token) : '');

  const ws = new WebSocket(url);
  ws.onmessage = async (event) => {
    let msg;
    try { msg = JSON.parse(event.data); } catch { return; }
    await handleWsMessage(msg);
  };
  ws.onclose = () => { state.ws = null; };
  state.ws = ws;
}

function sessionPath(sessionId) {
  const tokenParam = state.token ? '?token=' + encodeURIComponent(state.token) : '';
  return '/sessions/' + sessionId + tokenParam;
}

async function handleWsMessage(msg) {
  const sid = state.currentSession ? state.currentSession.id : null;
  if (!sid) return;

  const sectionId = msg.section_id;

  if (msg.type === 'ai_activity') {
    if (!state.aiLogAutoOpened) openAiLog();
    if (!state.aiLogOpen) {
      state.aiLogHasNew = true;
      document.getElementById('ai-log-dot').style.display = '';
    }
    if (msg.error) {
      appendAiLog(msg.text, 'error');
    } else {
      appendAiLogStream(msg.text);
    }
  } else if (msg.type === 'ai_complete') {
    appendAiLog('AI processing complete.', 'complete');
  } else if (msg.type === 'drafts_started') {
    appendAiLog('Generating drafts...', '');
    state.currentSession = await apiFetch(sessionPath(sid));
    renderSidebar();
  } else if (msg.type === 'section_draft_ready' && sectionId) {
    appendAiLog('Drafted: ' + sectionId, '');
    state.currentSession = await apiFetch(sessionPath(sid));
    state.sectionContent[sectionId] = await apiFetch('/sessions/' + sid + '/sections/' + sectionId);
    renderSidebar();
    if (state.activeSection === sectionId) renderReviewArea();
  } else if (msg.type === 'drafts_complete') {
    appendAiLog('All drafts complete.', 'complete');
    state.currentSession = await apiFetch(sessionPath(sid));
    updateHeader();
    renderSidebar();
  } else if (msg.type === 'drafts_failed') {
    appendAiLog(msg.message || 'Draft generation failed.', 'error');
    state.currentSession = await apiFetch(sessionPath(sid));
    updateHeader();
    renderSidebar();
  } else if (msg.type === 'comment_added' && sectionId) {
    state.sectionComments[sectionId] = await apiFetch('/sessions/' + sid + '/sections/' + sectionId + '/comments');
    if (state.activeSection === sectionId) renderReviewArea();
  } else if (msg.type === 'proposal_created' && sectionId) {
    state.sectionProposals[sectionId] = await apiFetch('/sessions/' + sid + '/sections/' + sectionId + '/proposals');
    if (state.activeSection === sectionId) renderReviewArea();
    renderSidebar();
  } else if ((msg.type === 'proposal_accepted' || msg.type === 'proposal_rejected') && sectionId) {
    state.sectionProposals[sectionId] = await apiFetch('/sessions/' + sid + '/sections/' + sectionId + '/proposals');
    state.sectionContent[sectionId] = await apiFetch('/sessions/' + sid + '/sections/' + sectionId);
    if (state.activeSection === sectionId) renderReviewArea();
    renderSidebar();
  } else if (msg.type === 'section_approved' || msg.type === 'section_reopened' || msg.type === 'section_skipped') {
    state.currentSession = await apiFetch(sessionPath(sid));
    updateHeader();
    renderSidebar();
    if (state.activeSection === sectionId) renderReviewArea();
  } else if (msg.type === 'session_published') {
    state.currentSession = await apiFetch(sessionPath(sid));
    updateHeader();
    renderSidebar();
  } else if (msg.type === 'section_assigned') {
    state.currentSession = await apiFetch(sessionPath(sid));
    renderSidebar();
  }
}

// --- Routing & Init ---

function parseRoute() {
  const path = window.location.pathname;
  const params = new URLSearchParams(window.location.search);

  const sessionMatch = path.match(/^\/session\/(.+)$/);
  if (sessionMatch) {
    const sessionId = sessionMatch[1];
    const token = params.get('token');
    if (token) {
      localStorage.setItem('dc-token-' + sessionId, token);
      state.token = token;
      window.history.replaceState({}, '', path);
    } else {
      state.token = localStorage.getItem('dc-token-' + sessionId);
    }
    return { view: 'workspace', sessionId: sessionId };
  }
  return { view: 'session-list' };
}

function resolveUserId() {
  if (!state.currentSession) {
    state.userId = null;
    return;
  }
  state.userId = state.currentSession.current_user_id || null;
}

async function init() {
  const route = parseRoute();

  document.getElementById('logo-home').addEventListener('click', () => {
    if (state.ws) { state.ws.close(); state.ws = null; }
    state.currentSession = null;
    state.activeSection = null;
    window.history.pushState({}, '', '/');
    loadSessionList();
  });
  document.getElementById('create-session-btn').addEventListener('click', showCreateForm);
  document.getElementById('cancel-create-btn').addEventListener('click', loadSessionList);
  document.getElementById('create-session-form').addEventListener('submit', handleCreateSession);
  document.getElementById('submit-comment-btn').addEventListener('click', submitComment);
  document.getElementById('review-approve-btn').addEventListener('click', approveSection);
  document.getElementById('review-reopen-btn').addEventListener('click', reopenSection);
  document.getElementById('review-skip-btn').addEventListener('click', skipSection);
  document.getElementById('invite-links-btn').addEventListener('click', () => showInviteLinks(state.currentSession));
  document.getElementById('publish-btn').addEventListener('click', showPublishModal);
  document.getElementById('cancel-publish-btn').addEventListener('click', () => {
    document.getElementById('publish-modal').style.display = 'none';
  });
  document.getElementById('publish-form').addEventListener('submit', handlePublish);
  document.getElementById('close-invite-modal').addEventListener('click', () => {
    document.getElementById('invite-modal').style.display = 'none';
  });
  document.getElementById('comment-input').addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) submitComment();
  });
  document.getElementById('seed-upload-btn').addEventListener('click', () => {
    document.getElementById('seed-file').click();
  });
  document.getElementById('seed-file').addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (!file) return;
    document.getElementById('seed-file-name').textContent = file.name;
    const reader = new FileReader();
    reader.onload = () => {
      document.getElementById('seed-text').value = reader.result;
    };
    reader.readAsText(file);
  });
  document.getElementById('ai-log-toggle').addEventListener('click', toggleAiLog);
  document.getElementById('ai-log-close').addEventListener('click', (e) => {
    e.stopPropagation();
    if (state.aiLogOpen) toggleAiLog();
  });

  if (route.view === 'workspace' && route.sessionId) {
    state.templates = await apiFetch('/templates');
    await openSession(route.sessionId);
  } else {
    await loadSessionList();
  }
}

init().catch(err => {
  document.body.style.padding = '2rem';
  document.body.textContent = 'Init error: ' + err.message;
  console.error('init() failed:', err);
});
