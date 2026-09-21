const form = document.querySelector("#generationForm");
const statusBox = document.querySelector("#status");
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

function setStatus(title, text) {
  statusBox.replaceChildren();
  const heading = document.createElement("h2");
  heading.textContent = title;
  const paragraph = document.createElement("p");
  paragraph.textContent = text;
  statusBox.append(heading, paragraph);
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
}

function safeOutputUrl(value) {
  const url = String(value || "");
  return /^\/outputs\/[A-Za-z0-9_.-]+\/[^?#]+$/.test(url) ? url : "#";
}

function setParagraphs(box, items) {
  box.replaceChildren(...items.filter(Boolean).map((item) => {
    const paragraph = document.createElement("p");
    paragraph.textContent = item;
    return paragraph;
  }));
}

function addBackToViewerAction() {
  const action = document.createElement("p");
  const button = document.createElement("button");
  button.type = "button";
  button.className = "ghost";
  button.textContent = "Volver al visor";
  button.addEventListener("click", () => showRightPanel("viewer"));
  action.appendChild(button);
  statusBox.appendChild(action);
}

function setGenerationError(message) {
  setStatus("Error", message);
  addBackToViewerAction();
}

function showRightPanel(state) {
  const resultsVisible = state !== "viewer";
  rightPanel.classList.toggle("show-results", resultsVisible);
  if (state === "viewer") window.roadViewer?.show();
}

window.showViewerResults = () => showRightPanel("results");
window.showRoadViewer = () => showRightPanel("viewer");

window.setRoadFromViewer = async (carretera, pkInicio = null, pkFin = null) => {
  const segment = segmentApi.activeSegment();
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
  await segmentApi.loadRoads();
  const road = segmentApi.roadExact(carretera);
  if (!road) throw new Error("Carretera no encontrada");
  segmentApi.selectSegmentRoad(segment, road);
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
  await segmentApi.validateSegmentPk(segment, true);
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
          <p>${escapeHtml(phase)}</p>
        </div>
        <strong>${formatElapsed(elapsed)}</strong>
      </div>
      <div class="progress-track"><div style="width:${percent}%"></div></div>
      <ol class="progress-steps">${details}</ol>
      <p class="loading-note">${escapeHtml(job.detalle || "La herramienta está componiendo mapas, perfil y archivos de descarga.")}</p>
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
const controls = window.createAnalysisControls({
  SG_TABLE,
  PK_INTERVALS,
  numberOrNull,
  elements: {
    alphaLocalizacion, alphaLocalizacionValue, alphaPendientes, alphaPendientesValue,
    anomaly, anomalyHelp, anomalyValue, cartoApiKey, cartoApiKeyField,
    cartoApiKeyStatus, mapaBase, mostrarCartoApiKey, olvidarCartoApiKey,
    pkAutoHelp, pkEtiquetaCada, pkEtiquetaCadaValue, pkManualControls, pkModo,
    pkSimboloCada, pkSimboloCadaValue, recordarCartoApiKeyField, resolutionMdt,
    sample, sampleHelp, sampleValue, sgAdvanced, sgAdvancedControls, sgPolyorder,
    sgPolyorderValue, sgSlopeAdvanced, sgSlopeAdvancedControls, sgSlopePolyorder,
    sgSlopePolyorderValue, sgSlopeWindow, sgSlopeWindowValue, sgWindow, sgWindowValue,
    slopeSmooth, slopeSmoothHelp, slopeSmoothValue, smooth, smoothHelp, smoothValue,
  },
});
const {
  clearCartoStoredMask, forgetCartoApiKey, hideCartoApiKey, pkSliderValue,
  restoreCartoStoredMask,
  setCartoStoredMask, sgPolyorderReal, sgSlopePolyorderReal, showCartoApiKey,
  updateAdvancedSgHelp, updateAdvancedSgState, updateAdvancedSlopeSgHelp,
  updateAdvancedSlopeSgState, updateAlphaLabels, updateAnomalyHelp,
  updateMapBaseControls, updatePkControls, updateSampleHelp, updateSlopeSmoothHelp,
  updateSmoothHelp,
} = controls;
const segmentApi = window.createAnalysisSegments({
  segmentList, addSegmentButton, multiSegmentWarning, pendingMapCheckbox,
  normalizeRoad, normalizedPrefix, numberOrNull, formatPk, setParagraphs,
  setStatus, updateSmoothHelp, updatePkControls,
});
const resultsApi = window.createAnalysisResults({
  addBackToViewerAction, escapeHtml, formatPk, resultsBox, safeOutputUrl,
  showRightPanel, zipDownloads,
});



function payloadFromForm() {
  const data = new FormData(form);
  const tramos = segmentApi.segments().map((segment) => {
    const road = segmentApi.segmentRoad(segment);
    return {
      carretera: road?.carretera || segment.querySelector('[data-role="road"]').value.trim(),
      pk_inicio: Number(segment.querySelector('[data-role="pk-start"]').value),
      pk_fin: Number(segment.querySelector('[data-role="pk-end"]').value),
      sentido: segment.querySelector('[data-role="direction"]').value || "creciente",
      divisiones_pk: segmentApi.divisionValues(segment),
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
    restoreCartoStoredMask();
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
    for (const segment of segmentApi.segments()) {
      await segmentApi.ensureSegmentRoad(segment);
      await segmentApi.validateSegmentPk(segment, true);
      segmentApi.divisionValues(segment);
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
    resultsApi.renderResults(finalResult);
  } catch (error) {
    stopLoadingClock();
    lastProgress = null;
    setGenerationError(String(error.message || error));
  } finally {
    button.disabled = false;
  }
});

segmentApi.loadRoads().catch(() => {});
updateSampleHelp();
updateSmoothHelp();
updateSlopeSmoothHelp();
updateAnomalyHelp();
updatePkControls();
updateAdvancedSgState();
updateAdvancedSlopeSgState();
updateAlphaLabels();
updateMapBaseControls();
segmentApi.updateMultiSegmentMode();
showRightPanel("viewer");
