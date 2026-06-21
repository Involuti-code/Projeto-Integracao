const API = {
  checkout: "/api/checkout",
  estoque: "/api/estoque",
  monitor: "/api/monitor",
};

const PRODUTOS = [
  { id: "produto_A", nome: "Produto A", estoque: 10, preco: 29.9 },
  { id: "produto_B", nome: "Produto B", estoque: 5, preco: 49.9 },
  { id: "produto_C", nome: "Produto C", estoque: 0, preco: 19.9 },
];

const CENARIOS = {
  sucesso: {
    id_pedido: () => `pedido-${Date.now()}`,
    cliente: "maria@email.com",
    itens: [
      { produto_id: "produto_A", quantidade: 2 },
      { produto_id: "produto_B", quantidade: 1 },
    ],
  },
  insuficiente: {
    id_pedido: () => `pedido-insuf-${Date.now()}`,
    cliente: "joao@email.com",
    itens: [{ produto_id: "produto_B", quantidade: 999 }],
  },
  zerado: {
    id_pedido: () => `pedido-zero-${Date.now()}`,
    cliente: "ana@email.com",
    itens: [{ produto_id: "produto_C", quantidade: 1 }],
  },
  invalido: {
    id_pedido: () => `pedido-inv-${Date.now()}`,
    cliente: "teste@email.com",
    itens: [{ produto_id: "produto_X", quantidade: 1 }],
  },
};

const logOutput = document.getElementById("log-output");
const serviceLogsEl = document.getElementById("service-logs");
const sseStatusEl = document.getElementById("sse-status");
const itensContainer = document.getElementById("itens-container");
const itemTemplate = document.getElementById("item-row-template");

let logFilter = "todos";
let eventSource = null;
let reconnectTimer = null;
let pollTimer = null;
const knownEventKeys = new Set();

function produtoLabel(id) {
  const p = PRODUTOS.find((x) => x.id === id);
  if (!p) return id;
  return `${p.nome} — R$ ${p.preco.toFixed(2)} (estoque: ${p.estoque})`;
}

function fillProdutoSelect(select) {
  select.innerHTML = "";
  PRODUTOS.forEach((p) => {
    const opt = document.createElement("option");
    opt.value = p.id;
    opt.textContent = produtoLabel(p.id);
    select.appendChild(opt);
  });
}

function addItemRow(produtoId = "produto_A", quantidade = 1) {
  const clone = itemTemplate.content.cloneNode(true);
  const row = clone.querySelector(".item-row");
  const select = row.querySelector(".item-produto");
  const input = row.querySelector(".item-quantidade");

  fillProdutoSelect(select);
  select.value = produtoId;
  input.value = quantidade;

  row.querySelector(".btn-remove-item").addEventListener("click", () => {
    if (itensContainer.children.length > 1) {
      row.remove();
    }
  });

  itensContainer.appendChild(row);
}

function getItensFromForm() {
  return Array.from(itensContainer.querySelectorAll(".item-row")).map((row) => ({
    produto_id: row.querySelector(".item-produto").value,
    quantidade: parseInt(row.querySelector(".item-quantidade").value, 10),
  }));
}

function clearLog() {
  logOutput.innerHTML = '<p class="log-placeholder">As respostas das requisições aparecerão aqui.</p>';
}

function appendLog(method, url, status, body) {
  const placeholder = logOutput.querySelector(".log-placeholder");
  if (placeholder) placeholder.remove();

  const entry = document.createElement("div");
  entry.className = "log-entry";

  const statusClass = status >= 200 && status < 300 ? "log-status-ok" : "log-status-error";
  const time = new Date().toLocaleTimeString("pt-BR");

  entry.innerHTML = `
    <div class="log-meta">
      <span class="log-method">${method}</span>
      <span>${url}</span>
      <span class="${statusClass}">${status}</span>
      <span class="log-time">${time}</span>
    </div>
    <pre class="log-body">${escapeHtml(JSON.stringify(body, null, 2))}</pre>
  `;

  logOutput.prepend(entry);
}

function escapeHtml(str) {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

async function apiRequest(method, url, body) {
  const options = { method, headers: {} };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }

  const response = await fetch(url, options);
  let data;
  const text = await response.text();
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { raw: text };
  }

  appendLog(method, url, response.status, data);
  return { ok: response.ok, status: response.status, data };
}

async function criarPedido(pedido) {
  return apiRequest("POST", `${API.checkout}/pedidos`, pedido);
}

async function verificarEstoque(produtoId, quantidade) {
  const url = `${API.estoque}/produtos/${encodeURIComponent(produtoId)}/disponibilidade?quantidade=${quantidade}`;
  return apiRequest("GET", url);
}

async function simularFalha(ativo) {
  const url = `${API.estoque}/admin/simular-falha?ativo=${ativo}`;
  return apiRequest("POST", url);
}

async function circuitBreakerStatus() {
  return apiRequest("GET", `${API.checkout}/health/circuit-breaker`);
}

function switchPanel(panelId) {
  document.querySelectorAll(".nav-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.panel === panelId);
  });
  document.querySelectorAll(".panel").forEach((panel) => {
    panel.classList.toggle("active", panel.id === `panel-${panelId}`);
  });
}

function renderCbStatus(data) {
  const box = document.getElementById("cb-status");
  const estado = data.estado || "desconhecido";
  const cores = { closed: "var(--success)", open: "var(--danger)", half_open: "var(--warning)" };
  box.innerHTML = `
    <div style="margin-bottom:0.5rem">
      Estado: <strong style="color:${cores[estado] || "inherit"}">${estado.toUpperCase()}</strong>
    </div>
    Falhas consecutivas: ${data.falhas_consecutivas} / ${data.limite_falhas}
    Recuperação: ${data.tempo_recuperacao_segundos}s
  `;
  box.classList.remove("muted");
}

async function checkServices() {
  const pills = document.getElementById("status-pills");
  const checks = [
    { name: "Checkout", url: `${API.checkout}/` },
    { name: "Estoque", url: `${API.estoque}/` },
    { name: "Monitor", url: `${API.monitor}/` },
  ];

  const results = await Promise.all(
    checks.map(async (c) => {
      try {
        const res = await fetch(c.url);
        return { name: c.name, ok: res.ok };
      } catch {
        return { name: c.name, ok: false };
      }
    })
  );

  pills.innerHTML = results
    .map((r) => `<span class="pill ${r.ok ? "pill-ok" : "pill-error"}">${r.name}: ${r.ok ? "online" : "offline"}</span>`)
    .join("");
}

function generatePedidoId() {
  document.getElementById("id-pedido").value = `pedido-${Date.now()}`;
}

function formatEventTime(iso) {
  try {
    return new Date(iso).toLocaleTimeString("pt-BR");
  } catch {
    return "--:--:--";
  }
}

function shouldShowEvent(evento) {
  if (logFilter === "todos") return true;
  return evento.servico === logFilter;
}

function renderServiceLogEntry(evento) {
  const entry = document.createElement("div");
  entry.className = `service-log-entry servico-${evento.servico} nivel-${evento.nivel || "info"}`;
  if (!shouldShowEvent(evento)) entry.classList.add("hidden");

  const metaParts = [];
  if (evento.id_pedido) metaParts.push(`Pedido: ${evento.id_pedido}`);
  if (evento.detalhes && Object.keys(evento.detalhes).length > 0) {
    metaParts.push(JSON.stringify(evento.detalhes));
  }

  entry.innerHTML = `
    <span class="service-log-time">${formatEventTime(evento.timestamp)}</span>
    <span class="service-badge ${evento.servico}">${evento.servico}</span>
    <div class="service-log-body">
      <div class="service-log-message">${escapeHtml(evento.mensagem)}</div>
      ${metaParts.length ? `<div class="service-log-meta">${escapeHtml(metaParts.join(" · "))}</div>` : ""}
    </div>
  `;
  return entry;
}

function appendServiceLog(evento, scroll = true) {
  const placeholder = serviceLogsEl.querySelector(".log-placeholder");
  if (placeholder) placeholder.remove();

  serviceLogsEl.appendChild(renderServiceLogEntry(evento));

  const autoscroll = document.getElementById("logs-autoscroll").checked;
  if (scroll && autoscroll) {
    serviceLogsEl.scrollTop = serviceLogsEl.scrollHeight;
  }
}

function applyLogFilter() {
  serviceLogsEl.querySelectorAll(".service-log-entry").forEach((entry) => {
    const servico = entry.className.match(/servico-(\w+)/)?.[1];
    const visible = logFilter === "todos" || servico === logFilter;
    entry.classList.toggle("hidden", !visible);
  });
}

function clearServiceLogs() {
  knownEventKeys.clear();
  serviceLogsEl.innerHTML = '<p class="log-placeholder">Aguardando eventos dos serviços… Envie um pedido para ver a atividade.</p>';
}

function setSseStatus(state) {
  const labels = {
    connecting: "Conectando…",
    live: "Ao vivo",
    polling: "Atualizando",
    offline: "Monitor offline",
  };
  sseStatusEl.textContent = labels[state] || labels.offline;
  sseStatusEl.className = `sse-status ${state === "offline" ? "disconnected" : "connected"}`;
}

function eventKey(evento) {
  return `${evento.timestamp}|${evento.servico}|${evento.mensagem}|${evento.id_pedido || ""}`;
}

function ingestEvents(eventos, scroll = true) {
  if (!eventos || eventos.length === 0) return false;

  let hasNew = false;
  for (const evento of eventos) {
    const key = eventKey(evento);
    if (knownEventKeys.has(key)) continue;
    knownEventKeys.add(key);
    appendServiceLog(evento, false);
    hasNew = true;
  }

  if (hasNew && scroll) {
    const autoscroll = document.getElementById("logs-autoscroll").checked;
    if (autoscroll) {
      serviceLogsEl.scrollTop = serviceLogsEl.scrollHeight;
    }
  }

  return hasNew;
}

async function pollEvents() {
  try {
    const res = await fetch(`${API.monitor}/eventos?limit=100`);
    if (!res.ok) {
      setSseStatus("offline");
      return false;
    }
    const data = await res.json();
    const hasNew = ingestEvents(data.eventos || []);
    setSseStatus(eventSource ? "live" : "polling");
    return hasNew;
  } catch {
    setSseStatus("offline");
    return false;
  }
}

function startPolling() {
  if (pollTimer) return;
  pollEvents();
  pollTimer = setInterval(pollEvents, 2000);
}

async function loadExistingEvents() {
  setSseStatus("connecting");
  const loaded = await pollEvents();
  if (!loaded) {
    const placeholder = serviceLogsEl.querySelector(".log-placeholder");
    if (placeholder) {
      placeholder.textContent = "Aguardando eventos dos serviços… Envie um pedido para ver a atividade.";
    }
  }
}

function connectEventStream() {
  if (eventSource) {
    eventSource.close();
    eventSource = null;
  }

  setSseStatus("connecting");
  eventSource = new EventSource(`${API.monitor}/eventos/stream`);

  eventSource.onopen = () => setSseStatus("live");

  eventSource.onmessage = (msg) => {
    if (!msg.data || msg.data.startsWith(":")) return;
    try {
      const evento = JSON.parse(msg.data);
      ingestEvents([evento]);
      setSseStatus("live");
    } catch {
      // ignore malformed events
    }
  };

  eventSource.onerror = () => {
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
    setSseStatus("polling");
    clearTimeout(reconnectTimer);
    reconnectTimer = setTimeout(connectEventStream, 10000);
  };
}

document.querySelectorAll(".nav-btn").forEach((btn) => {
  btn.addEventListener("click", () => switchPanel(btn.dataset.panel));
});

document.getElementById("btn-add-item").addEventListener("click", () => addItemRow());

document.getElementById("form-pedido").addEventListener("submit", async (e) => {
  e.preventDefault();
  const pedido = {
    id_pedido: document.getElementById("id-pedido").value.trim(),
    cliente: document.getElementById("cliente").value.trim(),
    itens: getItensFromForm(),
  };
  await criarPedido(pedido);
});

document.getElementById("form-estoque").addEventListener("submit", async (e) => {
  e.preventDefault();
  const produtoId = document.getElementById("estoque-produto").value;
  const quantidade = parseInt(document.getElementById("estoque-quantidade").value, 10);
  await verificarEstoque(produtoId, quantidade);
});

document.getElementById("btn-falha-on").addEventListener("click", () => simularFalha(true));
document.getElementById("btn-falha-off").addEventListener("click", () => simularFalha(false));

document.getElementById("btn-cb-status").addEventListener("click", async () => {
  const result = await circuitBreakerStatus();
  if (result.ok) renderCbStatus(result.data);
});

document.getElementById("btn-clear-log").addEventListener("click", clearLog);

document.getElementById("btn-clear-service-logs").addEventListener("click", clearServiceLogs);

document.querySelectorAll("#log-filter-chips .chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    document.querySelectorAll("#log-filter-chips .chip").forEach((c) => c.classList.remove("active"));
    chip.classList.add("active");
    logFilter = chip.dataset.filter;
    applyLogFilter();
  });
});

document.querySelectorAll(".scenario-card").forEach((card) => {
  card.querySelector(".btn-scenario").addEventListener("click", async () => {
    const key = card.dataset.scenario;
    const cenario = CENARIOS[key];
    const pedido = {
      id_pedido: typeof cenario.id_pedido === "function" ? cenario.id_pedido() : cenario.id_pedido,
      cliente: cenario.cliente,
      itens: cenario.itens,
    };
    await criarPedido(pedido);
  });
});

fillProdutoSelect(document.getElementById("estoque-produto"));
addItemRow("produto_A", 2);
addItemRow("produto_B", 1);
generatePedidoId();
checkServices();
setInterval(checkServices, 30000);
loadExistingEvents();
startPolling();
connectEventStream();
