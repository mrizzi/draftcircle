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
  userId: null,
  token: null,
  ws: null,
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
  if (el) el.classList.add('active');
  state.view = name;
}

function formatTime(iso) {
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  });
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
  const select = document.getElementById('template-select');
  select.textContent = '';
  state.templates.forEach(t => {
    const opt = document.createElement('option');
    opt.value = t.slug || t.name;
    opt.textContent = t.name + ' — ' + t.description;
    select.appendChild(opt);
  });
  document.getElementById('participants-list').textContent = '';
  document.getElementById('seed-text').value = '';
  showView('create-session');
}

function addParticipantRow() {
  const list = document.getElementById('participants-list');
  const row = document.createElement('div');
  row.style.cssText = 'display:flex;gap:0.5rem;margin-bottom:0.5rem;align-items:center;';

  const userSelect = document.createElement('select');
  userSelect.className = 'participant-user';
  userSelect.style.flex = '1';
  state.users.forEach(u => {
    const opt = document.createElement('option');
    opt.value = u.id;
    opt.textContent = u.name + ' (' + u.id + ')';
    userSelect.appendChild(opt);
  });

  const roleInput = document.createElement('input');
  roleInput.className = 'participant-role';
  roleInput.placeholder = 'Role';
  roleInput.style.cssText = 'flex:1;padding:0.4rem;border:1px solid var(--border);border-radius:4px';

  const sectionsInput = document.createElement('input');
  sectionsInput.className = 'participant-sections';
  sectionsInput.placeholder = 'Sections (comma-separated)';
  sectionsInput.style.cssText = 'flex:2;padding:0.4rem;border:1px solid var(--border);border-radius:4px';

  const removeBtn = document.createElement('button');
  removeBtn.type = 'button';
  removeBtn.className = 'btn-icon';
  removeBtn.textContent = '×';
  removeBtn.addEventListener('click', () => row.remove());

  row.appendChild(userSelect);
  row.appendChild(roleInput);
  row.appendChild(sectionsInput);
  row.appendChild(removeBtn);
  list.appendChild(row);
}

async function handleCreateSession(e) {
  e.preventDefault();
  const slug = document.getElementById('template-select').value;
  const seedText = document.getElementById('seed-text').value.trim();

  const rows = document.getElementById('participants-list').children;
  const participants = Array.from(rows).map(row => ({
    user_id: row.querySelector('.participant-user').value,
    role: row.querySelector('.participant-role').value || 'participant',
    assigned_sections: row.querySelector('.participant-sections').value
      .split(',').map(s => s.trim()).filter(Boolean),
  }));

  try {
    const session = await apiFetch('/sessions', {
      method: 'POST',
      body: JSON.stringify({
        template: slug,
        coordinator: state.userId || 'coordinator',
        participants: participants,
        seed_text: seedText || undefined,
      }),
    });
    showInviteLinks(session);
    await loadSessionList();
  } catch (err) {
    alert('Error: ' + err.message);
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

  document.getElementById('invite-modal').style.display = 'flex';
}

// --- Workspace ---

async function openSession(sessionId) {
  state.currentSession = await apiFetch(sessionPath(sessionId));
  state.sectionContent = {};
  state.sectionComments = {};
  state.sectionProposals = {};
  state.activeSection = null;

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
  connectWebSocket(sessionId);
  updateHeader();
}

function updateHeader() {
  const s = state.currentSession;
  if (!s) return;
  document.getElementById('session-info').textContent = s.id + ' — ' + s.template;

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
  renderSectionGrid();
}

function findTemplate() {
  const s = state.currentSession;
  return state.templates.find(
    t => (t.slug || t.name) === s.template
  );
}

function renderSectionGrid() {
  const s = state.currentSession;
  const template = findTemplate();
  const grid = document.getElementById('section-grid');
  grid.textContent = '';

  Object.entries(s.section_meta).forEach(([sid, meta]) => {
    const sectionDef = template ? template.sections.find(sec => sec.id === sid) : null;
    const content = state.sectionContent[sid] ? state.sectionContent[sid].content : '';
    const preview = content.replace(/[#*_\[\]]/g, '').slice(0, 120);
    const assignees = (s.participants || [])
      .filter(p => p.assigned_sections.includes(sid))
      .map(p => p.user_id).join(', ');
    const pendingCount = (state.sectionProposals[sid] || [])
      .filter(p => p.status === 'pending').length;

    const card = document.createElement('div');
    card.className = 'section-card' + (state.activeSection === sid ? ' active' : '');
    card.dataset.section = sid;

    const header = document.createElement('div');
    header.className = 'section-card-header';
    const h3 = document.createElement('h3');
    h3.textContent = sectionDef ? sectionDef.title : sid;
    header.appendChild(h3);
    const badge = document.createElement('span');
    badge.className = 'badge badge-' + meta.status.replace(' ', '-');
    badge.textContent = meta.status;
    header.appendChild(badge);
    card.appendChild(header);

    if (assignees) {
      const aDiv = document.createElement('div');
      aDiv.className = 'section-card-assignees';
      aDiv.textContent = 'Assigned: ' + assignees;
      card.appendChild(aDiv);
    }

    if (preview) {
      const pDiv = document.createElement('div');
      pDiv.className = 'section-card-preview';
      pDiv.textContent = preview + '...';
      card.appendChild(pDiv);
    }

    if (pendingCount > 0) {
      const pDiv = document.createElement('div');
      pDiv.style.cssText = 'margin-top:0.5rem;font-size:0.8rem;color:var(--primary)';
      pDiv.textContent = pendingCount + ' pending proposal(s)';
      card.appendChild(pDiv);
    }

    card.addEventListener('click', () => openDetailPanel(sid));
    grid.appendChild(card);
  });
}

// --- Detail Panel ---

function openDetailPanel(sectionId) {
  state.activeSection = sectionId;
  document.getElementById('detail-panel').classList.add('panel-visible');
  document.getElementById('section-grid').classList.add('panel-open');
  renderDetailPanel();
  renderSectionGrid();
}

function closeDetailPanel() {
  state.activeSection = null;
  document.getElementById('detail-panel').classList.remove('panel-visible');
  document.getElementById('section-grid').classList.remove('panel-open');
  renderSectionGrid();
}

function renderDetailPanel() {
  const sid = state.activeSection;
  if (!sid) return;

  const s = state.currentSession;
  const meta = s.section_meta[sid];
  const template = findTemplate();
  const sectionDef = template ? template.sections.find(sec => sec.id === sid) : null;
  const content = state.sectionContent[sid] ? state.sectionContent[sid].content : '';
  const comments = state.sectionComments[sid] || [];
  const proposals = state.sectionProposals[sid] || [];
  const isOwner = canActOnSection(sid);

  document.getElementById('panel-title').textContent = sectionDef ? sectionDef.title : sid;

  const statusDiv = document.getElementById('panel-status-badge');
  statusDiv.textContent = '';
  const wrapper = document.createElement('div');
  wrapper.style.padding = '0 1.25rem 0.5rem';
  const badge = document.createElement('span');
  badge.className = 'badge badge-' + meta.status.replace(' ', '-');
  badge.textContent = meta.status;
  wrapper.appendChild(badge);
  statusDiv.appendChild(wrapper);

  document.getElementById('panel-approve-btn').style.display =
    (isOwner && meta.status !== 'approved' && meta.status !== 'skipped') ? 'inline-block' : 'none';
  document.getElementById('panel-skip-btn').style.display =
    (isOwner && sectionDef && sectionDef.priority !== 'required' && meta.status !== 'skipped' && meta.status !== 'approved') ? 'inline-block' : 'none';
  document.getElementById('panel-reopen-btn').style.display =
    (isOwner && meta.status === 'approved') ? 'inline-block' : 'none';

  // Draft
  const draftEl = document.getElementById('panel-draft');
  draftEl.textContent = '';
  const draftH4 = document.createElement('h4');
  draftH4.textContent = 'Draft';
  draftEl.appendChild(draftH4);
  const draftContent = document.createElement('div');
  draftContent.className = 'draft-content';
  if (content) {
    draftContent.innerHTML = typeof marked !== 'undefined' ? marked.parse(content) : esc(content);
  } else {
    const em = document.createElement('em');
    em.textContent = 'No content yet.';
    draftContent.appendChild(em);
  }
  draftEl.appendChild(draftContent);

  // Proposals
  const proposalsEl = document.getElementById('panel-proposals');
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

  // Comments
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
  const commentDisabled = meta.status === 'approved';
  commentInput.disabled = commentDisabled;
  commentBtn.disabled = commentDisabled;
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
    const diffContainer = document.createElement('div');
    diffContainer.className = 'proposal-diff';

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

    diffContainer.appendChild(currentLabel);
    diffContainer.appendChild(currentDiv);
    diffContainer.appendChild(proposedLabel);
    diffContainer.appendChild(proposedDiv);
    div.appendChild(diffContainer);
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

  try {
    await apiFetch('/sessions/' + state.currentSession.id + '/comments', {
      method: 'POST',
      body: JSON.stringify({
        section_id: state.activeSection,
        author: state.userId,
        text: text,
      }),
    });
    input.value = '';
  } catch (err) {
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

async function publishSession() {
  if (!confirm('Publish this session? It will become read-only.')) return;
  try {
    const result = await apiFetch('/sessions/' + state.currentSession.id + '/publish', {
      method: 'POST',
      body: JSON.stringify({
        config: { output_path: '/tmp/draftcircle-' + state.currentSession.id + '.md' },
      }),
    });
    alert('Published. Reference: ' + result.output_ref);
    await openSession(state.currentSession.id);
  } catch (err) {
    alert('Error: ' + err.message);
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

  if (msg.type === 'comment_added' && sectionId) {
    state.sectionComments[sectionId] = await apiFetch('/sessions/' + sid + '/sections/' + sectionId + '/comments');
    if (state.activeSection === sectionId) renderDetailPanel();
  } else if (msg.type === 'proposal_created' && sectionId) {
    state.sectionProposals[sectionId] = await apiFetch('/sessions/' + sid + '/sections/' + sectionId + '/proposals');
    if (state.activeSection === sectionId) renderDetailPanel();
    renderSectionGrid();
  } else if ((msg.type === 'proposal_accepted' || msg.type === 'proposal_rejected') && sectionId) {
    state.sectionProposals[sectionId] = await apiFetch('/sessions/' + sid + '/sections/' + sectionId + '/proposals');
    state.sectionContent[sectionId] = await apiFetch('/sessions/' + sid + '/sections/' + sectionId);
    if (state.activeSection === sectionId) renderDetailPanel();
    renderSectionGrid();
  } else if (msg.type === 'section_approved' || msg.type === 'section_reopened' || msg.type === 'section_skipped') {
    state.currentSession = await apiFetch(sessionPath(sid));
    updateHeader();
    renderSectionGrid();
    if (state.activeSection === sectionId) renderDetailPanel();
  } else if (msg.type === 'session_published') {
    state.currentSession = await apiFetch(sessionPath(sid));
    updateHeader();
    renderSectionGrid();
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

  document.getElementById('create-session-btn').addEventListener('click', showCreateForm);
  document.getElementById('cancel-create-btn').addEventListener('click', loadSessionList);
  document.getElementById('create-session-form').addEventListener('submit', handleCreateSession);
  document.getElementById('add-participant-btn').addEventListener('click', addParticipantRow);
  document.getElementById('panel-close-btn').addEventListener('click', closeDetailPanel);
  document.getElementById('submit-comment-btn').addEventListener('click', submitComment);
  document.getElementById('panel-approve-btn').addEventListener('click', approveSection);
  document.getElementById('panel-reopen-btn').addEventListener('click', reopenSection);
  document.getElementById('panel-skip-btn').addEventListener('click', skipSection);
  document.getElementById('publish-btn').addEventListener('click', publishSession);
  document.getElementById('close-invite-modal').addEventListener('click', () => {
    document.getElementById('invite-modal').style.display = 'none';
  });
  document.getElementById('comment-input').addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) submitComment();
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
