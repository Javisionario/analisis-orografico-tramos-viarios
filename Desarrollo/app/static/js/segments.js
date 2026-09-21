(function () {
  "use strict";

  window.createAnalysisSegments = function createAnalysisSegments(options) {
    const {
      segmentList, addSegmentButton, multiSegmentWarning, pendingMapCheckbox,
      normalizeRoad, normalizedPrefix, numberOrNull, formatPk, setParagraphs,
      setStatus, updateSmoothHelp, updatePkControls,
    } = options;
    let roadCache = null;
    let roadLoading = null;
    let activeSegmentId = 1;
    let nextSegmentId = 2;
    let pendingMapBeforeMulti = null;
    const segmentRoads = new Map();
    const segmentSuggestionState = new WeakMap();
    const SUGGESTION_LIMIT = 90;

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
      setParagraphs(box, clean);
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
      if (report && box) { box.hidden = !problems.length; setParagraphs(box, problems); }
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
      const loading = roadLoading;
      try {
        roadCache = await loading;
        return roadCache;
      } catch (error) {
        roadCache = null;
        throw error;
      } finally {
        if (roadLoading === loading) roadLoading = null;
      }
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
      closeSegmentSuggestions(segment);
      segment.querySelector('[data-role="clear-road"]').classList.add("visible");
      validateSegmentPk(segment);
    }

    function closeSegmentSuggestions(segment) {
      const suggestions = segment?.querySelector('[data-role="suggestions"]');
      const input = segment?.querySelector('[data-role="road"]');
      if (segment) {
        const requestId = Number(segment.dataset.suggestionRequest || 0);
        segment.dataset.suggestionRequest = String(requestId + 1);
      }
      if (suggestions) suggestions.hidden = true;
      if (input) input.setAttribute("aria-expanded", "false");
      if (segment) segmentSuggestionState.delete(segment);
    }

    function updateSuggestionHighlight(segment, index) {
      const state = segmentSuggestionState.get(segment);
      if (!state?.items.length) return;
      state.highlighted = (index + state.items.length) % state.items.length;
      state.items.forEach((entry, itemIndex) => {
        entry.button.classList.toggle("is-highlighted", itemIndex === state.highlighted);
        entry.button.setAttribute("aria-selected", String(itemIndex === state.highlighted));
      });
    }

    function renderSuggestions(segment, items, q) {
      const suggestions = segment.querySelector('[data-role="suggestions"]');
      suggestions.innerHTML = "";
      suggestions.setAttribute("role", "listbox");
      const shown = items.slice(0, SUGGESTION_LIMIT);
      if (!shown.length) {
        const empty = document.createElement("div");
        empty.className = "suggestion-empty";
        empty.textContent = q ? "No hay coincidencias" : "No hay carreteras disponibles";
        suggestions.appendChild(empty);
        suggestions.hidden = false;
        segmentSuggestionState.set(segment, { items: [], highlighted: -1 });
        segment.querySelector('[data-role="road"]').setAttribute("aria-expanded", "true");
        return;
      }
      const choices = [];
      for (const item of shown) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "suggestion";
        button.setAttribute("role", "option");
        button.setAttribute("aria-selected", "false");
        const road = document.createElement("strong");
        road.textContent = item.carretera;
        const range = document.createElement("span");
        range.textContent = `${formatPk(item.pk_min)} - ${formatPk(item.pk_max)}`;
        button.append(road, range);
        button.addEventListener("click", () => selectSegmentRoad(segment, item));
        suggestions.appendChild(button);
        choices.push({ item, button });
      }
      if (items.length > shown.length) {
        const more = document.createElement("div");
        more.className = "suggestion-empty";
        more.textContent = `Mostrando ${shown.length} de ${items.length} coincidencias. Sigue escribiendo para afinar.`;
        suggestions.appendChild(more);
      }
      suggestions.hidden = false;
      segmentSuggestionState.set(segment, { items: choices, highlighted: -1 });
      segment.querySelector('[data-role="road"]').setAttribute("aria-expanded", "true");
    }

    async function refreshSegmentSuggestions(segment) {
      const roadInputLocal = segment.querySelector('[data-role="road"]');
      const message = segment.querySelector('[data-role="road-message"]');
      const q = roadInputLocal.value.trim();
      const requestId = Number(segment.dataset.suggestionRequest || 0) + 1;
      segment.dataset.suggestionRequest = String(requestId);
      segment.querySelector('[data-role="clear-road"]').classList.toggle("visible", q.length > 0);
      const selected = segmentRoad(segment);
      if (selected && normalizeRoad(selected.carretera) !== normalizeRoad(q)) segmentRoads.delete(segment.dataset.segmentId);
      message.className = "field-message";
      try {
        await loadRoads();
        if (requestId !== Number(segment.dataset.suggestionRequest)) return;
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
        if (requestId !== Number(segment.dataset.suggestionRequest)) return;
        message.textContent = String(error.message || error);
        message.className = "field-message error";
      }
    }

    function clearSegmentRoad(segment) {
      segment.querySelector('[data-role="road"]').value = "";
      segmentRoads.delete(segment.dataset.segmentId);
      segment.querySelector('[data-role="road-message"]').textContent = "";
      segment.querySelector('[data-role="road-message"]').className = "field-message";
      closeSegmentSuggestions(segment);
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
          <label class="road-field"><span>Carretera</span><div class="input-wrap"><input data-role="road" autocomplete="off" placeholder="Ma-2210" required role="combobox" aria-autocomplete="list" aria-expanded="false"><button data-role="clear-road" class="clear-input" type="button" aria-label="Limpiar carretera">×</button></div><div data-role="suggestions" class="suggestions" hidden></div><p data-role="road-message" class="field-message"></p></label>
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
    segmentList.addEventListener("keydown", (event) => {
      if (!event.target.matches('[data-role="road"]')) return;
      const segment = event.target.closest(".segment-block");
      const state = segmentSuggestionState.get(segment);
      if (event.key === "Escape") { closeSegmentSuggestions(segment); return; }
      if (!state?.items.length) return;
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        const initial = event.key === "ArrowDown" ? 0 : state.items.length - 1;
        updateSuggestionHighlight(segment, state.highlighted < 0 ? initial : state.highlighted + (event.key === "ArrowDown" ? 1 : -1));
      }
      if (event.key === "Enter" && state.highlighted >= 0) {
        event.preventDefault();
        selectSegmentRoad(segment, state.items[state.highlighted].item);
      }
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
      const roadField = event.target.closest(".road-field");
      if (roadField && !roadField.contains(event.relatedTarget)) closeSegmentSuggestions(segment);
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
    document.addEventListener("pointerdown", (event) => {
      const activeRoadField = event.target.closest(".road-field");
      segments().forEach((segment) => {
        if (!activeRoadField || !segment.contains(activeRoadField)) closeSegmentSuggestions(segment);
      });
    });

    return { activeSegment, divisionValues, ensureSegmentRoad, loadRoads, roadExact, segmentRoad, segments, selectSegmentRoad, updateMultiSegmentMode, validateSegmentPk };
  };
}());
