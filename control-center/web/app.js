"use strict";

const dock = document.getElementById("dock");
const clock = document.getElementById("clock");
const date = document.getElementById("date");
const toast = document.getElementById("toast");
const library = document.getElementById("library");
const libraryGrid = document.getElementById("library-grid");
const libraryClose = document.getElementById("library-close");

const FALLBACK_APPS = [
  { appId: "9Ur5IzDKqV.TizenYouTube", label: "YouTube", glyph: "▶", color: "#ff2d55", icon: "icons/youtube.png" },
  { appId: "org.tizen.netflix-app", label: "Netflix", glyph: "N", color: "#e50914", icon: "icons/netflix.png" },
  { appId: "org.tizen.primevideo", label: "Prime Video", glyph: "P", color: "#00a8e1" },
  { appId: "IkWsFHtOY9.Stremio", label: "Stremio", glyph: "S", color: "#7c3aed", icon: "icons/stremio.png" },
  { appId: "rJeHak5zRg.Spotify", label: "Spotify", glyph: "♫", color: "#1db954", icon: "icons/spotify.png" },
  { appId: "org.tizen.browser", label: "Internet", glyph: "◎", color: "#3b82f6" },
  { appId: "HEPsqFNie0.tvplusstandalone", label: "TV Plus", glyph: "▣", color: "#ef4444" },
  { appId: "com.samsung.tv.store", label: "Apps", glyph: "▦", color: "#8b5cf6", icon: "icons/apps.png", dock: false },
  { appId: "org.tizen.menu", label: "Settings", glyph: "⚙", color: "#22d3ee" },
  { action: "library", label: "All Apps", glyph: "▦", color: "#94a3b8" },
];

const LIBRARY_COLUMNS = 5;
const PALETTE = ["#ff2d55", "#e50914", "#00a8e1", "#7c3aed", "#1db954", "#3b82f6", "#ef4444", "#8b5cf6", "#22d3ee", "#f59e0b"];
const SERVICE_RE = /(Service|service|daemon|agent|client|provider|framework|analytics|smartthings|account|billing|knox|easysetup|voice|aov|adagent|pisa|iacr|screen-analysis|mcf|companion)/;

const timeFormat = new Intl.DateTimeFormat("en-GB", {
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

const dateFormat = new Intl.DateTimeFormat("en-GB", {
  weekday: "long",
  day: "numeric",
  month: "long",
});

let configApps = FALLBACK_APPS;
let dockApps = [];
let libraryApps = [];
let dockTiles = [];
let libraryTiles = [];
let dockFocus = 0;
let libraryFocus = 0;
let libraryOpen = false;
let toastTimer = 0;

function updateClock() {
  const now = new Date();
  clock.textContent = timeFormat.format(now);
  date.textContent = dateFormat.format(now);
}

function showToast(message) {
  window.clearTimeout(toastTimer);
  toast.textContent = message;
  toast.classList.add("show");
  toastTimer = window.setTimeout(() => toast.classList.remove("show"), 3200);
}

function colorFor(id) {
  let hash = 0;
  for (let i = 0; i < id.length; i += 1) {
    hash = (hash * 31 + id.charCodeAt(i)) >>> 0;
  }
  return PALETTE[hash % PALETTE.length];
}

function glyphFor(name) {
  const trimmed = (name || "").trim();
  if (!trimmed) {
    return "•";
  }
  const first = trimmed[0];
  return first.toUpperCase();
}

function iconUrl(path) {
  if (!path) {
    return "";
  }
  if (/^(https?|file):/.test(path)) {
    return path;
  }
  return `file://${path}`;
}

function mapTizenApp(info) {
  return {
    appId: info.id,
    label: info.name || info.id,
    glyph: glyphFor(info.name),
    color: colorFor(info.id),
    icon: iconUrl(info.iconPath),
  };
}

function getTizenApps() {
  if (!window.tizen || !tizen.application || typeof tizen.application.getAppsInfo !== "function") {
    return Promise.resolve(null);
  }
  return new Promise((resolve) => {
    try {
      tizen.application.getAppsInfo(
        (list) => {
          const apps = list
            .filter((info) => info && info.id && info.name)
            .filter((info) => !SERVICE_RE.test(info.id))
            .map(mapTizenApp);
          resolve(apps.length > 0 ? apps : null);
        },
        () => resolve(null)
      );
    } catch (error) {
      resolve(null);
    }
  });
}

function loadConfig() {
  return fetch("apps.json?v=9", { cache: "no-store" })
    .then((response) => {
      if (!response.ok) {
        throw new Error(`apps.json HTTP ${response.status}`);
      }
      return response.json();
    })
    .then((parsed) => (Array.isArray(parsed) && parsed.length > 0 ? parsed : FALLBACK_APPS))
    .catch((error) => {
      console.warn("[control-center] apps.json unavailable; using fallback", error);
      return FALLBACK_APPS;
    });
}

function favoriteApps() {
  return configApps.filter((app) => app.appId && app.dock !== false);
}

function libraryAction() {
  return configApps.find((app) => app.action === "library") || {
    action: "library",
    label: "All Apps",
    glyph: "▦",
    color: "#94a3b8",
  };
}

function mergeFavorites(installed) {
  const byId = new Map(installed.map((app) => [app.appId, app]));
  const dock = [];
  favoriteApps().forEach((favorite) => {
    const match = byId.get(favorite.appId);
    if (match) {
      dock.push({
        ...match,
        label: favorite.label || match.label,
        glyph: favorite.glyph || match.glyph,
        color: favorite.color || match.color,
      });
    }
  });
  if (dock.length === 0) {
    dock.push(...installed.slice(0, 8));
  }
  dock.push(libraryAction());
  return dock;
}

function sortLibrary(installed) {
  const order = new Map(favoriteApps().map((app, index) => [app.appId, index]));
  return installed.slice().sort((a, b) => {
    const ai = order.has(a.appId) ? order.get(a.appId) : 999;
    const bi = order.has(b.appId) ? order.get(b.appId) : 999;
    return ai - bi || a.label.localeCompare(b.label);
  });
}

async function loadApps() {
  configApps = await loadConfig();
  const params = new URLSearchParams(location.search);
  const dynamic = location.protocol === "file:" || params.get("installed") === "1";
  const installed = dynamic ? await getTizenApps() : null;

  if (installed) {
    libraryApps = sortLibrary(installed);
    dockApps = mergeFavorites(libraryApps);
  } else {
    libraryApps = configApps.filter((app) => app.appId);
    dockApps = configApps.filter((app) => app.action === "library" || (app.appId && app.dock !== false));
  }

  renderDock();
}

function glyphIcon(app) {
  const icon = document.createElement("span");
  icon.className = "tile-icon";
  icon.textContent = app.glyph || "•";
  return icon;
}

function createIcon(app) {
  if (!app.icon) {
    return glyphIcon(app);
  }
  const image = document.createElement("img");
  image.className = "tile-icon tile-image";
  image.src = app.icon;
  image.alt = "";
  image.decoding = "async";
  image.addEventListener(
    "error",
    () => image.replaceWith(glyphIcon(app)),
    { once: true }
  );
  return image;
}

function createTile(app, index, onFocus, onActivate) {
  const tile = document.createElement("button");
  tile.className = "tile";
  tile.type = "button";
  tile.dataset.appId = app.appId || "";
  tile.dataset.label = app.label || "App";
  tile.style.setProperty("--tile-color", app.color || "#64748b");
  tile.setAttribute("aria-label", app.label || "App");
  tile.setAttribute("aria-selected", "false");

  const label = document.createElement("span");
  label.className = "tile-label";
  label.textContent = app.label || app.appId || "App";

  tile.append(createIcon(app), label);
  tile.addEventListener("mouseenter", () => onFocus(index));
  tile.addEventListener("click", () => {
    onFocus(index);
    onActivate(app);
  });
  return tile;
}

function renderDock() {
  dock.replaceChildren();
  dockTiles = dockApps.map((app, index) =>
    createTile(app, index, setDockFocus, activate)
  );
  dockTiles.forEach((tile) => dock.append(tile));
  if (dockTiles.length > 0) {
    setDockFocus(0);
  }
}

function renderLibrary() {
  libraryGrid.replaceChildren();
  libraryTiles = libraryApps.map((app, index) =>
    createTile(app, index, setLibraryFocus, activate)
  );
  libraryTiles.forEach((tile) => libraryGrid.append(tile));
}

function markFocused(tiles, index) {
  tiles.forEach((tile, i) => {
    const active = i === index;
    tile.classList.toggle("focused", active);
    tile.setAttribute("aria-selected", active ? "true" : "false");
    tile.tabIndex = active ? 0 : -1;
  });
  if (tiles[index]) {
    tiles[index].focus({ preventScroll: true });
    tiles[index].scrollIntoView({ block: "nearest", inline: "nearest" });
  }
}

function setDockFocus(index) {
  if (dockTiles.length === 0) {
    return;
  }
  dockFocus = (index + dockTiles.length) % dockTiles.length;
  markFocused(dockTiles, dockFocus);
}

function setLibraryFocus(index) {
  if (libraryTiles.length === 0) {
    return;
  }
  libraryFocus = Math.max(0, Math.min(index, libraryTiles.length - 1));
  markFocused(libraryTiles, libraryFocus);
}

function openLibrary() {
  if (!libraryOpen) {
    renderLibrary();
    library.hidden = false;
    libraryOpen = true;
  }
  setLibraryFocus(0);
}

function closeLibrary() {
  library.hidden = true;
  libraryOpen = false;
  const index = dockApps.findIndex((app) => app.action === "library");
  setDockFocus(index >= 0 ? index : 0);
}

function activate(app) {
  if (!app) {
    return;
  }
  if (app.action === "library") {
    openLibrary();
    return;
  }
  if (!app.appId) {
    showToast(`${app.label || "App"}: not wired yet`);
    return;
  }
  showToast(`${app.label || app.appId}: launch bridge not wired yet (${app.appId})`);
  console.log("[control-center] launch requested", { label: app.label, appId: app.appId });
}

function libraryColumns() {
  const columns = getComputedStyle(libraryGrid).gridTemplateColumns;
  return columns && columns !== "none" ? columns.split(" ").length : LIBRARY_COLUMNS;
}

document.addEventListener("keydown", (event) => {
  if (libraryOpen) {
    switch (event.key) {
      case "ArrowLeft":
        event.preventDefault();
        setLibraryFocus(libraryFocus - 1);
        break;
      case "ArrowRight":
        event.preventDefault();
        setLibraryFocus(libraryFocus + 1);
        break;
      case "ArrowUp":
        event.preventDefault();
        setLibraryFocus(libraryFocus - libraryColumns());
        break;
      case "ArrowDown":
        event.preventDefault();
        setLibraryFocus(libraryFocus + libraryColumns());
        break;
      case "Enter":
      case " ":
        event.preventDefault();
        activate(libraryApps[libraryFocus]);
        break;
      case "Escape":
      case "Backspace":
        event.preventDefault();
        closeLibrary();
        break;
      default:
        break;
    }
    return;
  }

  switch (event.key) {
    case "ArrowLeft":
      event.preventDefault();
      setDockFocus(dockFocus - 1);
      break;
    case "ArrowRight":
      event.preventDefault();
      setDockFocus(dockFocus + 1);
      break;
    case "ArrowDown":
      event.preventDefault();
      openLibrary();
      break;
    case "Enter":
    case " ":
      event.preventDefault();
      activate(dockApps[dockFocus]);
      break;
    case "Escape":
    case "Backspace":
      event.preventDefault();
      showToast("Back");
      break;
    default:
      break;
  }
});

libraryClose.addEventListener("click", closeLibrary);

updateClock();
window.setInterval(updateClock, 1000);
loadApps().then(() => {
  if (new URLSearchParams(location.search).get("library") === "1") {
    openLibrary();
  }
});
