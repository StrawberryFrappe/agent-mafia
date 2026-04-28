/**
 * Agent Mafia Arena - WebSocket Client
 * Handles real-time game event rendering
 */

const ROLE_COLORS = {
    MAFIA: '#e74c5e',
    DOCTOR: '#4ce78a',
    SHERIFF: '#d64ce7',
    TOWN: '#4cd6e7',
    ORCHESTRATOR: '#e7c94c',
};

const PHASE_CLASSES = {
    NIGHT: 'night',
    DAY_ZERO: 'day',
    DAY_TALK: 'day',
    DAWN: 'day',
    VOTING_STEP1: 'voting',
    VOTING_STEP2: 'voting',
    TRIAL: 'trial',
    SENTENCING: 'trial',
    INIT: '',
    GAME_OVER: '',
};

// State
const players = new Map();
const graveyard = [];
const voteTally = {};
let ws = null;
let reconnectTimer = null;

// DOM refs
const logEl = document.getElementById('game-log');
const playersEl = document.getElementById('players-list');
const phaseBadge = document.getElementById('phase-badge');
const currentPhaseEl = document.getElementById('current-phase');
const graveyardEl = document.getElementById('graveyard');
const voteTallyEl = document.getElementById('vote-tally');
const votesSection = document.getElementById('votes-section');
const connDot = document.getElementById('connection-dot');
const connText = document.getElementById('connection-text');

// ---- WebSocket ----

function connect() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}/ws`);

    ws.onopen = () => {
        connDot.className = 'dot connected';
        connText.textContent = 'Connected';
        if (reconnectTimer) {
            clearTimeout(reconnectTimer);
            reconnectTimer = null;
        }
    };

    ws.onclose = () => {
        connDot.className = 'dot disconnected';
        connText.textContent = 'Disconnected';
        reconnectTimer = setTimeout(connect, 3000);
    };

    ws.onerror = () => {
        ws.close();
    };

    ws.onmessage = (evt) => {
        try {
            const event = JSON.parse(evt.data);
            handleEvent(event);
        } catch (e) {
            console.error('Failed to parse event:', e);
        }
    };
}

// ---- Event Handlers ----

function handleEvent(event) {
    switch (event.type) {
        case 'phase':
            handlePhase(event);
            break;
        case 'speak':
            handleSpeak(event);
            break;
        case 'system':
            handleSystem(event);
            break;
        case 'death':
            handleDeath(event);
            break;
        case 'vote':
            handleVote(event);
            break;
        case 'win':
            handleWin(event);
            break;
        case 'error':
            handleError(event);
            break;
    }

    // Auto-scroll
    logEl.scrollTop = logEl.scrollHeight;
}

function handlePhase(event) {
    const label = event.phase.replace(/_/g, ' ');
    const cls = PHASE_CLASSES[event.phase] || '';

    phaseBadge.textContent = label;
    phaseBadge.className = 'phase-badge ' + cls;
    currentPhaseEl.textContent = label + (event.round ? ` (Round ${event.round})` : '');

    // Phase header in log
    const entry = createLogEntry('phase-header');
    entry.textContent = label + (event.round ? ` - Round ${event.round}` : '');
    logEl.appendChild(entry);

    // Clear votes on new voting phase
    if (event.phase.startsWith('VOTING')) {
        Object.keys(voteTally).forEach(k => delete voteTally[k]);
        votesSection.classList.remove('hidden');
        renderVoteTally();
    }
}

function handleSpeak(event) {
    // Track player
    if (!players.has(event.agent)) {
        players.set(event.agent, {
            name: event.display_name,
            role: event.role,
            alive: true,
        });
        renderPlayers();
    }

    const roleClass = event.role ? event.role.toLowerCase() : '';
    const entry = createLogEntry('speak ' + roleClass);

    const color = ROLE_COLORS[event.role] || ROLE_COLORS.TOWN;

    entry.innerHTML = `
        <span class="log-time">${event.timestamp || ''}</span>
        <span class="log-speaker" style="color: ${color}">${escapeHtml(event.display_name)}</span>
        ${event.intent ? `<span class="log-intent">${event.intent}</span>` : ''}
        <span class="log-text">${escapeHtml(event.text)}</span>
    `;

    logEl.appendChild(entry);
}

function handleSystem(event) {
    const entry = createLogEntry('system');
    entry.innerHTML = `
        <span class="log-time">${event.timestamp || ''}</span>
        <span class="log-text">${escapeHtml(event.text)}</span>
    `;
    logEl.appendChild(entry);
}

function handleDeath(event) {
    // Update player state
    for (const [key, p] of players) {
        if (p.name === event.display_name) {
            p.alive = false;
            p.role = event.role; // Reveal on death
            break;
        }
    }
    renderPlayers();

    // Add to graveyard
    graveyard.push({ name: event.display_name, role: event.role, cause: event.cause });
    renderGraveyard();

    // Log entry
    const entry = createLogEntry('death');
    const color = ROLE_COLORS[event.role] || '#e8e6f0';
    entry.innerHTML = `
        <span class="log-time">${event.timestamp || ''}</span>
        <strong style="color: var(--accent-red)">DEATH</strong> -
        <strong>${escapeHtml(event.display_name)}</strong>
        has been ${escapeHtml(event.cause)}!
        They were <span style="color: ${color}">${event.role}</span>.
    `;
    logEl.appendChild(entry);
}

function handleVote(event) {
    const target = event.target || 'no one';

    // Update tally
    if (target !== 'no one') {
        voteTally[target] = (voteTally[target] || 0) + 1;
        renderVoteTally();
    }

    const entry = createLogEntry('vote');
    entry.innerHTML = `
        <span class="log-time">${event.timestamp || ''}</span>
        <strong>${escapeHtml(event.voter)}</strong> votes for
        <strong style="color: var(--accent-purple)">${escapeHtml(target)}</strong>
        ${event.justification ? `<span class="log-text" style="font-style:italic; color: var(--text-secondary)">"${escapeHtml(event.justification.substring(0, 120))}"</span>` : ''}
    `;
    logEl.appendChild(entry);
}

function handleWin(event) {
    const entry = createLogEntry('win');
    const color = event.winner === 'MAFIA' ? ROLE_COLORS.MAFIA : ROLE_COLORS.TOWN;
    entry.innerHTML = `
        <div style="color: ${color}; font-size: 24px; margin-bottom: 8px;">
            ${event.winner} WINS!
        </div>
        <div style="color: var(--text-secondary); font-size: 14px; font-family: var(--font-body);">
            ${escapeHtml(event.reason)}
        </div>
    `;
    logEl.appendChild(entry);

    // Reveal all roles
    for (const [key, p] of players) {
        // Roles revealed via death events; remaining alive players stay hidden
    }
}

function handleError(event) {
    const entry = createLogEntry('error');
    entry.innerHTML = `
        <span class="log-time">${event.timestamp || ''}</span>
        <span class="log-text">[ERROR] ${escapeHtml(event.text)}</span>
    `;
    logEl.appendChild(entry);
}

// ---- Renderers ----

function renderPlayers() {
    playersEl.innerHTML = '';

    for (const [key, p] of players) {
        const card = document.createElement('div');
        card.className = 'player-card' + (p.alive ? '' : ' dead');

        const avatarClass = p.alive ? 'alive' : 'dead-avatar';
        const initials = p.name.split(' ').map(w => w[0]).join('').substring(0, 2);
        const roleClass = p.alive ? 'role-hidden' : `role-${p.role.toLowerCase()}`;
        const roleText = p.alive ? '???' : p.role;

        card.innerHTML = `
            <div class="player-avatar ${avatarClass}">${initials}</div>
            <div>
                <div class="player-name">${escapeHtml(p.name)}</div>
                <span class="player-role ${roleClass}">${roleText}</span>
            </div>
        `;

        playersEl.appendChild(card);
    }
}

function renderGraveyard() {
    graveyardEl.innerHTML = '';
    if (graveyard.length === 0) {
        graveyardEl.innerHTML = '<div style="color: var(--text-muted); font-size: 12px;">No deaths yet</div>';
        return;
    }

    for (const g of graveyard) {
        const color = ROLE_COLORS[g.role] || '#e8e6f0';
        const el = document.createElement('div');
        el.className = 'grave-entry';
        el.innerHTML = `
            <span class="grave-skull">X</span>
            <span>${escapeHtml(g.name)}</span>
            <span style="color: ${color}; margin-left: auto; font-size: 10px;">${g.role}</span>
        `;
        graveyardEl.appendChild(el);
    }
}

function renderVoteTally() {
    voteTallyEl.innerHTML = '';

    const sorted = Object.entries(voteTally).sort((a, b) => b[1] - a[1]);

    if (sorted.length === 0) {
        voteTallyEl.innerHTML = '<div style="color: var(--text-muted); font-size: 12px;">No votes yet</div>';
        return;
    }

    for (const [target, count] of sorted) {
        const row = document.createElement('div');
        row.className = 'vote-row';
        row.innerHTML = `
            <span class="vote-target">${escapeHtml(target)}</span>
            <span class="vote-count">${count}</span>
        `;
        voteTallyEl.appendChild(row);
    }
}

// ---- Utilities ----

function createLogEntry(className) {
    const el = document.createElement('div');
    el.className = 'log-entry ' + className;
    return el;
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ---- Init ----

function setupControls() {
    const btnStart = document.getElementById('btn-start');
    const btnStop = document.getElementById('btn-stop');

    if (btnStart) {
        btnStart.addEventListener('click', async () => {
            // Reset local UI state
            players.clear();
            graveyard.length = 0;
            Object.keys(voteTally).forEach(k => delete voteTally[k]);
            logEl.innerHTML = '';
            phaseBadge.textContent = 'WAITING';
            phaseBadge.className = 'phase-badge';
            currentPhaseEl.textContent = '--';
            renderPlayers();
            renderGraveyard();
            renderVoteTally();
            
            await fetch('/api/start', { method: 'POST' });
        });
    }

    if (btnStop) {
        btnStop.addEventListener('click', async () => {
            await fetch('/api/stop', { method: 'POST' });
        });
    }
}

setupControls();
renderGraveyard();
connect();
