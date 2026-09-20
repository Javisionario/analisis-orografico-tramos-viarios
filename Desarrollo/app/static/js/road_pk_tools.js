/* PK overlay, bulk locator and in-memory export helpers for the Leaflet viewer. */
(() => {
  "use strict";

  const ZOOM_INTERVALS = Object.freeze([
    { min: 16, interval: 1 }, { min: 15, interval: 5 }, { min: 14, interval: 10 },
    { min: 13, interval: 20 }, { min: 12, interval: 50 }, { min: -Infinity, interval: 100 },
  ]);
  const intervalForZoom = (zoom) => (ZOOM_INTERVALS.find((item) => zoom >= item.min)?.interval || null);
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
    function tickIcon(item) {
      const major = Math.round(item.pk) % 5 === 0;
      // rotacion was verified against the PK_2023 geometry as a screen-space,
      // undirected road angle. Tangent remains the safe fallback for nulls.
      const rotation = Number.isFinite(Number(item.rotacion)) ? item.rotacion : (Number.isFinite(Number(item.rotacion_tangente)) ? item.rotacion_tangente : 0);
      return L.divIcon({ className: "road-pk-icon-wrap", iconSize: [28, 28], iconAnchor: [14, 14], html: `<span class="road-pk-tick ${major ? "major" : ""}" style="transform:rotate(${rotation}deg)"></span>` });
    }
    function labelIcon(item) {
      return L.divIcon({ className: "road-pk-label-wrap", iconSize: [1, 1], iconAnchor: [0, 0], html: `<span class="road-pk-label">${escapeHtml(item.pk_formateado)}</span>` });
    }
    function drawOverlay(items) {
      overlay.clearLayers();
      const occupied = [];
      items.forEach((item) => {
        L.marker([item.lat, item.lon], { pane: "roadPkPane", icon: tickIcon(item), interactive: false }).addTo(overlay);
        const point = map.latLngToContainerPoint([item.lat, item.lon]);
        const offsets = [[22, -34], [-92, -34], [22, 24], [-92, 24]];
        const offset = offsets.find(([x, y]) => point.x + x > 8 && point.x + x < map.getSize().x - 75 && point.y + y > 8 && point.y + y < map.getSize().y - 22 && !occupied.some((other) => Math.abs(other.x - (point.x + x)) < 76 && Math.abs(other.y - (point.y + y)) < 24));
        if (offset) { const anchor = map.containerPointToLatLng([point.x + offset[0], point.y + offset[1]]); occupied.push({ x: point.x + offset[0], y: point.y + offset[1] }); L.polyline([[item.lat, item.lon], anchor], { pane: "roadPkLabelPane", color: "#6b747b", weight: 1, opacity: .8, interactive: false }).addTo(overlay); L.marker(anchor, { pane: "roadPkLabelPane", icon: labelIcon(item), interactive: false }).addTo(overlay); }
      });
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
    document.addEventListener("click", (event) => { const wrap = document.querySelector(".viewer-export-wrap"); if (wrap && !wrap.contains(event.target)) { const menu = document.querySelector("#viewerExportMenu"); if (menu) menu.hidden = true; document.querySelector("#viewerExportButton")?.setAttribute("aria-expanded", "false"); } });
    document.addEventListener("keydown", (event) => { if (event.key === "Escape") { const menu = document.querySelector("#viewerExportMenu"); if (menu) menu.hidden = true; document.querySelector("#viewerExportButton")?.setAttribute("aria-expanded", "false"); } });
    return { togglePanel: renderPkPanel, showLocateForm, scheduleLoad: scheduleAll, addHistory, showExport: toggleExport, parseText, intervalForZoom, selectedRoadsLayer };
  };
  window.roadPkTools = { parseText, intervalForZoom, normalRoad };
})();
