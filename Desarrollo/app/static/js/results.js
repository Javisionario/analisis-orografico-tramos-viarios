(function () {
  "use strict";

  window.createAnalysisResults = function createAnalysisResults(options) {
    const {
      addBackToViewerAction, escapeHtml, formatPk, resultsBox, safeOutputUrl,
      showRightPanel, zipDownloads,
    } = options;

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
      <img src="${escapeHtml(safeOutputUrl(item.url))}" loading="lazy" alt="${escapeHtml(item.name)}">
      <figcaption><a href="${escapeHtml(safeOutputUrl(item.url))}" target="_blank" rel="noopener noreferrer">${escapeHtml(item.name)}</a></figcaption>
    </figure>
  `).join("");
}

function dataLinks(items) {
  if (!items.length) return "<p class='empty'>Sin datos auxiliares.</p>";
  return items.map((item) => `<a href="${escapeHtml(safeOutputUrl(item.url))}" target="_blank" rel="noopener noreferrer">${escapeHtml(item.name)}</a>`).join("");
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
  return `<div class="metric"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`;
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
          <p>${escapeHtml(tramo.carretera || params.carretera || "")} · ${escapeHtml(tramo.sentido || params.sentido || "")}</p>
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
    link.href = safeOutputUrl(item.url);
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
      <span>Salida: ${escapeHtml(data.job_id)}</span>
    </div>
  `;
  resultsBox.innerHTML = info
    + renderSummaryCard(data)
    + accordion("Mapas generados", previewImages(mapImages), true)
    + accordion("Perfil longitudinal con pendiente", previewImages(profilesWithSlope.length ? profilesWithSlope : otherProfiles), true)
    + accordion("Perfil longitudinal sin pendiente", previewImages(profilesWithoutSlope), false)
    + accordion("Datos auxiliares y metadatos", dataLinks(dataItems), false);
  renderZipButtons(data.zip_downloads);
  addBackToViewerAction();
  window.roadViewer?.setHasResults(true);
  showRightPanel("results");
}

    return { renderResults };
  };
}());
