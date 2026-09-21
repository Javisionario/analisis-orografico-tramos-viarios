(function () {
  "use strict";

  window.createAnalysisControls = function createAnalysisControls(options) {
    const {
      SG_TABLE, PK_INTERVALS, numberOrNull,
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
    } = options;
    const CARTO_API_KEY_MASK = "••••••••••••••••";
    let cartoStoredKeyAvailable = false;
    let cartoShowPressed = false;

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

function restoreCartoStoredMask() {
  if (!cartoShowPressed) setCartoStoredMask();
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

    return {
      clearCartoStoredMask, forgetCartoApiKey, hideCartoApiKey, pkSliderValue,
      restoreCartoStoredMask,
      setCartoStoredMask, sgPolyorderReal, sgSlopePolyorderReal, showCartoApiKey,
      updateAdvancedSgHelp, updateAdvancedSgState, updateAdvancedSlopeSgHelp,
      updateAdvancedSlopeSgState, updateAlphaLabels, updateAnomalyHelp,
      updateMapBaseControls, updatePkControls, updateSampleHelp, updateSlopeSmoothHelp,
      updateSmoothHelp,
    };
  };
}());
