// ---------- UI helpers ----------
function showScreen(id) {
  document.querySelectorAll(".screen").forEach(s => s.classList.remove("active"));
  document.getElementById(id).classList.add("active");
}

function qs(id) { return document.getElementById(id); }

function setText(id, text) { qs(id).textContent = text; }

function clearJoinError() { setText("join-error", ""); }

// ---------- State ----------
const state = {
  ws: null,
  playerId: null,
  room: null,
  isHost: false,
  question: null,
  timer: null,
  timeLeft: 0,
  answered: false,
};

// ---------- WS ----------
function wsUrl() {
  // Se você estiver no Codespaces com porta 8000 exposta, a URL do backend
  // costuma ser o mesmo host do browser. Vamos montar dinamicamente:
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const host = location.host;
  return `${protocol}://${host}/ws`;
}

function setWsStatus(text) {
  setText("ws-status", text);
}

function connectWS() {
  if (state.ws && (state.ws.readyState === WebSocket.OPEN || state.ws.readyState === WebSocket.CONNECTING)) {
    return;
  }

  setWsStatus("Conectando...");
  const url = wsUrl();
  const ws = new WebSocket(url);
  state.ws = ws;

  ws.onopen = () => setWsStatus("Conectado");
  ws.onclose = () => setWsStatus("Desconectado");
  ws.onerror = () => setWsStatus("Erro");

  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);

    if (msg.type === "room_joined" && msg.payload?.playerId) {
      // handshake: server informa playerId
      state.playerId = msg.payload.playerId;
      return;
    }

    if (msg.type === "room_created") {
      state.room = msg.payload.room;
      state.isHost = true;
      renderRoomState(state.room);
      showScreen("screen-lobby");
      return;
    }

    if (msg.type === "room_joined" && msg.payload?.room) {
      state.room = msg.payload.room;
      // isHost será atualizado pelo room_state subsequente
      renderRoomState(state.room);
      showScreen("screen-lobby");
      return;
    }

    if (msg.type === "room_state") {
      if (msg.payload?.left) {
        resetRoom();
        return;
      }
      state.room = msg.payload;
      state.isHost = !!state.room.players?.find(p => p.id === state.playerId)?.isHost;
      renderRoomState(state.room);
      return;
    }

    if (msg.type === "game_started") {
      showScreen("screen-game");
      return;
    }

    if (msg.type === "error") {
      // erros de entrar geralmente
      setText("join-error", msg.payload?.message || "Erro");
      return;
    }
        if (msg.type === "question") {
      state.question = msg.payload;
      state.answered = false;
      renderQuestion(msg.payload);
      return;
    }

    if (msg.type === "answer_result") {
      const correct = msg.payload.correct;
      const gained = msg.payload.gained;
      const correctIndex = msg.payload.correctIndex;
      setText("answer-feedback", correct ? `Correto! +${gained} pontos.` : `Errado. Resposta correta: ${String.fromCharCode(65 + correctIndex)}.`);
      lockOptions();
      return;
    }

    if (msg.type === "scoreboard") {
      renderScoreboard(msg.payload.players || []);
      return;
    }

    if (msg.type === "round_ended") {
      // apenas informativo no MVP
      return;
    }

  };
}

function send(action, payload = {}) {
  connectWS();
  if (!state.ws || state.ws.readyState !== WebSocket.OPEN) {
    // pequena tolerância: tenta em 200ms
    setTimeout(() => send(action, payload), 200);
    return;
  }
  state.ws.send(JSON.stringify({ action, payload }));
}

// ---------- Render ----------
function renderRoomState(room) {
  if (!room) return;

  setText("current-pin", room.pin || "—");
  setText("current-count", String(room.count ?? 0));

  const ul = qs("players-list");
  ul.innerHTML = "";

  (room.players || []).forEach(p => {
    const li = document.createElement("li");
    li.innerHTML = `<span>${escapeHtml(p.name)} ${p.isHost ? "<em>(Host)</em>" : ""}</span><span>${p.id === state.playerId ? "Você" : ""}</span>`;
    ul.appendChild(li);
  });

  // Pin criado
  if (room.pin) {
    setText("created-pin", state.isHost ? `Sala criada. PIN: ${room.pin}` : "");
  }

  qs("btn-start-game").disabled = !(state.isHost && !room.started);
  qs("btn-leave-room").disabled = !room.pin;

  setText("host-info", state.isHost ? "Você é o host. Inicie quando estiver pronto." : "Aguarde o host iniciar.");
}

function resetRoom() {
  state.room = null;
  state.isHost = false;
  setText("current-pin", "—");
  setText("current-count", "0");
  qs("players-list").innerHTML = "";
  qs("btn-start-game").disabled = true;
  qs("btn-leave-room").disabled = true;
  setText("created-pin", "");
  setText("host-info", "");
}

function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, (m) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  }[m]));
}

// ---------- UI events ----------
qs("btn-go-lobby").addEventListener("click", () => {
  showScreen("screen-lobby");
  connectWS();
});

qs("btn-create-room").addEventListener("click", () => {
  clearJoinError();
  const name = qs("host-name").value.trim();
  send("create_room", { name });
});

qs("btn-join-room").addEventListener("click", () => {
  clearJoinError();
  const name = qs("player-name").value.trim();
  const pin = qs("room-pin").value.trim();
  send("join_room", { name, pin });
});

qs("btn-start-game").addEventListener("click", () => {
  send("start_game", {});
});

qs("btn-leave-room").addEventListener("click", () => {
  send("leave_room", {});
  resetRoom();
});

qs("btn-go-finish").addEventListener("click", () => showScreen("screen-finish"));
qs("btn-restart").addEventListener("click", () => {
  resetRoom();
  showScreen("screen-home");
});
function renderQuestion(q) {
  setText("game-meta", `Responda antes do tempo acabar.`);
  setText("q-difficulty", q.difficulty);
  setText("answer-feedback", "");
  buildOptions(q.options);

  // timer
  state.timeLeft = q.duration;
  setText("q-timer", String(state.timeLeft));
  if (state.timer) clearInterval(state.timer);
  state.timer = setInterval(() => {
    state.timeLeft -= 1;
    setText("q-timer", String(Math.max(0, state.timeLeft)));
    if (state.timeLeft <= 0) {
      clearInterval(state.timer);
      lockOptions();
      setText("answer-feedback", state.answered ? qs("answer-feedback").textContent : "Tempo esgotado.");
    }
  }, 1000);

  setText("q-text", q.question);
}

function buildOptions(options) {
  const container = qs("q-options");
  container.innerHTML = "";
  options.forEach((text, idx) => {
    const btn = document.createElement("button");
    btn.className = "option-btn";
    btn.textContent = `${String.fromCharCode(65 + idx)}) ${text}`;
    btn.onclick = () => {
      if (state.answered) return;
      state.answered = true;
      send("answer", { optionIndex: idx });
      lockOptions();
    };
    container.appendChild(btn);
  });
}

function lockOptions() {
  const container = qs("q-options");
  container.querySelectorAll("button").forEach(b => b.disabled = true);
}

function renderScoreboard(players) {
  const ul = qs("score-list");
  ul.innerHTML = "";
  players.forEach(p => {
    const li = document.createElement("li");
    li.innerHTML = `<span>${escapeHtml(p.name)} ${p.isHost ? "<em>(Host)</em>" : ""}</span><span>${p.score}</span>`;
    ul.appendChild(li);
  });
}


// Conectar já na abertura do lobby se usuário for direto
connectWS();
