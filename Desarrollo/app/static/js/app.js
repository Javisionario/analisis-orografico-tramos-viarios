const form = document.querySelector("#generationForm");
const statusBox = document.querySelector("#status");
const roadInput = document.querySelector("#carretera");
const clearRoad = document.querySelector("#clearRoad");
const suggestionsBox = document.querySelector("#roadSuggestions");
const roadMessage = document.querySelector("#roadMessage");
const pkWarnings = document.querySelector("#pkWarnings");
const resultsBox = document.querySelector("#results");
const zipDownloads = document.querySelector("#zipDownloads");
const rightPanel = document.querySelector("#rightPanel");
const smooth = document.querySelector("#suavizado");
const smoothValue = document.querySelector("#smoothValue");
const smoothHelp = document.querySelector("#smoothHelp");
const slopeSmooth = document.querySelector("#suavizadoPendientes");
const slopeSmoothValue = document.querySelector("#slopeSmoothValue");
const slopeSmoothHelp = document.querySelector("#slopeSmoothHelp");
const sample = document.querySelector("#intervaloMuestreo");
const sampleValue = document.querySelector("#sampleValue");
const sampleHelp = document.querySelector("#sampleHelp");
const resolutionMdt = document.querySelector("#resolucionMdt");
const anomaly = document.querySelector("#umbralAnomalia");
const anomalyValue = document.querySelector("#anomalyValue");
const anomalyHelp = document.querySelector("#anomalyHelp");
const modoEjeY = document.querySelector("#modoEjeY");
const viasFondoModo = document.querySelector("#viasFondoModo");
const mapaBase = document.querySelector("#mapaBase");
const cartoApiKeyField = document.querySelector("#cartoApiKeyField");
const cartoApiKey = document.querySelector("#cartoApiKey");
const cartoApiKeyStatus = document.querySelector("#cartoApiKeyStatus");
const recordarCartoApiKeyField = document.querySelector("#recordarCartoApiKeyField");
const mostrarCartoApiKey = document.querySelector("#mostrarCartoApiKey");
const olvidarCartoApiKey = document.querySelector("#olvidarCartoApiKey");
const pkModo = document.querySelector("#pkModo");
const pkManualControls = document.querySelector("#pkManualControls");
const pkSimboloCada = document.querySelector("#pkSimboloCada");
const pkEtiquetaCada = document.querySelector("#pkEtiquetaCada");
const pkSimboloCadaValue = document.querySelector("#pkSimboloCadaValue");
const pkEtiquetaCadaValue = document.querySelector("#pkEtiquetaCadaValue");
const pkAutoHelp = document.querySelector("#pkAutoHelp");
const sgAdvanced = document.querySelector("#sgAdvanced");
const sgAdvancedControls = document.querySelector("#sgAdvancedControls");
const sgWindow = document.querySelector("#sgWindow");
const sgWindowValue = document.querySelector("#sgWindowValue");
const sgPolyorder = document.querySelector("#sgPolyorder");
const sgPolyorderValue = document.querySelector("#sgPolyorderValue");
const sgSlopeAdvanced = document.querySelector("#sgSlopeAdvanced");
const sgSlopeAdvancedControls = document.querySelector("#sgSlopeAdvancedControls");
const sgSlopeWindow = document.querySelector("#sgSlopeWindow");
const sgSlopeWindowValue = document.querySelector("#sgSlopeWindowValue");
const sgSlopePolyorder = document.querySelector("#sgSlopePolyorder");
const sgSlopePolyorderValue = document.querySelector("#sgSlopePolyorderValue");
const alphaLocalizacion = document.querySelector("#alphaLocalizacion");
const alphaPendientes = document.querySelector("#alphaPendientes");
const alphaLocalizacionValue = document.querySelector("#alphaLocalizacionValue");
const alphaPendientesValue = document.querySelector("#alphaPendientesValue");
const openHelp = document.querySelector("#openHelp");
const closeHelp = document.querySelector("#closeHelp");
const helpOverlay = document.querySelector("#helpOverlay");
const helpPanel = document.querySelector("#helpPanel");
const helpBackground = document.querySelectorAll("body > .topbar, body > .app-layout");

let selectedRoad = null;
let roadCache = null;
let roadLoading = null;
let loadingTimer = null;
let loadingStartedAt = null;
let lastProgress = null;
let helpTrigger = null;
const SUGGESTION_LIMIT = 90;
const PK_INTERVALS = [1, 5, 10, 25, 50, 100, 250];
const PROGRESS_PHASES = [
  "Preparando el tramo de estudio.",
  "Leyendo carretera y PKs.",
  "Cargando modelo digital del terreno.",
  "Muestreando cotas sobre la vía.",
  "Calculando pendientes.",
  "Generando perfil longitudinal.",
  "Componiendo mapa de localización.",
  "Componiendo mapa de pendientes.",
  "Preparando archivos de descarga.",
  "Finalizando resultados.",
];
const SG_TABLE = {
  0: { window: 0, polyorder: 0, label: "sin suavizado" },
  1: { window: 3, polyorder: 2, label: "efecto muy leve" },
  2: { window: 5, polyorder: 3, label: "leve" },
  3: { window: 9, polyorder: 3, label: "leve-medio" },
  4: { window: 13, polyorder: 2, label: "medio-bajo" },
  5: { window: 17, polyorder: 2, label: "medio" },
  6: { window: 21, polyorder: 2, label: "medio-alto" },
  7: { window: 27, polyorder: 2, label: "alto" },
  8: { window: 33, polyorder: 2, label: "alto estable" },
  9: { window: 41, polyorder: 1, label: "muy alto" },
  10: { window: 51, polyorder: 1, label: "muy suavizado" },
};
const CARTO_API_KEY_MASK = "••••••••••••••••";
let cartoStoredKeyAvailable = false;
let cartoShowPressed = false;

function setStatus(title, text) {
  statusBox.innerHTML = `<h2>${title}</h2><p>${text}</p>`;
}

function showRightPanel(state) {
  const resultsVisible = state !== "viewer";
  rightPanel.classList.toggle("show-results", resultsVisible);
  if (state === "viewer") window.roadViewer?.show();
}

window.showViewerResults = () => showRightPanel("results");
window.showRoadViewer = () => showRightPanel("viewer");

window.setRoadFromViewer = async (carretera, pkInicio = null, pkFin = null) => {
  const segment = activeSegment();
  if (!segment) throw new Error("No hay tramo activo");
  const startField = segment.querySelector('[data-role="pk-start"]');
  const endField = segment.querySelector('[data-role="pk-end"]');
  const isWholeRange = pkInicio !== null && pkFin !== null;
  const targetField = pkInicio !== null ? startField : endField;
  const otherField = targetField === startField ? endField : startField;
  if (!isWholeRange && otherField.dataset.viewerRoad && normalizeRoad(otherField.dataset.viewerRoad) !== normalizeRoad(carretera)) {
    return {
      ok: false,
      reason: "different-road",
      message: "El punto seleccionado no pertenece a la misma vía que el otro extremo del tramo.",
    };
  }
  await loadRoads();
  const road = roadExact(carretera);
  if (!road) throw new Error("Carretera no encontrada");
  selectSegmentRoad(segment, road);
  if (pkInicio !== null) startField.value = Number(pkInicio).toFixed(3);
  if (pkFin !== null) endField.value = Number(pkFin).toFixed(3);
  if (pkInicio !== null && pkFin !== null) {
    const sentido = segment.querySelector('[data-role="direction"]').value;
    const low = Math.min(Number(pkInicio), Number(pkFin));
    const high = Math.max(Number(pkInicio), Number(pkFin));
    startField.value = (sentido === "decreciente" ? high : low).toFixed(3);
    endField.value = (sentido === "decreciente" ? low : high).toFixed(3);
  }
  if (pkInicio !== null) startField.dataset.viewerRoad = road.carretera;
  if (pkFin !== null) endField.dataset.viewerRoad = road.carretera;
  await validateSegmentPk(segment, true);
  return { ok: true };
};

function openHelpPanel(targetId = null, trigger = null) {
  if (!helpOverlay || !helpPanel) return;
  helpTrigger = trigger || document.activeElement;
  helpBackground.forEach((element) => {
    element.inert = true;
    element.setAttribute("aria-hidden", "true");
  });
  helpOverlay.hidden = false;
  const target = targetId ? document.getElementById(targetId) : null;
  const content = helpPanel.querySelector(".help-content");
  if (content) content.scrollTop = 0;
  if (target) target.scrollIntoView({ block: "start" });
  helpPanel.focus();
}

function closeHelpPanel() {
  if (!helpOverlay || helpOverlay.hidden) return;
  helpOverlay.hidden = true;
  helpBackground.forEach((element) => {
    element.inert = false;
    element.removeAttribute("aria-hidden");
  });
  if (helpTrigger && typeof helpTrigger.focus === "function") helpTrigger.focus();
  helpTrigger = null;
}

function helpFocusableElements() {
  if (!helpPanel) return [];
  return [...helpPanel.querySelectorAll("a[href], button:not([disabled]), [tabindex]:not([tabindex='-1'])")]
    .filter((element) => !element.hidden && element.getClientRects().length > 0);
}

function formatElapsed(seconds) {
  const total = Math.max(0, Math.floor(seconds || 0));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function stopLoadingClock() {
  if (loadingTimer) clearInterval(loadingTimer);
  loadingTimer = null;
}

function renderLoading(job = {}) {
  const index = Number(job.fase_indice || 1);
  const total = Number(job.fases_total || PROGRESS_PHASES.length);
  const percent = Math.max(4, Math.min(100, Math.round((index / total) * 100)));
  const elapsed = job.tiempo_transcurrido_s ?? (loadingStartedAt ? (performance.now() - loadingStartedAt) / 1000 : 0);
  const phase = job.fase || PROGRESS_PHASES[Math.max(0, index - 1)] || "Preparando generación.";
  const details = PROGRESS_PHASES.map((item, idx) => {
    const state = idx + 1 < index ? "done" : idx + 1 === index ? "active" : "";
    return `<li class="${state}"><span>${idx + 1}</span>${item}</li>`;
  }).join("");
  statusBox.innerHTML = `
    <div class="loading-card">
      <div class="loading-head">
        <div class="spinner" aria-hidden="true"></div>
        <div>
          <h2>Generando resultados</h2>
          <p>${phase}</p>
        </div>
        <strong>${formatElapsed(elapsed)}</strong>
      </div>
      <div class="progress-track"><div style="width:${percent}%"></div></div>
      <ol class="progress-steps">${details}</ol>
      <p class="loading-note">${job.detalle || "La herramienta está componiendo mapas, perfil y archivos de descarga."}</p>
    </div>
  `;
}

function normalizeRoad(value) {
  return String(value || "").trim().toUpperCase().replace(/[\s_-]+/g, "");
}

function normalizedPrefix(value) {
  return String(value || "").trim().toUpperCase();
}

function boolField(data, name) {
  return data.get(name) === "on";
}

function numberOrNull(value) {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function formatPk(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "";
  const sign = n < 0 ? "-" : "";
  const abs = Math.abs(n);
  let km = Math.floor(abs);
  let m = Math.round((abs - km) * 1000);
  if (m >= 1000) {
    km += 1;
    m -= 1000;
  }
  return `${sign}${km}+${String(m).padStart(3, "0")}`;
}

const segmentList = document.querySelector("#segmentList");
const addSegmentButton = document.querySelector("#addSegment");
const multiSegmentWarning = document.querySelector("#multiSegmentWarning");
const pendingMapCheckbox = document.querySelector('[name="generar_mapa_pendientes"]');
let activeSegmentId = 1;
let nextSegmentId = 2;
let pendingMapBeforeMulti = null;
const segmentRoads = new Map();

function segments() { return [...segmentList.querySelectorAll(".segment-block")]; }
function updateSegmentLabels() {
  segments().forEach((segment, index) => {
    const label = segment.querySelector(".segment-header strong");
    if (label) label.textContent = `Tramo ${index + 1}`;
  });
}
function activeSegment() { return segmentList.querySelector(`.segment-block[data-segment-id="${activeSegmentId}"]`) || segments()[0] || null; }
function segmentRoad(segment) { return segmentRoads.get(segment.dataset.segmentId) || null; }
function setSegmentActive(segment) {
  if (!segment) return;
  activeSegmentId = Number(segment.dataset.segmentId);
  segments().forEach((item) => item.classList.toggle("is-active", item === segment));
}
function showSegmentWarnings(segment, items) {
  const box = segment.querySelector('[data-role="pk-warnings"]');
  const clean = items.filter(Boolean);
  box.hidden = clean.length === 0;
  box.innerHTML = clean.map((item) => `<p>${item}</p>`).join("");
}

function updateMultiSegmentMode() {
  const multi = segments().length > 1;
  if (multi && pendingMapBeforeMulti === null) pendingMapBeforeMulti = pendingMapCheckbox.checked;
  if (multi) {
    pendingMapCheckbox.checked = false;
    pendingMapCheckbox.disabled = true;
  } else if (pendingMapBeforeMulti !== null) {
    pendingMapCheckbox.disabled = false;
    pendingMapCheckbox.checked = pendingMapBeforeMulti;
    pendingMapBeforeMulti = null;
  }
  multiSegmentWarning.hidden = !multi;
  const help = document.querySelector("#pkAutoHelp");
  if (help) help.textContent = multi && document.querySelector("#pkModo")?.value === "automatico"
    ? "Automático: símbolo y etiqueta según longitud de cada tramo."
    : "Automático: símbolo y etiqueta según longitud del tramo.";
}

function parseDivisionPk(value) {
  const text = String(value ?? "").trim().replace(",", ".");
  if (!text) return null;
  const station = text.match(/^(\d+)\+(\d{1,3})$/);
  if (station) return Number(station[1]) + Number(station[2].padEnd(3, "0")) / 1000;
  const parsed = Number(text);
  return Number.isFinite(parsed) ? parsed : null;
}

function divisionValues(segment, report = true) {
  const start = numberOrNull(segment.querySelector('[data-role="pk-start"]')?.value);
  const end = numberOrNull(segment.querySelector('[data-role="pk-end"]')?.value);
  const values = [...segment.querySelectorAll('[data-role="division-pk"]')].map((field) => parseDivisionPk(field.value));
  const problems = [];
  if (values.some((value) => value === null)) problems.push("Cada división debe usar un PK válido, por ejemplo 15+000.");
  if (Number.isFinite(start) && Number.isFinite(end)) {
    const low = Math.min(start, end); const high = Math.max(start, end);
    if (values.some((value) => value !== null && (value <= low + 0.002 || value >= high - 0.002))) problems.push("Las divisiones deben quedar estrictamente dentro del tramo.");
    const ordered = values.filter((value) => value !== null).sort((a, b) => a - b);
    if (ordered.some((value, index) => index && value - ordered[index - 1] <= 0.002)) problems.push("No puede haber divisiones duplicadas o separadas menos de 2 m.");
  }
  const box = segment.querySelector('[data-role="division-warnings"]');
  if (report && box) { box.hidden = !problems.length; box.innerHTML = problems.map((item) => `<p>${item}</p>`).join(""); }
  if (problems.length) throw new Error(problems[0]);
  return values.filter((value) => value !== null);
}

function divisionRowMarkup() {
  return `<div class="division-row"><label><span>División PK</span><input data-role="division-pk" type="text" inputmode="decimal" placeholder="15+000"></label><button class="ghost" data-role="remove-division" type="button" aria-label="Eliminar división">×</button></div>`;
}

async function loadRoads() {
  if (roadCache) return roadCache;
  if (!roadLoading) {
    const start = performance.now();
    roadLoading = fetch("/api/carreteras")
      .then((response) => {
        if (!response.ok) throw new Error("No se pudo consultar carreteras");
        return response.json();
      })
      .then((data) => {
        const items = (data.items || []).map((item) => ({
          ...item,
          normalizado: item.normalizado || normalizeRoad(item.carretera),
        }));
        console.info(`Carreteras cargadas: ${items.length}/${data.total ?? items.length} en ${Math.round(performance.now() - start)} ms`);
        return items;
      });
  }
  roadCache = await roadLoading;
  return roadCache;
}

function filterRoads(q) {
  const query = normalizeRoad(q);
  const roads = roadCache || [];
  if (!query) return roads;
  const rawQuery = normalizedPrefix(q);
  return roads
    .filter((item) => String(item.normalizado || normalizeRoad(item.carretera)).includes(query))
    .sort((a, b) => roadRank(a, query, rawQuery) - roadRank(b, query, rawQuery) || String(a.carretera).localeCompare(String(b.carretera), "es"));
}

function roadRank(item, query, rawQuery) {
  const original = normalizedPrefix(item.carretera);
  const norm = String(item.normalizado || normalizeRoad(item.carretera));
  if (norm === query) return 0;
  if (original.startsWith(rawQuery)) return 1;
  if (norm.startsWith(query)) return 2;
  if (original.includes(rawQuery)) return 3;
  if (norm.includes(query)) return 4;
  return 5;
}

function roadExact(value) {
  const target = normalizeRoad(value);
  return (roadCache || []).find((item) => String(item.normalizado || normalizeRoad(item.carretera)) === target) || null;
}

function selectSegmentRoad(segment, item) {
  segmentRoads.set(segment.dataset.segmentId, item);
  segment.querySelector('[data-role="road"]').value = item.carretera;
  const message = segment.querySelector('[data-role="road-message"]');
  message.textContent = item.pk_min !== undefined ? `Rango real ${formatPk(item.pk_min)} a ${formatPk(item.pk_max)}` : "";
  message.className = "field-message ok";
  segment.querySelector('[data-role="suggestions"]').hidden = true;
  segment.querySelector('[data-role="clear-road"]').classList.add("visible");
  validateSegmentPk(segment);
}

function renderSuggestions(segment, items, q) {
  const suggestions = segment.querySelector('[data-role="suggestions"]');
  suggestions.innerHTML = "";
  const shown = items.slice(0, SUGGESTION_LIMIT);
  if (!shown.length) {
    suggestions.innerHTML = `<div class="suggestion-empty">${q ? "No hay coincidencias" : "No hay carreteras disponibles"}</div>`;
    suggestions.hidden = false;
    return;
  }
  for (const item of shown) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "suggestion";
    button.innerHTML = `<strong>${item.carretera}</strong><span>${formatPk(item.pk_min)} - ${formatPk(item.pk_max)}</span>`;
    button.addEventListener("click", () => selectSegmentRoad(segment, item));
    suggestions.appendChild(button);
  }
  if (items.length > shown.length) {
    const more = document.createElement("div");
    more.className = "suggestion-empty";
    more.textContent = `Mostrando ${shown.length} de ${items.length} coincidencias. Sigue escribiendo para afinar.`;
    suggestions.appendChild(more);
  }
  suggestions.hidden = false;
}

async function refreshSegmentSuggestions(segment) {
  const roadInputLocal = segment.querySelector('[data-role="road"]');
  const message = segment.querySelector('[data-role="road-message"]');
  const q = roadInputLocal.value.trim();
  segment.querySelector('[data-role="clear-road"]').classList.toggle("visible", q.length > 0);
  const selected = segmentRoad(segment);
  if (selected && normalizeRoad(selected.carretera) !== normalizeRoad(q)) segmentRoads.delete(segment.dataset.segmentId);
  message.className = "field-message";
  try {
    await loadRoads();
    renderSuggestions(segment, filterRoads(q), q);
    const exact = roadExact(q);
    if (exact) {
      segmentRoads.set(segment.dataset.segmentId, exact);
      message.textContent = `Rango real ${formatPk(exact.pk_min)} a ${formatPk(exact.pk_max)}`;
      message.className = "field-message ok";
    } else if (q && filterRoads(q).length === 0) {
      message.textContent = "Carretera no encontrada";
      message.className = "field-message error";
    } else if (q) {
      message.textContent = "Selecciona una carretera de la lista";
    } else {
      message.textContent = "";
    }
  } catch (error) {
    message.textContent = String(error.message || error);
    message.className = "field-message error";
  }
}

function clearSegmentRoad(segment) {
  segment.querySelector('[data-role="road"]').value = "";
  segmentRoads.delete(segment.dataset.segmentId);
  segment.querySelector('[data-role="road-message"]').textContent = "";
  segment.querySelector('[data-role="road-message"]').className = "field-message";
  segment.querySelector('[data-role="suggestions"]').hidden = true;
  segment.querySelector('[data-role="clear-road"]').classList.remove("visible");
  showSegmentWarnings(segment, []);
  segment.querySelector('[data-role="road"]').focus();
  refreshSegmentSuggestions(segment);
}

async function ensureSegmentRoad(segment) {
  await loadRoads();
  const input = segment.querySelector('[data-role="road"]');
  const selected = segmentRoad(segment);
  if (selected && normalizeRoad(selected.carretera) === normalizeRoad(input.value)) return selected;
  const exact = roadExact(input.value);
  if (!exact) {
    const message = segment.querySelector('[data-role="road-message"]');
    message.textContent = "No se puede generar: carretera inexistente";
    message.className = "field-message error";
    throw new Error("Carretera inexistente");
  }
  selectSegmentRoad(segment, exact);
  return exact;
}

async function rangeForSegment(segment) {
  const road = await ensureSegmentRoad(segment);
  const params = new URLSearchParams({
    carretera: road.carretera,
    sentido: segment.querySelector('[data-role="direction"]').value,
  });
  const pkInicio = numberOrNull(segment.querySelector('[data-role="pk-start"]').value);
  const pkFin = numberOrNull(segment.querySelector('[data-role="pk-end"]').value);
  if (pkInicio !== null) params.set("pk_inicio", pkInicio);
  if (pkFin !== null) params.set("pk_fin", pkFin);
  const response = await fetch(`/api/rango-carretera?${params.toString()}`);
  if (!response.ok) throw new Error((await response.json()).detail || "No se pudo validar rango");
  return response.json();
}

async function validateSegmentPk(segment, apply = false) {
  if (!segment.querySelector('[data-role="road"]').value.trim()) return null;
  try {
    const data = await rangeForSegment(segment);
    const warnings = [];
    for (const item of data.ajustes || []) {
      if (item.advertencia) {
        warnings.push(item.advertencia);
        if (apply) {
          const field = segment.querySelector(item.campo === "pk_inicio" ? '[data-role="pk-start"]' : '[data-role="pk-end"]');
          field.value = Number(item.ajustado).toFixed(3);
        }
      }
    }
    showSegmentWarnings(segment, warnings);
    return data;
  } catch (error) {
    if (apply) setStatus("Error", String(error.message || error));
    return null;
  }
}

function segmentMarkup(id) {
  return `
    <section class="segment-block" data-segment-id="${id}">
      <header class="segment-header"><strong>Tramo ${id}</strong><span class="segment-active-label">Activo</span><button class="ghost segment-remove" type="button" data-role="remove-segment">Eliminar</button></header>
      <label class="road-field"><span>Carretera</span><div class="input-wrap"><input data-role="road" autocomplete="off" placeholder="Ma-2210" required><button data-role="clear-road" class="clear-input" type="button" aria-label="Limpiar carretera">×</button></div><div data-role="suggestions" class="suggestions" hidden></div><p data-role="road-message" class="field-message"></p></label>
      <label><span>Sentido</span><select data-role="direction"><option value="creciente">Creciente</option><option value="decreciente">Decreciente</option><option value="ambos">Ambos</option></select></label>
      <div class="grid two"><label><span>PK inicio</span><input data-role="pk-start" type="number" step="0.001" placeholder="1.000" required></label><label><span>PK fin</span><input data-role="pk-end" type="number" step="0.001" placeholder="6.000" required></label></div>
      <div data-role="pk-warnings" class="warnings" hidden></div>
      <div class="segment-divisions" data-role="divisions"><p class="field-message">Divide visualmente este mismo recorrido sin crear otro análisis.</p><div data-role="division-list"></div><button class="ghost division-add" data-role="add-division" type="button">+ Añadir división</button><div data-role="division-warnings" class="warnings" hidden></div></div>
    </section>`;
}

function addSegment() {
  const id = nextSegmentId++;
  segmentList.insertAdjacentHTML("beforeend", segmentMarkup(id));
  const segment = segments().at(-1);
  setSegmentActive(segment);
  updateSegmentLabels();
  updateMultiSegmentMode();
  segment.querySelector('[data-role="road"]').focus();
}

function removeSegment(segment) {
  if (segments().length === 1) return;
  const wasActive = segment === activeSegment();
  const previous = segment.previousElementSibling || segmentList.querySelector(".segment-block");
  segmentRoads.delete(segment.dataset.segmentId);
  segment.remove();
  if (wasActive) setSegmentActive(previous);
  updateSegmentLabels();
  updateMultiSegmentMode();
}

segmentList.addEventListener("focusin", (event) => {
  const segment = event.target.closest(".segment-block");
  if (segment) setSegmentActive(segment);
});
segmentList.addEventListener("pointerdown", (event) => {
  const segment = event.target.closest(".segment-block");
  if (segment) setSegmentActive(segment);
});
segmentList.addEventListener("input", (event) => {
  const segment = event.target.closest(".segment-block");
  if (!segment) return;
  if (event.target.matches('[data-role="road"]')) refreshSegmentSuggestions(segment);
  if (event.target.matches('[data-role="pk-start"], [data-role="pk-end"]')) {
    delete event.target.dataset.viewerRoad;
    updateSmoothHelp();
    updatePkControls();
    try { divisionValues(segment); } catch (_) { /* se muestra el aviso junto al tramo */ }
  }
  if (event.target.matches('[data-role="division-pk"]')) { try { divisionValues(segment); } catch (_) { /* aviso ya renderizado */ } }
});
segmentList.addEventListener("change", (event) => {
  const segment = event.target.closest(".segment-block");
  if (segment && event.target.matches('[data-role="direction"]')) validateSegmentPk(segment, false);
});
segmentList.addEventListener("focusout", (event) => {
  const segment = event.target.closest(".segment-block");
  if (!segment) return;
  if (event.target.matches('[data-role="road"]')) setTimeout(() => { segment.querySelector('[data-role="suggestions"]').hidden = true; }, 180);
  if (event.target.matches('[data-role="pk-start"], [data-role="pk-end"]')) validateSegmentPk(segment, false);
});
segmentList.addEventListener("click", (event) => {
  const segment = event.target.closest(".segment-block");
  if (!segment) return;
  if (event.target.closest('[data-role="clear-road"]')) clearSegmentRoad(segment);
  if (event.target.closest('[data-role="remove-segment"]')) removeSegment(segment);
  if (event.target.closest('[data-role="add-division"]')) segment.querySelector('[data-role="division-list"]').insertAdjacentHTML("beforeend", divisionRowMarkup());
  if (event.target.closest('[data-role="remove-division"]')) { event.target.closest(".division-row")?.remove(); try { divisionValues(segment); } catch (_) { /* aviso ya renderizado */ } }
});
addSegmentButton.addEventListener("click", addSegment);

function updateSmoothHelp() {
  const q = Number(smooth.value);
  const d = Number(sample.value) || 75;
  const spec = SG_TABLE[q] || SG_TABLE[4];
  smoothValue.textContent = `${q}/10`;
  smoothHelp.textContent = q === 0
    ? "Sin suavizado."
    : `Suavizado de elevaciones. Ventana: ${spec.window} pts (${Math.round(spec.window * d)} m), polinomio ${spec.polyorder}.`;
}

function updateSlopeSmoothHelp() {
  if (!slopeSmooth || !slopeSmoothValue || !slopeSmoothHelp) return;
  const q = Number(slopeSmooth.value);
  const d = Number(sample.value) || 75;
  const spec = SG_TABLE[q] || SG_TABLE[4];
  slopeSmoothValue.textContent = `${q}/10`;
  slopeSmoothHelp.textContent = q === 0
    ? "Sin suavizado de pendientes."
    : `Suavizado de pendientes. Ventana: ${spec.window} pts (${Math.round(spec.window * d)} m), polinomio ${spec.polyorder}.`;
}

function updateSampleHelp() {
  const value = Number(sample.value);
  sampleValue.textContent = `${value} m`;
  const selected = resolutionMdt.value;
  if (selected === "5") {
    sampleHelp.textContent = value < 20
      ? "Advertencia: inferior al mínimo recomendado para MDT 5 m."
      : "Mínimo 4x tamaño del píxel del MDT.";
  } else if (selected === "25") {
    if (value < 25) {
      sampleHelp.textContent = "Advertencia fuerte: intervalo inferior al pixel MDT de 25 m.";
    } else if (value < 100) {
      sampleHelp.textContent = "Advertencia: recomendado al menos 100 m para MDT 25 m.";
    } else {
      sampleHelp.textContent = "Mínimo 4x tamaño del píxel del MDT.";
    }
  } else {
    sampleHelp.textContent = "Mínimo 4x tamaño del píxel del MDT.";
  }
  updateAdvancedSgHelp();
  updateAdvancedSlopeSgHelp();
}

function updateAnomalyHelp() {
  const value = Number(anomaly.value || 20);
  const label = value.toLocaleString("es-ES", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  anomalyValue.textContent = `${label} %`;
  anomalyHelp.textContent = `Pendientes con valor superior a ${label} % son omitidas.`;
}

function updateAlphaLabels() {
  if (alphaLocalizacion && alphaLocalizacionValue) {
    alphaLocalizacionValue.textContent = `${Math.round(Number(alphaLocalizacion.value || 0) * 100)} %`;
  }
  if (alphaPendientes && alphaPendientesValue) {
    alphaPendientesValue.textContent = `${Math.round(Number(alphaPendientes.value || 0) * 100)} %`;
  }
}

function setCartoControlVisibility(element, visible) {
  if (!element) return;
  element.hidden = !visible;
  element.style.display = visible ? "" : "none";
}

function setCartoStoredMask() {
  if (!cartoApiKey || !cartoStoredKeyAvailable || cartoApiKey.value || cartoApiKey.dataset.editing === "true") return;
  cartoApiKey.value = CARTO_API_KEY_MASK;
  cartoApiKey.dataset.storedMask = "true";
}

function clearCartoStoredMask() {
  if (!cartoApiKey || cartoApiKey.dataset.storedMask !== "true") return;
  cartoApiKey.value = "";
  delete cartoApiKey.dataset.storedMask;
}

function hideCartoApiKey() {
  cartoShowPressed = false;
  if (!cartoApiKey) return;
  cartoApiKey.type = "password";
  if (cartoApiKey.dataset.revealedStored === "true") {
    cartoApiKey.value = "";
    delete cartoApiKey.dataset.revealedStored;
    setCartoStoredMask();
  }
}

async function refreshCartoApiKeyStatus() {
  if (mapaBase?.value !== "carto_positron") return;
  try {
    const response = await fetch("/api/carto-api-key");
    if (!response.ok) throw new Error("No se pudo consultar el estado de la API key de CARTO.");
    const data = await response.json();
    if (mapaBase?.value === "carto_positron") {
      const stored = data.stored === true;
      cartoStoredKeyAvailable = stored;
      setCartoControlVisibility(cartoApiKeyStatus, stored);
      setCartoControlVisibility(olvidarCartoApiKey, stored);
      if (stored) {
        setCartoStoredMask();
      } else if (cartoApiKey?.dataset.storedMask === "true") {
        clearCartoStoredMask();
      }
    }
  } catch (_) {
    cartoStoredKeyAvailable = false;
    setCartoControlVisibility(cartoApiKeyStatus, false);
    setCartoControlVisibility(olvidarCartoApiKey, false);
  }
}

function updateMapBaseControls() {
  const isCarto = mapaBase?.value === "carto_positron";
  setCartoControlVisibility(cartoApiKeyField, isCarto);
  setCartoControlVisibility(recordarCartoApiKeyField, isCarto);
  if (cartoApiKey) {
    cartoApiKey.required = isCarto;
    if (!isCarto) {
      hideCartoApiKey();
      cartoApiKey.value = "";
      delete cartoApiKey.dataset.storedMask;
    }
  }
  if (!isCarto) {
    cartoStoredKeyAvailable = false;
    setCartoControlVisibility(cartoApiKeyStatus, false);
    setCartoControlVisibility(mostrarCartoApiKey, false);
    setCartoControlVisibility(olvidarCartoApiKey, false);
  } else {
    setCartoControlVisibility(mostrarCartoApiKey, true);
    refreshCartoApiKeyStatus();
  }
}

async function showCartoApiKey() {
  if (!cartoApiKey || mapaBase?.value !== "carto_positron") return;
  cartoShowPressed = true;
  const revealStored = cartoStoredKeyAvailable && (!cartoApiKey.value || cartoApiKey.dataset.storedMask === "true");
  if (!revealStored) {
    cartoApiKey.type = "text";
    return;
  }
  try {
    const response = await fetch("/api/carto-api-key/reveal", { method: "POST", cache: "no-store" });
    if (!response.ok) return;
    const data = await response.json();
    if (!cartoShowPressed || mapaBase?.value !== "carto_positron" || typeof data.api_key !== "string") return;
    cartoApiKey.value = data.api_key;
    delete cartoApiKey.dataset.storedMask;
    cartoApiKey.dataset.revealedStored = "true";
    cartoApiKey.type = "text";
  } finally {
    // La respuesta solo se conserva en el campo mientras el botón permanece pulsado.
  }
}

async function forgetCartoApiKey() {
  if (!cartoStoredKeyAvailable || !window.confirm("¿Olvidar la API key guardada en este equipo?")) return;
  hideCartoApiKey();
  try {
    const response = await fetch("/api/carto-api-key", { method: "DELETE", cache: "no-store" });
    const data = await response.json();
    if (!response.ok || data.stored !== false) return;
    cartoStoredKeyAvailable = false;
    if (cartoApiKey) {
      cartoApiKey.value = "";
      cartoApiKey.type = "password";
      delete cartoApiKey.dataset.storedMask;
    }
    setCartoControlVisibility(cartoApiKeyStatus, false);
    setCartoControlVisibility(olvidarCartoApiKey, false);
  } catch (_) {
    // Si no se puede borrar, se conserva el estado actual de la interfaz.
  }
}

function pkSliderValue(input) {
  if (!input) return null;
  const index = Math.max(0, Math.min(PK_INTERVALS.length - 1, Number(input.value || 0)));
  return PK_INTERVALS[index] || PK_INTERVALS[0];
}

function setPkSliderToValue(input, value) {
  if (!input) return;
  const index = PK_INTERVALS.indexOf(Number(value));
  input.value = String(index >= 0 ? index : 0);
}

function updatePkSliderLabels() {
  const symbol = pkSliderValue(pkSimboloCada);
  let label = pkSliderValue(pkEtiquetaCada);
  if (label < symbol) {
    setPkSliderToValue(pkEtiquetaCada, symbol);
    label = symbol;
  }
  if (pkSimboloCadaValue) pkSimboloCadaValue.textContent = `${symbol} km`;
  if (pkEtiquetaCadaValue) pkEtiquetaCadaValue.textContent = `${label} km`;
}

function updatePkControls() {
  if (!pkModo || !pkManualControls) return;
  const manual = pkModo.value === "manual";
  if (pkSimboloCada) pkSimboloCada.disabled = !manual;
  if (pkEtiquetaCada) pkEtiquetaCada.disabled = !manual;
  pkManualControls.classList.toggle("is-disabled", !manual);
  updatePkSliderLabels();
  if (pkAutoHelp) {
    pkAutoHelp.textContent = pkModo.value === "automatico"
      ? `Automático: ${automaticPkText()}`
      : pkModo.value === "no_mostrar"
        ? "No se pintarán símbolos ni etiquetas de PK."
        : "Manual: símbolo y etiqueta se configuran por separado.";
  }
}

function automaticPkText() {
  const start = numberOrNull(document.querySelector("#pkInicio").value);
  const end = numberOrNull(document.querySelector("#pkFin").value);
  if (start === null || end === null) return "símbolo y etiqueta según longitud del tramo.";
  const length = Math.abs(end - start);
  let symbol = 50;
  let label = 100;
  if (length <= 10) [symbol, label] = [1, 1];
  else if (length <= 30) [symbol, label] = [1, 5];
  else if (length <= 80) [symbol, label] = [5, 10];
  else if (length <= 150) [symbol, label] = [10, 25];
  else if (length <= 300) [symbol, label] = [25, 50];
  return `símbolo cada ${symbol} km · etiqueta cada ${label} km.`;
}

function updateAdvancedSgHelp() {
  if (!sgWindow || !sgWindowValue || !sgPolyorder || !sgPolyorderValue) return;
  const windowPoints = Number(sgWindow.value || 9);
  const d = Number(sample.value) || 75;
  const maxPoly = Math.max(1, Math.min(4, windowPoints - 1));
  let visual = Number(sgPolyorder.value || 3);
  let poly = 5 - visual;
  if (poly > maxPoly) {
    poly = maxPoly;
    sgPolyorder.value = String(5 - poly);
  }
  if (poly >= windowPoints) {
    poly = Math.max(1, windowPoints - 1);
    visual = 5 - poly;
    sgPolyorder.value = String(visual);
  }
  sgWindowValue.textContent = `${windowPoints} puntos · ${Math.round(windowPoints * d)} m`;
  sgPolyorderValue.textContent = `Polinomio ${poly}`;
}

function sgPolyorderReal() {
  if (!sgPolyorder) return null;
  return 5 - Number(sgPolyorder.value || 3);
}

function sgSlopePolyorderReal() {
  if (!sgSlopePolyorder) return null;
  return 5 - Number(sgSlopePolyorder.value || 3);
}

function updateAdvancedSgState() {
  if (!sgAdvanced || !sgAdvancedControls || !smooth) return;
  const enabled = sgAdvanced.checked;
  smooth.disabled = enabled;
  sgAdvancedControls.classList.toggle("is-disabled", !enabled);
  if (sgWindow) sgWindow.disabled = !enabled;
  if (sgPolyorder) sgPolyorder.disabled = !enabled;
  updateAdvancedSgHelp();
}

function updateAdvancedSlopeSgHelp() {
  if (!sgSlopeWindow || !sgSlopeWindowValue || !sgSlopePolyorder || !sgSlopePolyorderValue) return;
  const windowPoints = Number(sgSlopeWindow.value || 13);
  const d = Number(sample.value) || 75;
  const maxPoly = Math.max(1, Math.min(4, windowPoints - 1));
  let visual = Number(sgSlopePolyorder.value || 3);
  let poly = 5 - visual;
  if (poly > maxPoly) {
    poly = maxPoly;
    sgSlopePolyorder.value = String(5 - poly);
  }
  if (poly >= windowPoints) {
    poly = Math.max(1, windowPoints - 1);
    visual = 5 - poly;
    sgSlopePolyorder.value = String(visual);
  }
  sgSlopeWindowValue.textContent = `${windowPoints} puntos · ${Math.round(windowPoints * d)} m`;
  sgSlopePolyorderValue.textContent = `Polinomio ${poly}`;
}

function updateAdvancedSlopeSgState() {
  if (!sgSlopeAdvanced || !sgSlopeAdvancedControls || !slopeSmooth) return;
  const enabled = sgSlopeAdvanced.checked;
  slopeSmooth.disabled = enabled;
  sgSlopeAdvancedControls.classList.toggle("is-disabled", !enabled);
  if (sgSlopeWindow) sgSlopeWindow.disabled = !enabled;
  if (sgSlopePolyorder) sgSlopePolyorder.disabled = !enabled;
  updateAdvancedSlopeSgHelp();
}

function payloadFromForm() {
  const data = new FormData(form);
  const tramos = segments().map((segment) => {
    const road = segmentRoad(segment);
    return {
      carretera: road?.carretera || segment.querySelector('[data-role="road"]').value.trim(),
      pk_inicio: Number(segment.querySelector('[data-role="pk-start"]').value),
      pk_fin: Number(segment.querySelector('[data-role="pk-end"]').value),
      sentido: segment.querySelector('[data-role="direction"]').value || "creciente",
      divisiones_pk: divisionValues(segment),
    };
  });
  const first = tramos[0];
  const elevAdvanced = data.get("suavizado_elevaciones_avanzado") === "on";
  const slopeAdvanced = data.get("suavizado_pendientes_avanzado") === "on";
  const elevSmooth = Number(data.get("suavizado_elevaciones") || 4);
  const slopeSmoothValueForm = Number(data.get("suavizado_pendientes") || 4);
  const cartoApiKeyValue = cartoApiKey?.dataset.storedMask === "true" ? "" : String(data.get("carto_api_key") || "");
  return {
    carretera: first.carretera,
    pk_inicio: first.pk_inicio,
    pk_fin: first.pk_fin,
    sentido: first.sentido,
    ...(tramos.length > 1 || first.divisiones_pk.length ? { tramos } : {}),
    generar_mapa_localizacion: boolField(data, "generar_mapa_localizacion"),
    generar_mapa_pendientes: boolField(data, "generar_mapa_pendientes"),
    generar_perfil: boolField(data, "generar_perfil"),
    generar_datos_auxiliares: boolField(data, "generar_datos_auxiliares"),
    generar_todo: false,
    resolucion_mdt: String(data.get("resolucion_mdt") || "5"),
    intervalo_muestreo_m: numberOrNull(data.get("intervalo_muestreo_m")) || 75,
    longitud_intervalo_pendiente_m: numberOrNull(data.get("longitud_intervalo_pendiente_m")),
    suavizado: elevSmooth,
    suavizado_modo: elevAdvanced ? "avanzado" : "simple",
    sg_window_puntos: elevAdvanced ? numberOrNull(data.get("sg_elevaciones_window_puntos")) : null,
    sg_polyorder: elevAdvanced ? sgPolyorderReal() : null,
    sg_polyorder_slider_visual: elevAdvanced ? numberOrNull(data.get("sg_elevaciones_polyorder_visual")) : null,
    suavizado_elevaciones: elevSmooth,
    suavizado_elevaciones_modo: elevAdvanced ? "avanzado" : "simple",
    sg_elevaciones_window_puntos: elevAdvanced ? numberOrNull(data.get("sg_elevaciones_window_puntos")) : null,
    sg_elevaciones_polyorder: elevAdvanced ? sgPolyorderReal() : null,
    sg_elevaciones_polyorder_slider_visual: elevAdvanced ? numberOrNull(data.get("sg_elevaciones_polyorder_visual")) : null,
    suavizado_pendientes: slopeSmoothValueForm,
    suavizado_pendientes_modo: slopeAdvanced ? "avanzado" : "simple",
    sg_pendientes_window_puntos: slopeAdvanced ? numberOrNull(data.get("sg_pendientes_window_puntos")) : null,
    sg_pendientes_polyorder: slopeAdvanced ? sgSlopePolyorderReal() : null,
    sg_pendientes_polyorder_slider_visual: slopeAdvanced ? numberOrNull(data.get("sg_pendientes_polyorder_visual")) : null,
    umbral_pendiente_anomala_pct: Number(data.get("umbral_pendiente_anomala_pct") || 20),
    modo_eje_y: String(data.get("modo_eje_y") || "cero"),
    mostrar_linea_muestreada_elevaciones: boolField(data, "mostrar_linea_muestreada_elevaciones"),
    mostrar_anotaciones_curvas_nivel: boolField(data, "mostrar_anotaciones_curvas_nivel"),
    vias_fondo_modo: String(data.get("vias_fondo_modo") || "todas"),
    mapa_base: String(data.get("mapa_base") || "ign_gris"),
    carto_api_key: cartoApiKeyValue,
    recordar_carto_api_key: boolField(data, "recordar_carto_api_key"),
    pk_modo: String(data.get("pk_modo") || "automatico"),
    pk_simbolo_cada: pkSliderValue(pkSimboloCada),
    pk_etiqueta_cada: pkSliderValue(pkEtiquetaCada),
    pintar_pks: String(data.get("pk_modo") || "automatico") !== "no_mostrar",
    alpha_elev_localizacion: Number(data.get("alpha_elev_localizacion") || 0.34),
    alpha_elev_pendientes: Number(data.get("alpha_elev_pendientes") || 0.46),
  };
}

function fileKind(item) {
  const name = item.name.toLowerCase();
  if (name.endsWith(".zip")) return "zip";
  if (name.startsWith("mapa_") && name.endsWith(".png")) return "mapas";
  if (name.startsWith("perfil_longitudinal") && name.endsWith(".png")) return "perfiles";
  return "datos";
}

function accordion(title, html, open = false) {
  return `<details ${open ? "open" : ""}><summary>${title}</summary><div class="accordion-body">${html}</div></details>`;
}

function previewImages(items) {
  if (!items.length) return "<p class='empty'>Sin previsualizaciones PNG.</p>";
  return items.map((item) => `
    <figure class="preview">
      <img src="${item.url}" loading="lazy" alt="${item.name}">
      <figcaption><a href="${item.url}" target="_blank">${item.name}</a></figcaption>
    </figure>
  `).join("");
}

function dataLinks(items) {
  if (!items.length) return "<p class='empty'>Sin datos auxiliares.</p>";
  return items.map((item) => `<a href="${item.url}" target="_blank">${item.name}</a>`).join("");
}

function numberText(value, suffix = "", digits = 1) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "Sin dato";
  return `${n.toLocaleString("es-ES", { maximumFractionDigits: digits, minimumFractionDigits: digits })}${suffix}`;
}

function pkText(value) {
  const n = Number(value);
  return Number.isFinite(n) ? formatPk(n) : "Sin dato";
}

function metric(label, value) {
  return `<div class="metric"><span>${label}</span><strong>${value}</strong></div>`;
}

function renderAnomalyRanges(anomalias) {
  const ranges = anomalias.detalle_rangos_anomalos || [];
  if (!ranges.length) return "<p class='summary-muted'>Sin pendientes aplanadas.</p>";
  const rows = ranges.map((item) => `
    <li>
      <span>PK ${pkText(item.pk_inicio)} a PK ${pkText(item.pk_fin)} · ${Number(item.n_puntos_muestreo || 0)} puntos · ${Number(item.n_segmentos_mapa || 0)} segmentos · máx. suavizada ${numberText(item.pendiente_suavizada_max_pct ?? item.pendiente_bruta_max_pct, " %", 1)} en PK ${pkText(item.pk_pendiente_suavizada_max ?? item.pk_pendiente_bruta_max)}</span>
    </li>
  `).join("");
  return `
    <div class="anomaly-ranges">
      <h4>Pendientes aplanadas</h4>
      <ul>${rows}</ul>
    </div>
  `;
}

function smoothParamText(params, prefix, legacy = false) {
  const mode = params[`${prefix}_modo`] || (legacy ? params.suavizado_modo : "simple");
  if (mode === "avanzado") {
    const windowPoints = params[`sg_${prefix.replace("suavizado_", "")}_window_puntos`] || (legacy ? params.sg_window_puntos : "?");
    const polyorder = params[`sg_${prefix.replace("suavizado_", "")}_polyorder`] || (legacy ? params.sg_polyorder : "?");
    return `Avanzado · ${windowPoints} puntos · polinomio ${polyorder}`;
  }
  return `${params[prefix] ?? (legacy ? params.suavizado : 4) ?? 4}/10`;
}

function renderSummaryCard(data) {
  const meta = data.metadata || {};
  const scopes = meta.scopes?.length ? meta.scopes : [{}];
  const params = meta.parametros || {};
  const alt = meta.altimetria || scopes[0]?.altimetria || {};
  const mdt = meta.mdt || {};
  const usedResolution = alt.resolucion_mdt_usada ?? mdt.resolucion_m ?? mdt.resolucion_usada;
  const paramsHtml = `
    <section class="summary-card compact">
      <div>
        <h3>Parámetros empleados</h3>
        <p>Configuración usada en esta generación.</p>
      </div>
      <div class="metrics-grid">
        ${metric("Suavizado de elevaciones", smoothParamText(params, "suavizado_elevaciones", true))}
        ${metric("Suavizado de pendientes", smoothParamText(params, "suavizado_pendientes"))}
        ${metric("Muestreo altimétrico", numberText(params.intervalo_muestreo_m ?? 75, " m", 0))}
        ${metric("Segmento pendiente", params.longitud_intervalo_pendiente_m ? numberText(params.longitud_intervalo_pendiente_m, " m", 0) : "Auto")}
        ${metric("Umbral de anomalía", numberText(params.umbral_pendiente_anomala_pct ?? 20, " %", 1))}
        ${metric("Fuente altimétrica usada", alt.fuente_altimetrica_usada_label || "Sin dato")}
        ${metric("Resolución MDT solicitada", `${alt.resolucion_mdt_solicitada ?? params.resolucion_mdt ?? "5"} m`)}
        ${metric("Resolución MDT usada", usedResolution ? `${usedResolution} m` : "No disponible")}
        ${metric("Estado MDT", alt.estado_mdt || (mdt.path ? "Disponible" : "No disponible"))}
      </div>
    </section>
  `;
  const scopesHtml = scopes.map((scope) => {
    const tramo = scope.tramo || {};
    const perfil = scope.perfil || {};
    const anomalias = scope.anomalias || perfil.anomalias || {};
    return `
      <section class="summary-card">
        <div>
          <h3>Resumen del tramo</h3>
          <p>${tramo.carretera || params.carretera || ""} · ${tramo.sentido || params.sentido || ""}</p>
        </div>
        <div class="metrics-grid">
          ${metric("Vía", tramo.carretera || params.carretera || "Sin dato")}
          ${metric("Sentido", tramo.sentido || params.sentido || "Sin dato")}
          ${metric("PK inicio", pkText(tramo.pk_inicio))}
          ${metric("PK fin", pkText(tramo.pk_fin))}
          ${metric("Longitud", numberText(tramo.longitud_m, " m", 0))}
          ${metric("Rango altitudinal", numberText(perfil.rango_altitudinal_m, " m", 1))}
          ${metric("Altitud mínima", `${numberText(perfil.altitud_min_m, " m", 1)} · PK ${pkText(perfil.altitud_min_pk)}`)}
          ${metric("Altitud máxima", `${numberText(perfil.altitud_max_m, " m", 1)} · PK ${pkText(perfil.altitud_max_pk)}`)}
          ${metric("Pendiente máxima", `${numberText(perfil.pendiente_max_pct, " %", 1)} · PK ${pkText(perfil.pendiente_max_pk)}`)}
          ${metric("Pendiente mínima", `${numberText(perfil.pendiente_min_pct, " %", 1)} · PK ${pkText(perfil.pendiente_min_pk)}`)}
          ${metric("Pendiente media", numberText(perfil.pendiente_media_pct, " %", 1))}
          ${metric("Pendiente media absoluta", numberText(perfil.pendiente_media_abs_pct, " %", 1))}
        </div>
        ${renderAnomalyRanges(anomalias)}
      </section>
    `;
  }).join("");
  return scopesHtml + paramsHtml;
}

function renderZipButtons(zipDownloadsData) {
  zipDownloads.innerHTML = "";
  const entries = [
    ["mapas", "Descargar mapas"],
    ["perfiles", "Descargar perfiles"],
    ["datos", "Descargar datos auxiliares"],
  ];
  for (const [key, label] of entries) {
    const item = zipDownloadsData?.[key];
    if (!item) continue;
    const link = document.createElement("a");
    link.href = item.url;
    link.textContent = label;
    link.className = "zip-button";
    zipDownloads.appendChild(link);
  }
}

function renderResults(data) {
  const downloads = data.downloads || [];
  const mapImages = downloads.filter((item) => fileKind(item) === "mapas");
  const profileImages = downloads.filter((item) => fileKind(item) === "perfiles");
  const profilesWithSlope = profileImages.filter((item) => item.name.toLowerCase().includes("_con_pendiente"));
  const profilesWithoutSlope = profileImages.filter((item) => item.name.toLowerCase().includes("_sin_pendiente"));
  const otherProfiles = profileImages.filter((item) => !profilesWithSlope.includes(item) && !profilesWithoutSlope.includes(item));
  const dataItems = downloads.filter((item) => fileKind(item) === "datos");
  const info = `
    <div class="run-info">
      <strong>Proceso completado</strong>
      <span>Salida: ${data.job_id}</span>
    </div>
  `;
  resultsBox.innerHTML = info
    + renderSummaryCard(data)
    + accordion("Mapas generados", previewImages(mapImages), true)
    + accordion("Perfil longitudinal con pendiente", previewImages(profilesWithSlope.length ? profilesWithSlope : otherProfiles), true)
    + accordion("Perfil longitudinal sin pendiente", previewImages(profilesWithoutSlope), false)
    + accordion("Datos auxiliares y metadatos", dataLinks(dataItems), false);
  renderZipButtons(data.zip_downloads);
  statusBox.insertAdjacentHTML("beforeend", '<p><button type="button" class="ghost" id="backToViewer">Volver al visor</button></p>');
  document.querySelector("#backToViewer")?.addEventListener("click", () => showRightPanel("viewer"));
  window.roadViewer?.setHasResults(true);
  showRightPanel("results");
}

if (openHelp) openHelp.addEventListener("click", () => openHelpPanel(null, openHelp));
if (closeHelp) closeHelp.addEventListener("click", closeHelpPanel);
if (helpOverlay) {
  helpOverlay.addEventListener("click", (event) => {
    if (event.target === helpOverlay) closeHelpPanel();
  });
}
document.querySelectorAll(".parameter-help").forEach((button) => {
  button.addEventListener("click", () => openHelpPanel(button.dataset.helpTarget, button));
});
document.addEventListener("keydown", (event) => {
  if (!helpOverlay || helpOverlay.hidden) return;
  if (event.key === "Escape") {
    closeHelpPanel();
    return;
  }
  if (event.key !== "Tab") return;
  const focusable = helpFocusableElements();
  if (!focusable.length) {
    event.preventDefault();
    helpPanel.focus();
    return;
  }
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && (document.activeElement === first || document.activeElement === helpPanel)) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
});
smooth.addEventListener("input", updateSmoothHelp);
if (slopeSmooth) slopeSmooth.addEventListener("input", updateSlopeSmoothHelp);
sample.addEventListener("input", () => {
  updateSampleHelp();
  updateSmoothHelp();
  updateSlopeSmoothHelp();
});
resolutionMdt.addEventListener("change", updateSampleHelp);
anomaly.addEventListener("input", updateAnomalyHelp);
if (pkModo) pkModo.addEventListener("change", updatePkControls);
if (sgAdvanced) sgAdvanced.addEventListener("change", updateAdvancedSgState);
if (sgWindow) sgWindow.addEventListener("input", updateAdvancedSgHelp);
if (sgPolyorder) sgPolyorder.addEventListener("input", updateAdvancedSgHelp);
if (sgSlopeAdvanced) sgSlopeAdvanced.addEventListener("change", updateAdvancedSlopeSgState);
if (sgSlopeWindow) sgSlopeWindow.addEventListener("input", updateAdvancedSlopeSgHelp);
if (sgSlopePolyorder) sgSlopePolyorder.addEventListener("input", updateAdvancedSlopeSgHelp);
if (alphaLocalizacion) alphaLocalizacion.addEventListener("input", updateAlphaLabels);
if (alphaPendientes) alphaPendientes.addEventListener("input", updateAlphaLabels);
if (mapaBase) mapaBase.addEventListener("change", updateMapBaseControls);
if (cartoApiKey) {
  cartoApiKey.addEventListener("focus", () => {
    cartoApiKey.dataset.editing = "true";
    clearCartoStoredMask();
  });
  cartoApiKey.addEventListener("blur", () => {
    delete cartoApiKey.dataset.editing;
    if (!cartoShowPressed) setCartoStoredMask();
  });
}
if (mostrarCartoApiKey) {
  mostrarCartoApiKey.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    showCartoApiKey();
  });
  for (const eventName of ["pointerup", "pointercancel", "pointerleave", "lostpointercapture", "blur"]) {
    mostrarCartoApiKey.addEventListener(eventName, hideCartoApiKey);
  }
}
window.addEventListener("pointerup", hideCartoApiKey);
window.addEventListener("blur", hideCartoApiKey);
if (olvidarCartoApiKey) olvidarCartoApiKey.addEventListener("click", forgetCartoApiKey);
if (pkSimboloCada && pkEtiquetaCada) {
  pkSimboloCada.addEventListener("input", updatePkControls);
  pkEtiquetaCada.addEventListener("input", updatePkControls);
}
form.addEventListener("submit", async (event) => {
  event.preventDefault();
  resultsBox.innerHTML = "";
  zipDownloads.innerHTML = "";
  showRightPanel("generating");
  loadingStartedAt = performance.now();
  lastProgress = { fase_indice: 1, fases_total: PROGRESS_PHASES.length };
  renderLoading(lastProgress);
  stopLoadingClock();
  loadingTimer = setInterval(() => renderLoading(lastProgress || { fase_indice: 1, fases_total: PROGRESS_PHASES.length }), 1000);
  const button = form.querySelector(".primary");
  button.disabled = true;
  try {
    for (const segment of segments()) {
      await ensureSegmentRoad(segment);
      await validateSegmentPk(segment, true);
      divisionValues(segment);
    }
    const response = await fetch("/generar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payloadFromForm()),
    });
    const job = await response.json();
    if (!response.ok) throw new Error(job.detail || "Error de generacion");
    let finalResult = null;
    while (!finalResult) {
      await new Promise((resolve) => setTimeout(resolve, 750));
      const progressResponse = await fetch(`/api/progreso/${job.job_id}`);
      const progress = await progressResponse.json();
      if (!progressResponse.ok) throw new Error(progress.detail || "No se pudo consultar el progreso");
      lastProgress = progress;
      renderLoading(progress);
      if (progress.estado === "completado") {
        finalResult = progress.resultado;
      } else if (progress.estado === "error") {
        throw new Error(progress.error || progress.detalle || "Error de generacion");
      }
    }
    stopLoadingClock();
    lastProgress = null;
    setStatus("Proceso completado", `Salida: ${finalResult.job_id}`);
    renderResults(finalResult);
  } catch (error) {
    stopLoadingClock();
    lastProgress = null;
    setStatus("Error", String(error.message || error));
  } finally {
    button.disabled = false;
  }
});

loadRoads().catch(() => {});
updateSampleHelp();
updateSmoothHelp();
updateSlopeSmoothHelp();
updateAnomalyHelp();
updatePkControls();
updateAdvancedSgState();
updateAdvancedSlopeSgState();
updateAlphaLabels();
updateMapBaseControls();
updateMultiSegmentMode();
showRightPanel("viewer");
