/* game.js — OneMoreTurn Phase 6 frontend
 *
 * State: one plain object holds everything the UI needs.
 * Rendering: pure SVG for the map; DOM manipulation elsewhere.
 * All API calls go through the fetch() wrappers at the bottom.
 *
 * Security note: all dynamic text is inserted via .textContent
 * or explicit attribute sets — never via innerHTML with user data.
 */

"use strict";

// ---------------------------------------------------------------------------
// Application state
// ---------------------------------------------------------------------------

const state = {
  games:          [],   // list[{id, name, turn, players}]
  gameId:         null, // currently selected game id
  playerName:     null, // currently active player name
  gameState:      null, // last export_game_state() response
  selectedFleet:  null, // fleet object currently selected on the map
};

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", () => {
  loadGames();

  document.getElementById("ng-create").addEventListener("click", onCreateGame);
  document.getElementById("player-select").addEventListener("change", onPlayerChange);
  document.getElementById("resolve-btn").addEventListener("click", onResolveTurn);
  document.getElementById("submit-move").addEventListener("click", onSubmitMove);
});

// ---------------------------------------------------------------------------
// Event handlers
// ---------------------------------------------------------------------------

async function onCreateGame() {
  const name    = document.getElementById("ng-name").value.trim();
  const player1 = document.getElementById("ng-player1").value.trim() || "Player1";
  const player2 = document.getElementById("ng-player2").value.trim() || "Player2";
  const fb      = document.getElementById("ng-feedback");

  if (!name) { setFeedback(fb, "Game name is required.", "err"); return; }

  const resp = await apiPost("/api/games", { name, player1, player2 });
  if (resp.error) { setFeedback(fb, resp.error, "err"); return; }

  setFeedback(fb, `Created "${resp.game_id}".`, "ok");
  document.getElementById("ng-name").value = "";
  await loadGames();
}

async function onPlayerChange() {
  const player = document.getElementById("player-select").value;
  if (player) await selectGame(state.gameId, player);
}

async function onResolveTurn() {
  const fb = document.getElementById("map-feedback");
  const resp = await apiPost(`/api/game/${state.gameId}/resolve`, {});
  if (resp.error) { setFeedback(fb, resp.error, "err"); return; }
  setFeedback(fb, `Turn ${resp.turn} started. ${resp.event_count} events.`, "ok");
  await selectGame(state.gameId, state.playerName);
}

async function onSubmitMove() {
  const dest = document.getElementById("dest-select").value;
  const fb   = document.getElementById("action-feedback");
  if (!state.selectedFleet || !dest) {
    setFeedback(fb, "Select a fleet and a destination.", "err");
    return;
  }

  const resp = await apiPost(`/api/game/${state.gameId}/orders`, {
    player:      state.playerName,
    action_type: "MoveFleet",
    action_data: { fleet: state.selectedFleet.name, target: dest },
  });

  if (resp.error) { setFeedback(fb, resp.error, "err"); return; }
  if (!resp.valid) {
    setFeedback(fb, resp.errors.join("; "), "err");
    return;
  }
  setFeedback(fb, "Move order queued.", "ok");
  clearSelection();
}

// ---------------------------------------------------------------------------
// loadGames — reload sidebar game list
// ---------------------------------------------------------------------------

async function loadGames() {
  const games = await apiFetch("/api/games");
  state.games = Array.isArray(games) ? games : [];
  renderGameList();
}

// ---------------------------------------------------------------------------
// selectGame — load state for one player and refresh the whole UI
// ---------------------------------------------------------------------------

async function selectGame(gameId, playerName) {
  state.gameId    = gameId;
  state.playerName = playerName;

  const gs = await apiFetch(`/api/game/${gameId}/state?player=${encodeURIComponent(playerName)}`);
  if (gs.error) {
    document.getElementById("map-feedback").textContent = gs.error;
    return;
  }
  state.gameState = gs;
  state.selectedFleet = null;

  renderTurnLabel();
  renderPlayerPanel();
  renderMap();
  renderPlayerSelect();
  renderEvents();

  document.getElementById("resolve-btn").classList.remove("hidden");
  document.getElementById("player-select").classList.remove("hidden");
  document.getElementById("action-form").classList.add("hidden");
  document.getElementById("map-feedback").textContent = "";
  renderGameList(); // refresh turn counts
}

// ---------------------------------------------------------------------------
// Renderers
// ---------------------------------------------------------------------------

function renderGameList() {
  const ul = document.getElementById("game-list");
  ul.innerHTML = "";
  for (const g of state.games) {
    const li = document.createElement("li");
    if (g.id === state.gameId) li.classList.add("active");

    const nameSpan = document.createElement("span");
    nameSpan.textContent = g.name;

    const turnSpan = document.createElement("span");
    turnSpan.className = "game-turn";
    turnSpan.textContent = `T${g.turn}`;

    li.appendChild(nameSpan);
    li.appendChild(turnSpan);
    li.addEventListener("click", () => openGamePicker(g));
    ul.appendChild(li);
  }
}

function openGamePicker(game) {
  // If there are players on the game, default to the first
  const player = game.players && game.players.length > 0 ? game.players[0] : null;
  if (player) selectGame(game.id, player);
}

function renderPlayerSelect() {
  const gs  = state.gameState;
  const sel = document.getElementById("player-select");
  // Collect player names from own fleets + planets ownership
  // The server already tells us the current player; build list from games list
  const game = state.games.find(g => g.id === state.gameId);
  const players = game ? game.players : [gs.player_name];

  sel.innerHTML = "";
  for (const p of players) {
    const opt = document.createElement("option");
    opt.value = p;
    opt.textContent = p;
    if (p === state.playerName) opt.selected = true;
    sel.appendChild(opt);
  }
}

function renderTurnLabel() {
  const gs = state.gameState;
  document.getElementById("turn-label").textContent =
    `${gs.game_id}  ·  Turn ${gs.turn}  ·  ${gs.player_name}`;
}

function renderPlayerPanel() {
  const gs   = state.gameState;
  const panel = document.getElementById("player-panel");
  panel.classList.remove("hidden");

  document.getElementById("player-name-label").textContent = gs.player_name;

  // Aggregate resources across own fleets + planets
  const totals = {};
  for (const f of gs.fleets)  mergeResources(totals, f.resources);
  for (const p of gs.planets) mergeResources(totals, p.resources);

  const resDiv = document.getElementById("player-resources");
  resDiv.innerHTML = "";
  for (const [k, v] of Object.entries(totals)) {
    const sp = document.createElement("span");
    sp.textContent = `${k}: ${Math.round(v)}`;
    resDiv.appendChild(sp);
  }

  // Planet list
  const plDiv = document.getElementById("planet-list");
  plDiv.innerHTML = "";
  for (const p of gs.planets) {
    const row = document.createElement("p");
    const bold = document.createElement("strong");
    bold.textContent = p.name;
    row.appendChild(bold);
    row.appendChild(document.createTextNode(
      `  pop ${p.population}  |  ${Object.entries(p.resources).map(([k,v]) => `${k}:${Math.round(v)}`).join(" ")}`,
    ));
    plDiv.appendChild(row);
  }
}

// ---------------------------------------------------------------------------
// drawMap — SVG rendering
// NOTE: iterates ONLY the typed arrays from the server response.
//       There is no generic "render every entity" path, so a hypothetical
//       JSON leak for out-of-range entities would not produce any SVG output.
// ---------------------------------------------------------------------------

function renderMap() {
  const gs = state.gameState;

  clearSvgGroup("map-systems");
  clearSvgGroup("map-fleets");
  clearSvgGroup("map-visible");

  // -- Star systems --------------------------------------------------------
  const sysG = document.getElementById("map-systems");
  for (const sys of gs.star_systems) {
    const g = svgEl("g");

    const circle = svgEl("circle");
    circle.setAttribute("cx", sys.position_x);
    circle.setAttribute("cy", sys.position_y);
    circle.setAttribute("r", "1.8");
    circle.setAttribute("class", "sys-circle");
    circle.dataset.sysId = sys.id;

    const label = svgEl("text");
    label.setAttribute("x", sys.position_x);
    label.setAttribute("y", sys.position_y - 2.4);
    label.setAttribute("class", "sys-label");
    label.textContent = sys.name;

    g.appendChild(circle);
    g.appendChild(label);
    sysG.appendChild(g);
  }

  // -- Own fleets ----------------------------------------------------------
  const fleetG = document.getElementById("map-fleets");
  for (const fleet of gs.fleets) {
    const tri = makeFleetTriangle(fleet.position_x, fleet.position_y, "fleet-own");
    tri.dataset.fleetId = fleet.id;
    if (state.selectedFleet && state.selectedFleet.id === fleet.id) {
      tri.classList.add("selected-fleet");
    }
    tri.addEventListener("click", () => selectFleet(fleet));

    const label = svgEl("text");
    label.setAttribute("x", fleet.position_x);
    label.setAttribute("y", fleet.position_y + 3.2);
    label.setAttribute("class", "fleet-label");
    label.textContent = fleet.name;

    fleetG.appendChild(tri);
    fleetG.appendChild(label);
  }

  // -- Visible entities (other players, fog-of-war filtered) ---------------
  // Only entries the server explicitly returned are rendered here.
  const visG = document.getElementById("map-visible");
  for (const ent of gs.visible_entities) {
    const cls = ent.stale ? "fleet-stale" : "fleet-foe";
    const tri = makeFleetTriangle(ent.position_x, ent.position_y, cls);

    const label = svgEl("text");
    label.setAttribute("x", ent.position_x);
    label.setAttribute("y", ent.position_y + 3.2);
    label.setAttribute("class", "fleet-label");
    label.textContent = ent.stale ? `${ent.name} [?]` : ent.name;

    visG.appendChild(tri);
    visG.appendChild(label);
  }
}

function renderEvents() {
  const gs  = state.gameState;
  const ul  = document.getElementById("event-list");
  ul.innerHTML = "";
  if (!gs.events || gs.events.length === 0) {
    const li = document.createElement("li");
    li.className = "muted";
    li.textContent = "No events this turn.";
    ul.appendChild(li);
    return;
  }
  for (const ev of gs.events.slice(-10)) {  // show last 10
    const li   = document.createElement("li");
    const bold = document.createElement("strong");
    bold.textContent = ev.type;
    li.appendChild(bold);
    li.appendChild(document.createTextNode(`  ${ev.description}`));
    ul.appendChild(li);
  }
}

// ---------------------------------------------------------------------------
// Fleet selection
// ---------------------------------------------------------------------------

function selectFleet(fleet) {
  state.selectedFleet = fleet;

  const detailDiv = document.getElementById("selection-detail");
  detailDiv.textContent =
    `${fleet.name}  ·  speed ${fleet.speed}` +
    (fleet.turns_remaining > 0
      ? `  →  ${fleet.destination_name} (${fleet.turns_remaining} turns)`
      : `  ·  at ${fleet.system_name || "transit"}`);

  // Populate destination picker from star_systems list
  const sel = document.getElementById("dest-select");
  sel.innerHTML = "";
  for (const sys of state.gameState.star_systems) {
    const opt = document.createElement("option");
    opt.value = sys.name;
    opt.textContent = sys.name;
    if (sys.id === fleet.system_id) opt.disabled = true; // can't move to current system
    sel.appendChild(opt);
  }

  document.getElementById("action-form").classList.remove("hidden");
  document.getElementById("action-feedback").textContent = "";

  // Redraw map to highlight selected fleet
  renderMap();
}

function clearSelection() {
  state.selectedFleet = null;
  document.getElementById("action-form").classList.add("hidden");
  document.getElementById("selection-detail").textContent = "Click a fleet to act.";
  renderMap();
}

// ---------------------------------------------------------------------------
// SVG helpers
// ---------------------------------------------------------------------------

function svgEl(tag) {
  return document.createElementNS("http://www.w3.org/2000/svg", tag);
}

function clearSvgGroup(id) {
  const g = document.getElementById(id);
  while (g.firstChild) g.removeChild(g.firstChild);
}

function makeFleetTriangle(cx, cy, cls) {
  const size = 1.4;
  const pts  = `${cx},${cy - size} ${cx - size},${cy + size} ${cx + size},${cy + size}`;
  const tri  = svgEl("polygon");
  tri.setAttribute("points", pts);
  tri.setAttribute("class", cls);
  return tri;
}

// ---------------------------------------------------------------------------
// Utility
// ---------------------------------------------------------------------------

function mergeResources(totals, amounts) {
  for (const [k, v] of Object.entries(amounts || {})) {
    totals[k] = (totals[k] || 0) + v;
  }
}

function setFeedback(el, msg, type) {
  el.textContent = msg;
  el.className = `feedback ${type}`;
}

// ---------------------------------------------------------------------------
// API fetch wrappers
// ---------------------------------------------------------------------------

async function apiFetch(url) {
  try {
    const resp = await fetch(url);
    return await resp.json();
  } catch (e) {
    return { error: String(e) };
  }
}

async function apiPost(url, body) {
  try {
    const resp = await fetch(url, {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify(body),
    });
    return await resp.json();
  } catch (e) {
    return { error: String(e) };
  }
}
