/* PK overlay, bulk locator and in-memory export helpers for the Leaflet viewer. */
(() => {
  "use strict";

  const VIEWER_PK_INTERVALS = Object.freeze([1, 5, 10, 25, 50, 100, 250]);
  const VIEWER_PK_MAX_SYMBOLS = 650;
  const VIEWER_PK_MAX_LABELS = 90;
  function pkDensityForZoom(zoom) { if (zoom >= 15) return { symbol: 1, label: 1 }; if (zoom >= 14) return { symbol: 1, label: 5 }; if (zoom >= 12) return { symbol: 5, label: 10 }; if (zoom >= 10) return { symbol: 10, label: 25 }; if (zoom >= 8) return { symbol: 25, label: 50 }; if (zoom >= 6) return { symbol: 50, label: 100 }; return { symbol: 100, label: 250 }; }
  const greatestCommonDivisor = (left, right) => { let a = Math.abs(left); let b = Math.abs(right); while (b) [a, b] = [b, a % b]; return a; };
  // The BBOX response is a source set, not the final density.  It must retain
  // every later symbol and label rung (10/25 => 5, 100/250 => 50).
  const sourceIntervalForZoom = (zoom) => { const density = pkDensityForZoom(zoom); return greatestCommonDivisor(density.symbol, density.label); };
  const intervalForZoom = sourceIntervalForZoom;
  const nextPkInterval = (interval) => VIEWER_PK_INTERVALS[Math.min(VIEWER_PK_INTERVALS.length - 1, Math.max(0, VIEWER_PK_INTERVALS.indexOf(interval)) + 1)];
  const pkMatchesInterval = (item, interval) => Math.abs(Number(item.pk) / interval - Math.round(Number(item.pk) / interval)) < .001;
  function balancedPkDensity(items, zoom) { let density = pkDensityForZoom(zoom); while (items.filter((item) => pkMatchesInterval(item, density.symbol)).length > VIEWER_PK_MAX_SYMBOLS && density.symbol < 250) density = { ...density, symbol: nextPkInterval(density.symbol), label: Math.max(density.label, nextPkInterval(density.symbol)) }; while (items.filter((item) => pkMatchesInterval(item, density.label)).length > VIEWER_PK_MAX_LABELS && density.label < 250) density = { ...density, label: nextPkInterval(density.label) }; return density; }
  const pkKey = (item) => `${normalRoad(item.carretera)}|${Number(item.pk).toFixed(3)}|${Number(item.lon).toFixed(7)}|${Number(item.lat).toFixed(7)}`;
  const pkCompare = (left, right) => pkKey(left).localeCompare(pkKey(right));
  function selectEvenly(items, limit, required = []) {
    const ordered = [...items].sort(pkCompare);
    if (ordered.length <= limit) return ordered;
    const byKey = new Map(ordered.map((item) => [pkKey(item), item]));
    const retained = [...new Map(required.map((item) => [pkKey(item), byKey.get(pkKey(item))]).filter(([, item]) => item)).values()];
    if (retained.length >= limit) return retained.slice(0, limit).sort(pkCompare);
    const optional = ordered.filter((item) => !retained.some((chosen) => pkKey(chosen) === pkKey(item)));
    const remaining = limit - retained.length;
    const sampled = Array.from({ length: remaining }, (_, index) => optional[Math.floor(index * optional.length / remaining)]);
    return [...retained, ...sampled].sort(pkCompare);
  }
  function overlaySelection(items, zoom) {
    const density = balancedPkDensity(items, zoom);
    const labelItems = selectEvenly(items.filter((item) => pkMatchesInterval(item, density.label)), VIEWER_PK_MAX_LABELS);
    // A label may fall on a rung that is not a multiple of the symbol rung
    // (10/25 and 100/250). Include it in the actual marker pool as well.
    const symbolPool = [...new Map([...items.filter((item) => pkMatchesInterval(item, density.symbol)), ...labelItems].map((item) => [pkKey(item), item])).values()];
    const symbolItems = selectEvenly(symbolPool, VIEWER_PK_MAX_SYMBOLS, labelItems);
    return { density, symbolItems, labelItems };
  }
  const normalRoad = (value) => String(value || "").trim().toUpperCase().replace(/[\s_-]+/g, "");
  const pkText = (pk) => { const metres = Math.round(Number(pk) * 1000); return `${Math.floor(metres / 1000)}+${String(Math.abs(metres % 1000)).padStart(3, "0")}`; };
  const parseValue = (text) => {
    const value = String(text).trim().replace(",", ".");
    if (value.includes("+")) { const [km, metres] = value.split("+"); if (!/^[-+]?\d+$/.test(km) || !/^\d{1,3}$/.test(metres)) throw new Error("PK no válido"); return Number(km) + Number(metres) / 1000; }
    const result = Number(value); if (!Number.isFinite(result)) throw new Error("PK no válido"); return result;
  };
  function parseText(text) {
    const valid = [], errors = [];
    String(text || "").split(/\r?\n/).forEach((raw, index) => {
      if (!raw.trim()) return;
      const match = raw.match(/^\s*([^,;\s]+)\s*(?:[,;]|\s+)\s*([-+]?\d+(?:[.,]\d+)?(?:\+\d{1,3})?)\s*$/);
      if (!match) { errors.push({ line: index + 1, text: raw, error: "Formato no reconocido." }); return; }
      try { valid.push({ carretera: match[1], pk: parseValue(match[2]) }); } catch (_) { errors.push({ line: index + 1, text: raw, error: "PK no válido." }); }
    });
    return { valid, errors };
  }

  window.createRoadPkTools = ({ map, formElement, setResult, escapeHtml, drawPoint, clearInteractionGraphics, focusMapPoint, usePk, showNotice }) => {
    const overlay = L.layerGroup();
    const selectedRoadsLayer = L.layerGroup().addTo(map);
    const markers = L.layerGroup().addTo(map);
    let selectedRoads = [];
    let enabled = true;
    let timer = null;
    let controller = null;
    let requestId = 0;
    let roadsController = null;
    let roadsRequestId = 0;
    const history = new Map();

    const historyKey = (item) => `${normalRoad(item.carretera)}|${Math.round(Number(item.pk) * 1000)}|${Number(item.punto.lat).toFixed(6)}|${Number(item.punto.lon).toFixed(6)}`;
    const addHistory = (item) => { if (!item?.punto) return; history.set(historyKey(item), { ...item, selected: true }); updateExportButton(); };
    const escapeAttr = (value) => escapeHtml(value);
    function updateExportButton() { const button = document.querySelector("#viewerExportButton"); if (button) button.disabled = history.size === 0; }
    function pkIcon(item, showLabel) {
      // rotacion was verified against the PK_2023 geometry as a screen-space,
      // undirected road angle. Tangent remains the safe fallback for nulls.
      const rotation = Number.isFinite(Number(item.rotacion)) ? item.rotacion : (Number.isFinite(Number(item.rotacion_tangente)) ? item.rotacion_tangente : 0);
      const tickAngle = rotation + 90;
      return L.divIcon({ className: "pk-marker", iconSize: [1, 1], iconAnchor: [0, 0], html: `<span class="pk-tick" style="transform:rotate(${tickAngle.toFixed(1)}deg)"></span>${showLabel ? `<span class="pk-callout"></span><span class="pk-label">${escapeHtml(item.pk_formateado)}</span>` : ""}` });
    }
    function drawOverlay(items) {
      overlay.clearLayers();
      const selection = overlaySelection(items, map.getZoom());
      const { density, symbolItems, labelItems } = selection;
      const labelKeys = new Set(labelItems.map(pkKey));
      const occupied = []; let candidates = 0; let placed = 0;
      symbolItems.forEach((item) => {
        const point = map.latLngToContainerPoint([item.lat, item.lon]);
        const labelCandidate = labelKeys.has(pkKey(item)); if (labelCandidate) candidates += 1;
        const box = [point.x + 28, point.y - 40, point.x + 28 + Math.min(96, Math.max(46, item.pk_formateado.length * 7 + 12)), point.y - 18];
        const showLabel = labelCandidate && box[0] > 0 && box[1] > 0 && box[2] < map.getSize().x && !occupied.some((other) => box[0] < other[2] && box[2] > other[0] && box[1] < other[3] && box[3] > other[1]);
        if (showLabel) { occupied.push(box); placed += 1; }
        L.marker([item.lat, item.lon], { pane: "roadPkPane", icon: pkIcon(item, showLabel), interactive: false }).addTo(overlay);
      });
      console.debug(`PK overlay: zoom=${map.getZoom()} source=${sourceIntervalForZoom(map.getZoom())} symbol=${density.symbol} label=${density.label} received=${items.length} symbols=${symbolItems.length} labelCandidates=${candidates} labelsPlaced=${placed}`);
      if (enabled && !map.hasLayer(overlay)) overlay.addTo(map);
    }
    async function load() {
      if (!enabled) return;
      const interval = intervalForZoom(map.getZoom());
      controller?.abort();
      const id = ++requestId;
      if (!interval || !selectedRoads.length) { overlay.clearLayers(); return; }
      const bounds = map.getBounds();
      if (!bounds.isValid()) return;
      controller = new AbortController();
      try {
        const bbox = [bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()].join(",");
        const response = await fetch(`/api/visor/pks?${new URLSearchParams({ bbox, carreteras: selectedRoads.join(";"), intervalo: interval })}`, { signal: controller.signal });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "No se pudieron cargar PKs.");
        if (id === requestId) drawOverlay(data.items || []);
      } catch (error) { if (error.name !== "AbortError" && id === requestId) showNotice(error.message, "warning"); }
    }
    function scheduleLoad() { clearTimeout(timer); timer = setTimeout(load, 220); }
    async function loadSelectedRoads() {
      roadsController?.abort(); const id = ++roadsRequestId;
      if (!selectedRoads.length) { selectedRoadsLayer.clearLayers(); return; }
      const bounds = map.getBounds(); if (!bounds.isValid()) return;
      roadsController = new AbortController();
      try { const bbox = [bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()].join(","); const response = await fetch(`/api/visor/vias-seleccionadas?${new URLSearchParams({ bbox, carreteras: selectedRoads.join(";") })}`, { signal: roadsController.signal }); const data = await response.json(); if (!response.ok) throw new Error(data.detail || "No se pudieron cargar las vías identificadas."); if (id !== roadsRequestId) return; selectedRoadsLayer.clearLayers(); const style = (pass) => (feature) => ({ pane: "selectedRoadPane", lineCap: "round", lineJoin: "round", ...(feature.properties?.autovia ? (pass === "casing" ? { color: "#7f1d1d", weight: 9.2, opacity: .94 } : { color: "#dc5b63", weight: 6.2, opacity: .96 }) : (pass === "casing" ? { color: "#7f1d1d", weight: 5.4, opacity: .94 } : { color: "#dc5b63", weight: 2.4, opacity: .98 })) }); L.geoJSON(data, { style: style("casing") }).addTo(selectedRoadsLayer); L.geoJSON(data, { style: style("interior") }).addTo(selectedRoadsLayer); } catch (error) { if (error.name !== "AbortError" && id === roadsRequestId) showNotice(error.message, "warning"); }
    }
    function scheduleAll() { scheduleLoad(); clearTimeout(timer); timer = setTimeout(() => { load(); loadSelectedRoads(); }, 220); }
    function renderPkPanel() {
      formElement.innerHTML = `<div class="viewer-inline-form viewer-pk-panel"><strong>Vías identificadas</strong><div class="viewer-road-chips">${selectedRoads.map((road) => `<button type="button" class="viewer-chip" data-remove-pk-road="${escapeAttr(road)}">${escapeHtml(road)} ×</button>`).join("")}</div><label>Añadir vía <input id="viewerPkRoad" list="viewerPkRoadOptions" autocomplete="off"></label><datalist id="viewerPkRoadOptions"></datalist><button type="button" class="ghost" id="viewerAddPkRoad">+ Añadir vía</button><label class="viewer-pk-checkbox"><input id="viewerTogglePk" type="checkbox" ${enabled ? "checked" : ""}> Mostrar PKs</label><span class="field-message">${selectedRoads.length ? "Densidad automática según zoom." : "Añade una carretera para destacarla."}</span></div>`;
      fetch("/api/carreteras").then((response) => response.ok ? response.json() : { items: [] }).then((data) => { const list = document.querySelector("#viewerPkRoadOptions"); if (list) list.innerHTML = (data.items || []).map((item) => `<option value="${escapeAttr(item.carretera)}"></option>`).join(""); }).catch(() => {});
      formElement.querySelectorAll("[data-remove-pk-road]").forEach((button) => button.addEventListener("click", () => { selectedRoads = selectedRoads.filter((road) => road !== button.dataset.removePkRoad); renderPkPanel(); scheduleAll(); }));
      document.querySelector("#viewerAddPkRoad")?.addEventListener("click", () => { const input = document.querySelector("#viewerPkRoad"); const value = input.value.trim(); if (value && !selectedRoads.some((road) => normalRoad(road) === normalRoad(value))) selectedRoads.push(value); renderPkPanel(); scheduleAll(); });
      document.querySelector("#viewerTogglePk")?.addEventListener("change", (event) => { enabled = event.currentTarget.checked; if (!enabled) { overlay.remove(); controller?.abort(); } else scheduleLoad(); });
    }
    function pointCard(item) {
      const coords = `${Number(item.punto.lat).toFixed(6)}, ${Number(item.punto.lon).toFixed(6)}`;
      return `<li class="viewer-pk-result"><strong>${escapeHtml(item.carretera)} · PK ${pkText(item.pk)}</strong><a href="https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=${encodeURIComponent(`${item.punto.lat},${item.punto.lon}`)}" target="_blank" rel="noopener noreferrer">${coords} ↗</a><button type="button" class="viewer-copy" data-pk-copy="${escapeAttr(coords)}">copiar</button><button type="button" class="viewer-copy" data-pk-use="inicio" data-road="${escapeAttr(item.carretera)}" data-pk="${item.pk}">PK inicio</button><button type="button" class="viewer-copy" data-pk-use="fin" data-road="${escapeAttr(item.carretera)}" data-pk="${item.pk}">PK fin</button></li>`;
    }
    function bindResultActions() {
      document.querySelectorAll("[data-pk-copy]").forEach((button) => button.addEventListener("click", () => navigator.clipboard?.writeText(button.dataset.pkCopy)));
      document.querySelectorAll("[data-pk-use]").forEach((button) => button.addEventListener("click", () => usePk(button.dataset.road, Number(button.dataset.pk), button.dataset.pkUse)));
      document.querySelector("#viewerZoomAll")?.addEventListener("click", () => { const pts = [...markers.getLayers()]; if (pts.length) map.fitBounds(L.featureGroup(pts).getBounds(), { padding: [24, 24] }); });
      document.querySelector("#viewerClearLocated")?.addEventListener("click", () => { markers.clearLayers(); setResult(""); });
    }
    function showBatchResults(results, parseErrors = []) {
      markers.clearLayers();
      const valid = results.filter((item) => !item.error);
      valid.forEach((item) => { drawPoint(item.punto, `${item.carretera} · PK ${pkText(item.pk)}`, "locate", markers); addHistory(item); });
      const errors = [...results.filter((item) => item.error).map((item) => ({ text: `Entrada ${item.indice + 1}`, error: item.error })), ...parseErrors.map((item) => ({ text: `Línea ${item.line}: ${item.text}`, error: item.error }))];
      setResult(`<div class="viewer-card"><strong>${valid.length} PK localizados · ${errors.length} error${errors.length === 1 ? "" : "es"}</strong><div class="viewer-actions"><button type="button" class="ghost" id="viewerZoomAll">Zoom a todos</button><button type="button" class="ghost" id="viewerClearLocated">Borrar marcadores</button></div><ol class="viewer-pk-results">${valid.map(pointCard).join("")}</ol>${errors.length ? `<ul class="viewer-pk-errors">${errors.map((item) => `<li>${escapeHtml(item.text)}: ${escapeHtml(item.error)}</li>`).join("")}</ul>` : ""}</div>`);
      bindResultActions();
    }
    async function locate(points, parseErrors = []) {
      if (!points.length) { showBatchResults([], parseErrors); return; }
      try {
        const response = await fetch("/api/visor/localizar-pks", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ puntos: points }) });
        const data = await response.json(); if (!response.ok) throw new Error(data.detail || "No se pudieron localizar los PKs."); showBatchResults(data.resultados || [], parseErrors);
      } catch (error) { setResult(`<p class="viewer-message">${escapeHtml(error.message)}</p>`); }
    }
    function addRow() { const rows = document.querySelector("#viewerLocateRows"); rows.insertAdjacentHTML("beforeend", `<div class="viewer-locate-row"><input data-locate-road list="viewerLocateRoads" placeholder="Carretera"><input data-locate-pk placeholder="25.000"><button type="button" class="viewer-copy" data-remove-row>×</button></div>`); rows.lastElementChild.querySelector("[data-remove-row]").addEventListener("click", (event) => event.currentTarget.closest(".viewer-locate-row").remove()); }
    function showLocateForm() {
      formElement.innerHTML = `<div class="viewer-inline-form viewer-locate-panel"><div id="viewerLocateRows"></div><datalist id="viewerLocateRoads"></datalist><div class="viewer-actions"><button type="button" class="ghost" id="viewerAddLocateRow">+</button><button type="button" class="ghost" id="viewerPasteList">Pegar lista</button><button type="button" class="ghost" id="viewerLocateSubmit">Localizar</button></div></div>`;
      fetch("/api/carreteras").then((response) => response.ok ? response.json() : { items: [] }).then((data) => { document.querySelector("#viewerLocateRoads").innerHTML = (data.items || []).map((item) => `<option value="${escapeAttr(item.carretera)}"></option>`).join(""); }).catch(() => {});
      addRow();
      document.querySelector("#viewerAddLocateRow").addEventListener("click", addRow);
      document.querySelector("#viewerPasteList").addEventListener("click", () => { document.querySelector(".viewer-locate-panel").innerHTML = `<label>Pegar lista de PK<textarea id="viewerPasteText" rows="5" placeholder="N-320 160+000\nA-1 250+000"></textarea></label><div class="viewer-actions"><button type="button" class="ghost" id="viewerRowsMode">Filas</button><button type="button" class="ghost" id="viewerPasteSubmit">Localizar</button></div>`; document.querySelector("#viewerRowsMode").addEventListener("click", showLocateForm); document.querySelector("#viewerPasteSubmit").addEventListener("click", () => { const parsed = parseText(document.querySelector("#viewerPasteText").value); locate(parsed.valid, parsed.errors); }); });
      document.querySelector("#viewerLocateSubmit").addEventListener("click", () => { const points = [...document.querySelectorAll(".viewer-locate-row")].map((row) => { try { return { carretera: row.querySelector("[data-locate-road]").value.trim(), pk: parseValue(row.querySelector("[data-locate-pk]").value) }; } catch (_) { return null; } }).filter(Boolean); locate(points); });
    }
    async function exportSelected(format) {
      const points = [...history.values()].filter((item) => item.selected).map((item) => ({ carretera: item.carretera, pk: item.pk, longitud: item.punto.lon, latitud: item.punto.lat }));
      if (!points.length) return;
      const response = await fetch("/api/visor/exportar-pks", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ puntos: points, formato: format }) });
      if (!response.ok) { const data = await response.json(); showNotice(data.detail || "No se pudo exportar."); return; }
      const blob = await response.blob(); const url = URL.createObjectURL(blob); const link = document.createElement("a"); link.href = url; link.download = `pks.${format}`; link.click(); URL.revokeObjectURL(url);
    }
    function showExport() {
      const rows = [...history.entries()];
      const menu = document.querySelector("#viewerExportMenu"); const button = document.querySelector("#viewerExportButton"); if (!menu || !button) return;
      menu.innerHTML = `<strong>Puntos guardados</strong><div class="viewer-export-list">${rows.map(([key, item]) => `<label><input type="checkbox" data-export-key="${escapeAttr(key)}" ${item.selected ? "checked" : ""}><span>${escapeHtml(item.carretera)} · PK ${pkText(item.pk)}</span></label>`).join("") || "<p>El historial está vacío.</p>"}</div><div class="viewer-actions"><button type="button" class="ghost" id="viewerAllExport">Todos</button><button type="button" class="ghost" id="viewerNoneExport">Ninguno</button><button type="button" class="ghost" data-export-format="csv">CSV</button><button type="button" class="ghost" data-export-format="gpkg">GPKG</button><button type="button" class="ghost" data-export-format="kmz">KMZ</button><button type="button" class="ghost" id="viewerClearHistory">Vaciar historial</button></div>`;
      menu.hidden = false; button.setAttribute("aria-expanded", "true");
      const sync = () => menu.querySelectorAll("[data-export-key]").forEach((box) => { const item = history.get(box.dataset.exportKey); if (item) item.selected = box.checked; });
      menu.querySelectorAll("[data-export-key]").forEach((box) => box.addEventListener("change", sync));
      menu.querySelector("#viewerAllExport")?.addEventListener("click", () => { history.forEach((item) => { item.selected = true; }); showExport(); });
      menu.querySelector("#viewerNoneExport")?.addEventListener("click", () => { history.forEach((item) => { item.selected = false; }); showExport(); });
      menu.querySelectorAll("[data-export-format]").forEach((button) => button.addEventListener("click", () => { sync(); exportSelected(button.dataset.exportFormat); }));
      menu.querySelector("#viewerClearHistory")?.addEventListener("click", () => { history.clear(); updateExportButton(); showExport(); });
    }
    function toggleExport() { const menu = document.querySelector("#viewerExportMenu"); const button = document.querySelector("#viewerExportButton"); if (menu && !menu.hidden) { menu.hidden = true; button?.setAttribute("aria-expanded", "false"); } else showExport(); }
    document.addEventListener("click", (event) => { const wrap = document.querySelector(".viewer-export-wrap"); const menu = document.querySelector("#viewerExportMenu"); if (wrap && !wrap.contains(event.target) && !menu?.contains(event.target)) { if (menu) menu.hidden = true; document.querySelector("#viewerExportButton")?.setAttribute("aria-expanded", "false"); } });
    document.addEventListener("keydown", (event) => { if (event.key === "Escape") { const menu = document.querySelector("#viewerExportMenu"); if (menu) menu.hidden = true; document.querySelector("#viewerExportButton")?.setAttribute("aria-expanded", "false"); } });
    return { togglePanel: renderPkPanel, showLocateForm, scheduleLoad: scheduleAll, addHistory, showExport: toggleExport, parseText, intervalForZoom, selectedRoadsLayer };
  };
  window.roadPkTools = { parseText, intervalForZoom, sourceIntervalForZoom, normalRoad, overlaySelection };
})();
