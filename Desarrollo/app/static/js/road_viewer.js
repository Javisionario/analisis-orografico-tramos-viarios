/* Leaflet-only interactive viewer. General application state remains in app.js. */
(() => {
  "use strict";

  const ROAD_LAYER_MIN_ZOOM = 10;
  const SNAP_TOLERANCE_PX = 20;
  const MAX_SNAP_TOLERANCE_M = 500;
  const mapElement = document.querySelector("#roadViewerMap");
  const formElement = document.querySelector("#roadViewerForm");
  const resultElement = document.querySelector("#roadViewerResult");
  const resultsButton = document.querySelector("#viewerResultsButton");
  let map = null;
  let roadsLayer = null;
  let measureLayer = null;
  let mode = null;
  let measurePoints = [];
  let loadTimer = null;
  let hasResults = false;

  const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[char]));
  const pkText = (pk) => {
    const metres = Math.round(Number(pk) * 1000);
    return `${Math.floor(metres / 1000)}+${String(Math.abs(metres % 1000)).padStart(3, "0")}`;
  };
  const coordsText = (point) => `${Number(point.lat).toFixed(6)}, ${Number(point.lon).toFixed(6)}`;
  const streetViewUrl = (point) => `https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=${encodeURIComponent(`${point.lat},${point.lon}`)}`;

  function setResult(html = "") {
    resultElement.innerHTML = html;
    resultElement.hidden = !html;
    resultElement.querySelectorAll("[data-copy]").forEach((button) => button.addEventListener("click", () => copyText(button.dataset.copy, button)));
    resultElement.querySelectorAll("[data-use-pk]").forEach((button) => button.addEventListener("click", () => usePk(button.dataset.usePk, button.dataset.usePkTarget)));
    resultElement.querySelectorAll("[data-zoom]").forEach((button) => button.addEventListener("click", () => {
      map?.setView([Number(button.dataset.lat), Number(button.dataset.lon)], Math.max(map.getZoom(), 15));
    }));
    resultElement.querySelectorAll("[data-measure-road]").forEach((button) => button.addEventListener("click", () => requestMeasure(button.dataset.measureRoad)));
    resultElement.querySelectorAll("[data-use-tramo]").forEach((button) => button.addEventListener("click", () => useTramo(button.dataset.road, button.dataset.pk1, button.dataset.pk2)));
  }

  function copyText(value, button) {
    const done = () => {
      const before = button.textContent;
      button.textContent = "Copiado";
      setTimeout(() => { button.textContent = before; }, 1200);
    };
    if (navigator.clipboard?.writeText) navigator.clipboard.writeText(value).then(done).catch(() => fallbackCopy(value, done));
    else fallbackCopy(value, done);
  }

  function fallbackCopy(value, done) {
    const area = document.createElement("textarea");
    area.value = value;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    try { document.execCommand("copy"); done(); } finally { area.remove(); }
  }

  function resultCard(item, options = {}) {
    const point = item.punto;
    const roadPk = `${item.carretera} · PK ${pkText(item.pk)}`;
    const coordinates = coordsText(point);
    return `<div class="viewer-card">
      <div class="viewer-card-row"><strong>${escapeHtml(roadPk)}</strong><button type="button" class="viewer-copy" aria-label="Copiar carretera y PK" data-copy="${escapeHtml(roadPk)}">copiar</button></div>
      <div class="viewer-card-row"><a href="${streetViewUrl(point)}" target="_blank" rel="noopener noreferrer">${escapeHtml(coordinates)} ↗</a><button type="button" class="viewer-copy" aria-label="Copiar coordenadas" data-copy="${escapeHtml(coordinates)}">copiar</button></div>
      <div class="viewer-actions"><button type="button" class="ghost" data-zoom data-lat="${point.lat}" data-lon="${point.lon}">Zoom</button><button type="button" class="ghost" data-use-pk="${item.pk}" data-use-pk-target="inicio">Usar como PK inicio</button><button type="button" class="ghost" data-use-pk="${item.pk}" data-use-pk-target="fin">Usar como PK fin</button></div>
    </div>`;
  }

  async function usePk(pk, target) {
    if (typeof window.setRoadFromViewer !== "function") return;
    const current = resultElement.querySelector("[data-road]")?.dataset.road;
    if (current) await window.setRoadFromViewer(current, target === "inicio" ? pk : null, target === "fin" ? pk : null);
  }

  async function useTramo(road, pk1, pk2) {
    if (typeof window.setRoadFromViewer === "function") await window.setRoadFromViewer(road, pk1, pk2);
  }

  function toleranceMetres(lat) {
    const metres = SNAP_TOLERANCE_PX * 156543.03392 * Math.cos(lat * Math.PI / 180) / (2 ** map.getZoom());
    return Math.min(MAX_SNAP_TOLERANCE_M, Math.max(2, metres));
  }

  function clearInteraction() {
    mode = null;
    measurePoints = [];
    mapElement.classList.remove("viewer-identify-cursor", "viewer-measure-cursor");
    formElement.innerHTML = "";
  }

  function showLocateForm() {
    clearInteraction();
    formElement.innerHTML = `<form id="viewerLocateForm" class="viewer-inline-form"><label>Carretera <input id="viewerRoad" list="viewerRoadOptions" required autocomplete="off"></label><datalist id="viewerRoadOptions"></datalist><label>PK <input id="viewerPk" type="number" min="0" step="0.001" required></label><button class="ghost" type="submit">Localizar</button></form>`;
    fetch("/api/carreteras").then((response) => response.ok ? response.json() : { items: [] }).then((data) => {
      document.querySelector("#viewerRoadOptions").innerHTML = (data.items || []).map((item) => `<option value="${escapeHtml(item.carretera)}"></option>`).join("");
    }).catch(() => {});
    document.querySelector("#viewerLocateForm").addEventListener("submit", async (event) => {
      event.preventDefault();
      const road = document.querySelector("#viewerRoad").value;
      const pk = document.querySelector("#viewerPk").value;
      try {
        const response = await fetch(`/api/visor/localizar-pk?${new URLSearchParams({ carretera: road, pk })}`);
        const item = await response.json();
        if (!response.ok) throw new Error(item.detail || "No se pudo localizar el PK.");
        item.punto && drawPoint(item.punto, "PK");
        setResult(`<div data-road="${escapeHtml(item.carretera)}">${resultCard(item)}</div>`);
        map.setView([item.punto.lat, item.punto.lon], Math.max(map.getZoom(), 15));
      } catch (error) { setResult(`<p class="viewer-message">${escapeHtml(error.message)}</p>`); }
    });
  }

  function activateIdentify() {
    clearInteraction();
    mode = "identify";
    mapElement.classList.add("viewer-identify-cursor");
    setResult("<p class=\"viewer-message\">Haz clic sobre una vía para identificar su PK.</p>");
  }

  function activateMeasure() {
    clearInteraction();
    mode = "measure";
    measureLayer.clearLayers();
    mapElement.classList.add("viewer-measure-cursor");
    setResult("<p class=\"viewer-message\">Selecciona dos puntos sobre la misma carretera.</p>");
  }

  function drawPoint(point, label) {
    L.circleMarker([point.lat, point.lon], { radius: 7, color: "#9d1c25", weight: 2, fillColor: "#fff", fillOpacity: 1 }).bindTooltip(label, { permanent: true, direction: "top" }).addTo(measureLayer);
  }

  async function identify(latlng) {
    try {
      const response = await fetch("/api/visor/identificar", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ lon: latlng.lng, lat: latlng.lat, tolerance_m: toleranceMetres(latlng.lat) }) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "No se pudo identificar la vía.");
      if (data.estado === "ambiguo") {
        setResult(`<div class="viewer-card"><p>Hay varias vías posibles:</p>${data.opciones.map((item) => `<button class="ghost" type="button" data-identify-option="${escapeHtml(JSON.stringify(item))}">${escapeHtml(item.carretera)} · PK ${pkText(item.pk)}</button>`).join(" ")}</div>`);
        resultElement.querySelectorAll("[data-identify-option]").forEach((button) => button.addEventListener("click", () => {
          const item = JSON.parse(button.dataset.identifyOption); drawPoint(item.punto, "PK"); setResult(`<div data-road="${escapeHtml(item.carretera)}">${resultCard(item)}</div>`);
        }));
      } else {
        const item = data.opciones[0]; drawPoint(item.punto, "PK"); setResult(`<div data-road="${escapeHtml(item.carretera)}">${resultCard(item)}</div>`);
      }
    } catch (error) { setResult(`<p class="viewer-message">${escapeHtml(error.message)}</p>`); }
  }

  async function requestMeasure(road = null) {
    const [p1, p2] = measurePoints;
    if (!p1 || !p2) return;
    try {
      const tolerance = Math.max(toleranceMetres(p1.lat), toleranceMetres(p2.lat));
      const response = await fetch("/api/visor/medir", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ p1: { lon: p1.lng, lat: p1.lat }, p2: { lon: p2.lng, lat: p2.lat }, tolerance_m: tolerance, carretera: road }) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "No se pudo medir.");
      if (data.estado === "ambiguo") {
        setResult(`<div class="viewer-card"><p>¿Sobre qué vía quieres medir?</p>${data.carreteras.map((name) => `<button type="button" class="ghost" data-measure-road="${escapeHtml(name)}">${escapeHtml(name)}</button>`).join(" ")}</div>`);
        return;
      }
      if (data.estado !== "ok") {
        setResult("<p class=\"viewer-message\">Los dos puntos no se pueden resolver sobre una misma vía. Puedes repetir la selección.</p>");
        return;
      }
      measureLayer.clearLayers();
      drawPoint(data.p1, "1"); drawPoint(data.p2, "2");
      L.geoJSON(data.geometry, { style: { color: "#9d1c25", weight: 5, opacity: 0.9 } }).addTo(measureLayer);
      const title = `${data.carretera} · PK ${pkText(data.pk1)} → PK ${pkText(data.pk2)}`;
      const value = `${(data.distancia_geometria_m / 1000).toFixed(2)} km · ΔPK ${(data.diferencia_pk_m / 1000).toFixed(2)} km`;
      setResult(`<div class="viewer-card"><div class="viewer-card-row"><strong>${escapeHtml(title)}</strong><button type="button" class="viewer-copy" aria-label="Copiar medición" data-copy="${escapeHtml(title)}">copiar</button></div><p>Sobre la vía ${escapeHtml(value)}</p><div class="viewer-actions"><button type="button" class="ghost" data-use-tramo data-road="${escapeHtml(data.carretera)}" data-pk1="${data.pk1}" data-pk2="${data.pk2}">Usar este tramo</button></div></div>`);
    } catch (error) { setResult(`<p class="viewer-message">${escapeHtml(error.message)}</p>`); }
  }

  function onMapClick(event) {
    if (mode === "identify") identify(event.latlng);
    if (mode === "measure") {
      if (measurePoints.length === 2) { measureLayer.clearLayers(); measurePoints = []; }
      measurePoints.push(event.latlng);
      L.circleMarker(event.latlng, { radius: 7, color: "#9d1c25", weight: 2, fillColor: "#fff", fillOpacity: 1 }).bindTooltip(String(measurePoints.length), { permanent: true, direction: "top" }).addTo(measureLayer);
      if (measurePoints.length === 2) requestMeasure();
      else setResult("<p class=\"viewer-message\">Selecciona el segundo punto.</p>");
    }
  }

  function scheduleRoadLoad() {
    clearTimeout(loadTimer);
    loadTimer = setTimeout(loadRoads, 220);
  }

  async function loadRoads() {
    if (!map || map.getZoom() < ROAD_LAYER_MIN_ZOOM) { roadsLayer.clearLayers(); return; }
    const bounds = map.getBounds();
    const bbox = [bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()].join(",");
    try {
      const response = await fetch(`/api/visor/vias?${new URLSearchParams({ bbox })}`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "No se pudo cargar la red.");
      roadsLayer.clearLayers();
      L.geoJSON(data, { style: (feature) => feature.properties.autovia ? { color: "#2166a5", weight: 5, opacity: 0.62 } : { color: "#47515c", weight: 4.5, opacity: 0.5 }, onEachFeature: (_feature, layer) => layer.setStyle({ lineCap: "round", lineJoin: "round" }) }).addTo(roadsLayer);
      L.geoJSON(data, { style: (feature) => feature.properties.autovia ? { color: "#2f79b8", weight: 3, opacity: 0.72 } : { color: "#ffffff", weight: 2.1, opacity: 0.7 }, onEachFeature: (_feature, layer) => layer.setStyle({ lineCap: "round", lineJoin: "round" }) }).addTo(roadsLayer);
    } catch (_error) { /* The base map and report generation stay usable. */ }
  }

  async function initialise() {
    resultsButton.addEventListener("click", () => window.showViewerResults?.());
    if (!window.L || !mapElement) {
      mapElement.innerHTML = "<p class=\"viewer-unavailable\">El visor no está disponible ahora. Puedes generar informes con normalidad.</p>";
      return;
    }
    map = L.map(mapElement, { zoomControl: true });
    const grey = L.tileLayer("https://tms-ign-base.idee.es/1.0.0/IGNBaseGris/{z}/{x}/{y}.jpeg", { tms: true, maxNativeZoom: 17, maxZoom: 23, attribution: "Instituto Geográfico Nacional de España." });
    const photo = L.tileLayer("https://tms-pnoa-ma.idee.es/1.0.0/pnoa-ma/{z}/{x}/{-y}.jpeg", { maxZoom: 19, attribution: "PNOA Máxima Actualidad · Instituto Geográfico Nacional." });
    grey.addTo(map);
    roadsLayer = L.layerGroup().addTo(map);
    measureLayer = L.layerGroup().addTo(map);
    L.control.layers({ "Callejero gris": grey, Ortofoto: photo }, { "Red calibrada": roadsLayer }, { collapsed: true }).addTo(map);
    map.on("moveend", scheduleRoadLoad);
    map.on("click", onMapClick);
    try {
      const response = await fetch("/api/visor/bounds");
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail);
      map.fitBounds(data.bounds, { padding: [16, 16] });
    } catch (_error) { map.setView([40.2, -3.7], 6); }
    document.querySelectorAll("[data-viewer-tool]").forEach((button) => button.addEventListener("click", () => {
      if (button.dataset.viewerTool === "locate") showLocateForm();
      if (button.dataset.viewerTool === "identify") activateIdentify();
      if (button.dataset.viewerTool === "measure") activateMeasure();
    }));
  }

  window.roadViewer = {
    show() { requestAnimationFrame(() => map?.invalidateSize()); },
    setHasResults(value) { hasResults = Boolean(value); resultsButton.hidden = !hasResults; },
  };
  initialise();
})();
