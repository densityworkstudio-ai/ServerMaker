const $ = (id) => document.getElementById(id);
const AIKAR_FLAGS = "-XX:+UnlockExperimentalVMOptions -XX:+DisableExplicitGC -XX:+AlwaysPreTouch -XX:G1NewSizePercent=30 -XX:G1MaxNewSizePercent=40 -XX:G1HeapRegionSize=8M -XX:G1ReservePercent=20 -XX:G1HeapWastePercent=5 -XX:G1MixedGCCountTarget=4 -XX:InitiatingHeapOccupancyPercent=15 -XX:G1MixedGCLiveThresholdPercent=90 -XX:G1RSetUpdatingPauseTimePercent=5 -XX:SurvivorRatio=32 -XX:+PerfDisableSharedMem -XX:MaxTenuringThreshold=1";
const JVM_PRESETS = [["Clear", ""], ["Aikar tuned G1", AIKAR_FLAGS]];
const QUICK_COMMANDS = [
  ["List players", "list"], ["Save world", "save-all flush"], ["TPS", "tps"],
  ["Clear weather", "weather clear"], ["Day", "time set day"], ["Night", "time set night"],
  ["Keep inventory", "gamerule keepInventory true"], ["Whitelist", "whitelist list"],
];
const SAVE_PAYLOADS = {
  memory: () => ({ memory_mb: Number($("memory").value) }),
  memoryRestart: () => ({ memory_mb: Number($("memory").value), restart_now: true }),
  jvm: () => ({ jvm_args: $("jvmArgs").value }),
  jvmRestart: () => ({ jvm_args: $("jvmArgs").value, restart_now: true }),
  keepOnline: () => ({ auto_start: $("autoStart").checked, restart_delay_seconds: Number($("restartDelay").value) }),
};

const state = {
  settingsLoaded: false,
  consoleId: 0,
  currentPath: "",
  editingPath: "",
  schema: [],
  savedProps: {},
};

function esc(value) {
  return String(value).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error(`Unexpected response from the panel (${response.status}).`);
  }
  if (!response.ok) throw new Error(data.error || response.statusText);
  return data;
}

let toastTimer;
function toast(text, ok = true) {
  const box = $("toast");
  box.textContent = text;
  box.className = `toast show ${ok ? "ok" : "error"}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { box.className = "toast"; }, 4500);
}

function setLive(online, text) {
  $("livePill").querySelector(".dot").className = `dot ${online ? "on" : "warn"}`;
  $("livePillText").textContent = text;
}

function setTab(name) {
  document.querySelectorAll(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.tab === name));
  document.querySelectorAll(".view").forEach((view) => view.classList.toggle("active", view.id === `view-${name}`));
  if (name === "activity") loadActivity();
  if (name === "files") loadFiles(state.currentPath);
  if (name === "plugins") loadPlugins();
  if (name === "backups") loadBackups();
}

function renderStatus(data) {
  const server = data.server;
  const game = data.game;
  const settings = data.settings;
  const info = data.public;

  $("gameState").innerHTML = game.online ? '<span class="good">Online</span>' : '<span class="bad">Offline</span>';
  $("players").textContent = `${game.online_players} / ${game.max_players}`;
  $("ram").textContent = `${server.ram_mb.toLocaleString()} / ${settings.memory_mb.toLocaleString()} MiB`;
  $("cpu").textContent = `${server.cpu_percent.toFixed(1)}%`;
  $("powerText").textContent = server.running
    ? (game.online ? "Running and accepting players." : "Starting up. Waiting for the server to respond.")
    : (server.next_restart ? "Stopped. Restarting automatically soon." : "Stopped.");
  document.querySelector('[data-power="start"]').disabled = server.running;
  document.querySelector('[data-power="stop"]').disabled = !server.running;
  document.querySelector('[data-power="restart"]').disabled = !server.running;
  $("playerList").textContent = game.players.length
    ? game.players.join(", ")
    : (game.online ? "No players online." : "Server is offline.");

  if (info.address) {
    $("publicInfo").innerHTML = `<strong class="good">${esc(info.address)}</strong><div class="button-row"><button class="btn ghost" data-copy="${esc(info.address)}">Copy address</button></div>`;
    $("joinChip").textContent = `Join: ${info.address}`;
    $("joinChip").hidden = false;
  } else {
    $("publicInfo").innerHTML = `<span class="bad">No verified public address.</span><br>Detected egress IP: ${esc(info.ip || "unavailable")}<br>${esc(info.error || "Not reachable from outside.")}`;
    $("joinChip").hidden = true;
  }

  $("memory").max = server.safe_heap_mb;
  $("memoryMax").textContent = `Safe maximum on this host: ${server.safe_heap_mb.toLocaleString()} MiB`;
  if (!state.settingsLoaded) {
    $("memory").value = settings.memory_mb;
    $("memoryValue").textContent = formatMemory(settings.memory_mb);
    $("autoStart").checked = settings.auto_start;
    $("restartDelay").value = settings.restart_delay_seconds;
    $("jvmArgs").value = settings.jvm_args || "";
    state.settingsLoaded = true;
  }
  setLive(true, server.running ? "Panel connected" : "Panel connected, server stopped");
}

function formatMemory(mib) {
  return `${(mib / 1024).toFixed(1)} GB (${mib.toLocaleString()} MiB)`;
}

async function refreshStatus() {
  try {
    renderStatus(await api("/api/status"));
  } catch (error) {
    setLive(false, "Panel unreachable");
  }
}

async function powerAction(which) {
  try {
    const data = await api(`/api/server/${which}`, { method: "POST", body: "{}" });
    toast(data.message);
    await refreshStatus();
  } catch (error) {
    toast(error.message, false);
  }
}

async function saveSettings(key, button) {
  button.disabled = true;
  try {
    const data = await api("/api/settings", { method: "POST", body: JSON.stringify(SAVE_PAYLOADS[key]()) });
    toast(data.message);
    await refreshStatus();
  } catch (error) {
    toast(error.message, false);
  } finally {
    button.disabled = false;
  }
}

async function sendCommand(command) {
  try {
    await api("/api/server/command", { method: "POST", body: JSON.stringify({ command }) });
    await loadConsole();
  } catch (error) {
    toast(error.message, false);
  }
}

async function loadConsole() {
  try {
    const data = await api(`/api/console?after=${state.consoleId}`);
    const box = $("console");
    const nearBottom = box.scrollTop + box.clientHeight >= box.scrollHeight - 40;
    for (const line of data.lines) {
      const row = document.createElement("div");
      row.textContent = line.text;
      box.append(row);
      state.consoleId = line.id;
    }
    while (box.childElementCount > 2000) box.firstElementChild.remove();
    if (nearBottom) box.scrollTop = box.scrollHeight;
  } catch {
    setLive(false, "Panel unreachable");
  }
}

async function loadFiles(path) {
  state.currentPath = path;
  try {
    const data = await api(`/api/files?path=${encodeURIComponent(path)}`);
    $("filePath").textContent = `/${path}`;
    const list = $("files");
    list.replaceChildren();
    if (path) {
      list.append(fileRow("..", "Go up", () => loadFiles(path.split("/").slice(0, -1).join("/"))));
    }
    for (const file of data.files) {
      const full = path ? `${path}/${file.name}` : file.name;
      const meta = file.directory ? "Folder" : `${(file.size / 1024).toFixed(1)} KB`;
      if (file.directory) {
        list.append(fileRow(`${file.name}/`, meta, () => loadFiles(full)));
      } else if (file.editable) {
        list.append(fileRow(file.name, meta, () => openFile(full)));
      } else {
        list.append(fileRow(file.name, meta, null));
      }
    }
    if (!list.childElementCount) list.innerHTML = '<p class="subtle">This folder is empty.</p>';
  } catch (error) {
    toast(error.message, false);
  }
}

function fileRow(label, meta, onOpen) {
  const row = document.createElement("div");
  row.className = "row-item";
  const name = document.createElement("span");
  name.textContent = label;
  const right = document.createElement("span");
  right.className = "meta";
  right.textContent = meta;
  row.append(name, right);
  if (onOpen) {
    row.style.cursor = "pointer";
    row.tabIndex = 0;
    row.addEventListener("click", onOpen);
    row.addEventListener("keydown", (event) => { if (event.key === "Enter") onOpen(); });
  }
  return row;
}

async function openFile(path) {
  try {
    const data = await api(`/api/file?path=${encodeURIComponent(path)}`);
    state.editingPath = path;
    $("editorTitle").textContent = path;
    $("editor").value = data.content;
    $("editorCard").hidden = false;
  } catch (error) {
    toast(error.message, false);
  }
}

async function saveFile() {
  try {
    const data = await api("/api/file", { method: "POST", body: JSON.stringify({ path: state.editingPath, content: $("editor").value }) });
    toast(data.message);
  } catch (error) {
    toast(error.message, false);
  }
}

async function loadPlugins() {
  try {
    const data = await api("/api/plugins");
    $("plugins").innerHTML = data.plugins.length
      ? data.plugins.map((p) => `<div class="row-item"><span>${esc(p.name)}</span><span class="meta">${(p.size / 1024).toFixed(1)} KB</span></div>`).join("")
      : '<p class="subtle">No plugins installed yet.</p>';
  } catch (error) {
    toast(error.message, false);
  }
}

async function uploadPlugin(event) {
  event.preventDefault();
  const file = $("pluginFile").files[0];
  if (!file) return toast("Choose a plugin JAR first.", false);
  try {
    const content = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result).split(",")[1]);
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });
    const data = await api("/api/plugins/upload", { method: "POST", body: JSON.stringify({ name: file.name, content }) });
    toast(data.message);
    loadPlugins();
  } catch (error) {
    toast(error.message, false);
  }
}

async function loadBackups() {
  try {
    const data = await api("/api/backups");
    $("backups").innerHTML = data.backups.length
      ? data.backups.map((b) => `<div class="row-item"><span>${esc(b.name)}</span><span class="meta">${(b.size / 1048576).toFixed(1)} MB</span></div>`).join("")
      : '<p class="subtle">No backups yet.</p>';
  } catch (error) {
    toast(error.message, false);
  }
}

async function createBackup() {
  const button = $("makeBackup");
  button.disabled = true;
  button.textContent = "Saving world...";
  try {
    const data = await api("/api/backups", { method: "POST", body: "{}" });
    toast(data.message);
    loadBackups();
  } catch (error) {
    toast(error.message, false);
  } finally {
    button.disabled = false;
    button.textContent = "Create backup";
  }
}

async function loadActivity() {
  const box = $("activity");
  box.innerHTML = '<p class="subtle">Loading...</p>';
  try {
    const data = await api("/api/activity");
    box.replaceChildren();
    if (!data.entries.length) box.innerHTML = '<p class="subtle">No activity recorded yet.</p>';
    for (const entry of data.entries) {
      const row = document.createElement("div");
      row.className = "row-item";
      const text = document.createElement("span");
      text.textContent = `${entry.action}: ${entry.detail}`;
      const time = document.createElement("span");
      time.className = "meta";
      time.textContent = new Date(entry.created_at).toLocaleString();
      row.append(text, time);
      box.append(row);
    }
  } catch (error) {
    box.innerHTML = `<p class="bad">${esc(error.message)}</p>`;
  }
}

function propertyInput(prop, value) {
  const input = document.createElement(prop.kind === "enum" ? "select" : "input");
  input.id = `prop-${prop.key}`;
  input.dataset.key = prop.key;
  input.setAttribute("aria-label", prop.label);
  if (prop.kind === "bool") {
    input.type = "checkbox";
    input.className = "switch";
    input.checked = value === "true";
  } else if (prop.kind === "int") {
    input.type = "number";
    input.min = prop.min;
    input.max = prop.max;
    input.value = value;
  } else if (prop.kind === "enum") {
    for (const choice of prop.choices) {
      const option = document.createElement("option");
      option.value = choice;
      option.textContent = choice;
      input.append(option);
    }
    input.value = value;
  } else {
    input.type = "text";
    input.maxLength = 256;
    input.value = value;
  }
  return input;
}

function readProperty(input, prop) {
  if (prop.kind === "bool") return input.checked ? "true" : "false";
  return input.value;
}

function refreshPropertyDirty() {
  let changed = 0;
  for (const prop of state.schema) {
    const input = document.querySelector(`[data-key="${prop.key}"]`);
    const dirty = readProperty(input, prop) !== state.savedProps[prop.key];
    input.closest(".property").classList.toggle("changed", dirty);
    if (dirty) changed += 1;
  }
  $("saveProperties").disabled = changed === 0;
  $("saveProperties").textContent = changed ? `Save ${changed} change${changed === 1 ? "" : "s"}` : "Save changes";
}

async function loadProperties() {
  try {
    const data = await api("/api/properties");
    state.schema = data.schema;
    state.savedProps = { ...data.values };
    const groups = $("propertyGroups");
    groups.replaceChildren();
    for (const group of [...new Set(data.schema.map((p) => p.group))]) {
      const section = document.createElement("div");
      const heading = document.createElement("h3");
      heading.textContent = group;
      const grid = document.createElement("div");
      grid.className = "property-grid";
      section.append(heading, grid);
      for (const prop of data.schema.filter((p) => p.group === group)) {
        const wrapper = document.createElement("div");
        wrapper.className = "property";
        const label = document.createElement("label");
        label.htmlFor = `prop-${prop.key}`;
        label.textContent = prop.label;
        if (prop.note) {
          const note = document.createElement("small");
          note.textContent = prop.note;
          label.append(note);
        }
        const input = propertyInput(prop, data.values[prop.key]);
        input.addEventListener("input", refreshPropertyDirty);
        input.addEventListener("change", refreshPropertyDirty);
        wrapper.append(label, input);
        grid.append(wrapper);
      }
      groups.append(section);
    }
    refreshPropertyDirty();
  } catch (error) {
    toast(error.message, false);
  }
}

async function saveProperties() {
  const changes = {};
  for (const prop of state.schema) {
    const value = readProperty(document.querySelector(`[data-key="${prop.key}"]`), prop);
    if (value !== state.savedProps[prop.key]) changes[prop.key] = value;
  }
  try {
    const data = await api("/api/properties", { method: "POST", body: JSON.stringify(changes) });
    toast(data.message);
    Object.assign(state.savedProps, changes);
    refreshPropertyDirty();
  } catch (error) {
    toast(error.message, false);
  }
}

function renderPresets() {
  $("presetRow").replaceChildren(...JVM_PRESETS.map(([label, flags]) => {
    const button = document.createElement("button");
    button.textContent = label;
    button.addEventListener("click", () => { $("jvmArgs").value = flags; });
    return button;
  }));
}

function renderQuickCommands() {
  $("quickCommands").replaceChildren(...QUICK_COMMANDS.map(([label, command]) => {
    const button = document.createElement("button");
    button.textContent = label;
    button.addEventListener("click", () => sendCommand(command));
    return button;
  }));
}

function bindEvents() {
  document.querySelectorAll(".tab").forEach((tab) => tab.addEventListener("click", () => setTab(tab.dataset.tab)));
  document.querySelectorAll("[data-power]").forEach((button) => button.addEventListener("click", () => powerAction(button.dataset.power)));
  document.querySelectorAll("[data-save]").forEach((button) => button.addEventListener("click", () => saveSettings(button.dataset.save, button)));
  document.addEventListener("click", async (event) => {
    const copy = event.target.closest("[data-copy]");
    if (!copy) return;
    try {
      await navigator.clipboard.writeText(copy.dataset.copy);
      toast("Address copied.");
    } catch {
      toast("Copy failed. Select the address and copy it manually.", false);
    }
  });
  $("memory").addEventListener("input", (event) => { $("memoryValue").textContent = formatMemory(Number(event.target.value)); });
  $("commandForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const command = $("command").value.trim();
    if (!command) return;
    await sendCommand(command);
    $("command").value = "";
  });
  $("clearConsole").addEventListener("click", () => $("console").replaceChildren());
  $("playerForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const data = await api("/api/players/action", {
        method: "POST",
        body: JSON.stringify({ action: $("playerAction").value, name: $("playerName").value.trim() }),
      });
      toast(data.message);
      $("playerName").value = "";
      await loadConsole();
    } catch (error) {
      toast(error.message, false);
    }
  });
  $("refreshFiles").addEventListener("click", () => loadFiles(state.currentPath));
  $("closeEditor").addEventListener("click", () => { $("editorCard").hidden = true; });
  $("saveFile").addEventListener("click", saveFile);
  $("refreshPlugins").addEventListener("click", loadPlugins);
  $("pluginForm").addEventListener("submit", uploadPlugin);
  $("refreshBackups").addEventListener("click", loadBackups);
  $("makeBackup").addEventListener("click", createBackup);
  $("refreshActivity").addEventListener("click", loadActivity);
  $("saveProperties").addEventListener("click", saveProperties);
}

bindEvents();
renderPresets();
renderQuickCommands();
loadProperties();
loadFiles("");
loadPlugins();
loadBackups();
refreshStatus();
loadConsole();
setInterval(refreshStatus, 5000);
setInterval(loadConsole, 2000);
