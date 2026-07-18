"use strict";

const MAX_BYTES = 50 * 1024 * 1024;
const MAX_TRIANGLES = 400000;
const ROUTES = {
  B: { name: "Маршрут B", subtitle: "Стандартный поток" },
  C: { name: "Маршрут C", subtitle: "Габаритный контроль" },
  D: { name: "Маршрут D", subtitle: "Круглая форма" },
};

const elements = Object.fromEntries([
  "stl-input", "change-file", "run-check", "viewer", "viewer-shell", "empty-view", "loading-view",
  "dropzone", "file-meta", "empty-result", "result-content", "metric-length", "metric-width",
  "metric-height", "metric-k", "route-card", "route-letter", "route-name", "route-subtitle",
  "route-reason", "error-card", "error-message", "retry-button", "process-route", "event-log",
  "event-count", "download-report", "status-live",
  "cycle-status", "repeat-cycle", "fault-cycle",
].map((id) => [id, document.getElementById(id)]));

const reducedMotionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");

const state = {
  triangles: [],
  points: [],
  fileName: "",
  fileSize: 0,
  metrics: null,
  report: null,
  events: [],
  rotationX: -0.5,
  rotationY: 0.72,
  zoom: 0.82,
  drag: null,
  loadToken: 0,
  mode: "model",
  decision: null,
  conveyorMesh: [],
  cycle: {
    serial: 0,
    frame: 0,
    active: false,
    fault: false,
    requestedRoute: null,
    effectiveRoute: null,
    progress: 0,
    stage: -1,
    complete: false,
  },
};

function announce(message) {
  elements["status-live"].textContent = message;
}

function addEvent(message) {
  const stamp = new Date().toLocaleTimeString("ru-RU", { hour12: false });
  state.events.push(`${stamp} — ${message}`);
  const item = document.createElement("li");
  item.textContent = state.events.at(-1);
  elements["event-log"].append(item);
  elements["event-count"].textContent = `${state.events.length} ${eventWord(state.events.length)}`;
}

function eventWord(count) {
  const tens = count % 100;
  const units = count % 10;
  if (tens >= 11 && tens <= 14) return "событий";
  if (units === 1) return "событие";
  if (units >= 2 && units <= 4) return "события";
  return "событий";
}

function formatNumber(value, digits = 2) {
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: digits, minimumFractionDigits: digits }).format(value);
}

function parseStl(buffer) {
  if (buffer.byteLength < 15) throw new Error("Файл слишком мал и не похож на STL.");
  const view = new DataView(buffer);
  if (buffer.byteLength >= 84) {
    const count = view.getUint32(80, true);
    if (count > 0 && count <= MAX_TRIANGLES && 84 + count * 50 <= buffer.byteLength) {
      const triangles = [];
      let offset = 84;
      for (let index = 0; index < count; index += 1) {
        offset += 12;
        const triangle = [];
        for (let vertex = 0; vertex < 3; vertex += 1) {
          triangle.push([view.getFloat32(offset, true), view.getFloat32(offset + 4, true), view.getFloat32(offset + 8, true)]);
          offset += 12;
        }
        triangles.push(triangle);
        offset += 2;
      }
      return triangles;
    }
  }
  const text = new TextDecoder("utf-8", { fatal: false }).decode(buffer);
  const vertices = [...text.matchAll(/\bvertex\s+([-+\d.eE]+)\s+([-+\d.eE]+)\s+([-+\d.eE]+)/g)]
    .map((match) => [Number(match[1]), Number(match[2]), Number(match[3])]);
  if (vertices.length < 3 || vertices.length % 3 !== 0) throw new Error("Не найдены треугольники ASCII или binary STL.");
  if (vertices.length / 3 > MAX_TRIANGLES) throw new Error("В модели слишком много треугольников для безопасной проверки в браузере.");
  return Array.from({ length: vertices.length / 3 }, (_, index) => vertices.slice(index * 3, index * 3 + 3));
}

function enrichedPoints(triangles) {
  const limit = Math.max(1, Math.ceil(triangles.length / 25000));
  const points = [];
  for (let index = 0; index < triangles.length; index += limit) {
    const [a, b, c] = triangles[index];
    points.push(a, b, c);
    points.push(midpoint(a, b), midpoint(b, c), midpoint(c, a));
    points.push([(a[0] + b[0] + c[0]) / 3, (a[1] + b[1] + c[1]) / 3, (a[2] + b[2] + c[2]) / 3]);
  }
  return points;
}

function midpoint(a, b) {
  return [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2];
}

function principalFrame(points) {
  const mean = [0, 1, 2].map((axis) => points.reduce((sum, point) => sum + point[axis], 0) / points.length);
  const covariance = Array.from({ length: 3 }, () => [0, 0, 0]);
  for (const point of points) {
    const d = point.map((value, axis) => value - mean[axis]);
    for (let row = 0; row < 3; row += 1) for (let col = 0; col < 3; col += 1) covariance[row][col] += d[row] * d[col];
  }
  for (let row = 0; row < 3; row += 1) for (let col = 0; col < 3; col += 1) covariance[row][col] /= Math.max(1, points.length - 1);
  const vectors = jacobiEigenvectors(covariance);
  return points.map((point) => {
    const centered = point.map((value, axis) => value - mean[axis]);
    return vectors.map((vector) => dot(centered, vector));
  });
}

function jacobiEigenvectors(source) {
  const matrix = source.map((row) => [...row]);
  const vectors = [[1, 0, 0], [0, 1, 0], [0, 0, 1]];
  for (let iteration = 0; iteration < 40; iteration += 1) {
    let p = 0;
    let q = 1;
    for (const pair of [[0, 1], [0, 2], [1, 2]]) if (Math.abs(matrix[pair[0]][pair[1]]) > Math.abs(matrix[p][q])) [p, q] = pair;
    if (Math.abs(matrix[p][q]) < 1e-10) break;
    const angle = 0.5 * Math.atan2(2 * matrix[p][q], matrix[q][q] - matrix[p][p]);
    const cosine = Math.cos(angle);
    const sine = Math.sin(angle);
    for (let index = 0; index < 3; index += 1) {
      const mip = matrix[index][p];
      const miq = matrix[index][q];
      matrix[index][p] = cosine * mip - sine * miq;
      matrix[index][q] = sine * mip + cosine * miq;
    }
    for (let index = 0; index < 3; index += 1) {
      const mpi = matrix[p][index];
      const mqi = matrix[q][index];
      matrix[p][index] = cosine * mpi - sine * mqi;
      matrix[q][index] = sine * mpi + cosine * mqi;
      const vip = vectors[index][p];
      const viq = vectors[index][q];
      vectors[index][p] = cosine * vip - sine * viq;
      vectors[index][q] = sine * vip + cosine * viq;
    }
  }
  const columns = [0, 1, 2].map((column) => vectors.map((row) => row[column]));
  return columns.sort((a, b) => varianceAlong(source, b) - varianceAlong(source, a));
}

function varianceAlong(matrix, vector) {
  return dot(vector, matrix.map((row) => dot(row, vector)));
}

function dot(a, b) { return a.reduce((sum, value, index) => sum + value * b[index], 0); }

function convexHull(points) {
  const unique = [...new Map(points.map((point) => [`${point[0].toFixed(6)}:${point[1].toFixed(6)}`, point])).values()]
    .sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  if (unique.length < 3) return unique;
  const cross = (origin, a, b) => (a[0] - origin[0]) * (b[1] - origin[1]) - (a[1] - origin[1]) * (b[0] - origin[0]);
  const half = (list) => {
    const result = [];
    for (const point of list) {
      while (result.length >= 2 && cross(result.at(-2), result.at(-1), point) <= 0) result.pop();
      result.push(point);
    }
    result.pop();
    return result;
  };
  return [...half(unique), ...half([...unique].reverse())];
}

function polygonCircularity(points) {
  const hull = convexHull(points);
  if (hull.length < 3) return 0;
  let twiceArea = 0;
  let centroidX = 0;
  let centroidY = 0;
  for (let index = 0; index < hull.length; index += 1) {
    const a = hull[index];
    const b = hull[(index + 1) % hull.length];
    const cross = a[0] * b[1] - b[0] * a[1];
    twiceArea += cross;
    centroidX += (a[0] + b[0]) * cross;
    centroidY += (a[1] + b[1]) * cross;
  }
  if (Math.abs(twiceArea) < 1e-9) return 0;
  const center = [centroidX / (3 * twiceArea), centroidY / (3 * twiceArea)];
  const outer = Math.max(...hull.map((point) => Math.hypot(point[0] - center[0], point[1] - center[1])));
  const inner = Math.min(...hull.map((point, index) => distanceToLine(center, point, hull[(index + 1) % hull.length])));
  return outer > 0 ? Math.min(1, inner / outer) : 0;
}

function distanceToLine(point, a, b) {
  const numerator = Math.abs((b[1] - a[1]) * point[0] - (b[0] - a[0]) * point[1] + b[0] * a[1] - b[1] * a[0]);
  return numerator / Math.max(1e-12, Math.hypot(b[1] - a[1], b[0] - a[0]));
}

function measure(triangles) {
  const unique = [...new Map(triangles.flat().map((point) => [point.map((value) => value.toFixed(7)).join(":"), point])).values()];
  const stride = Math.max(1, Math.ceil(unique.length / 30000));
  const points = unique.filter((_, index) => index % stride === 0);
  if (!points.every((point) => point.every(Number.isFinite))) throw new Error("В модели есть некорректные координаты.");
  const principal = principalFrame(points);
  const extents = [0, 1, 2].map((axis) => {
    const values = principal.map((point) => point[axis]);
    return Math.max(...values) - Math.min(...values);
  }).sort((a, b) => b - a);
  if (extents.some((value) => value <= 0 || !Number.isFinite(value))) throw new Error("Модель вырождена: один из размеров равен нулю.");
  const projections = [[[1, 2]], [[0, 2]], [[0, 1]]].map((axes) => principal.map((point) => [point[axes[0][0]], point[axes[0][1]]]));
  const circularity = Math.max(...projections.map(polygonCircularity));
  return { dimensions: extents, circularity, points };
}

function classify(metrics) {
  const [length, width, height] = metrics.dimensions;
  if (!(length > 10 && width > 10 && height > 10 && length < 450 && width < 320 && height < 320)) {
    return { route: "C", reason: "хотя бы один размер вне строгих границ 10 < L < 450 мм и 10 < W,H < 320 мм" };
  }
  if (metrics.circularity > 0.8) return { route: "D", reason: `размеры допустимы, но K = ${formatNumber(metrics.circularity)} > 0,80` };
  return { route: "B", reason: `размеры допустимы и K = ${formatNumber(metrics.circularity)} ≤ 0,80` };
}

async function loadFile(file) {
  const token = ++state.loadToken;
  resetError();
  if (!file || !file.name.toLowerCase().endsWith(".stl")) return showError("Выберите файл с расширением .stl.");
  if (file.size > MAX_BYTES) return showError("Файл больше 50 МБ. Упростите сетку или используйте офлайн-симулятор.");
  setLoading(true);
  addEvent(`получен файл ${file.name}, ${file.size.toLocaleString("ru-RU")} байт`);
  try {
    const buffer = await file.arrayBuffer();
    if (token !== state.loadToken) return;
    const triangles = parseStl(buffer);
    state.triangles = triangles;
    state.points = enrichedPoints(triangles);
    state.fileName = file.name;
    state.fileSize = file.size;
    state.metrics = null;
    state.report = null;
    elements["file-meta"].textContent = `${file.name} · ${file.size.toLocaleString("ru-RU")} байт · ${triangles.length.toLocaleString("ru-RU")} треугольников`;
    elements["run-check"].disabled = false;
    elements["download-report"].disabled = true;
    elements["empty-view"].hidden = true;
    elements["empty-result"].hidden = false;
    elements["result-content"].hidden = true;
    addEvent(`STL разобран: ${triangles.length.toLocaleString("ru-RU")} треугольников`);
    announce("Модель загружена. Нажмите «Проверить модель».");
    render();
  } catch (error) {
    showError(error instanceof Error ? error.message : "Неизвестная ошибка разбора STL.");
  } finally {
    if (token === state.loadToken) setLoading(false);
  }
}

async function runCheck() {
  if (!state.triangles.length) return;
  resetError();
  setLoading(true);
  elements["run-check"].disabled = true;
  await new Promise((resolve) => window.setTimeout(resolve, 40));
  try {
    addEvent("построена геометрическая оценка по пяти виртуальным ракурсам");
    const metrics = measure(state.triangles);
    const decision = classify(metrics);
    state.metrics = metrics;
    state.report = await makeReport(metrics, decision);
    showResult(metrics, decision);
    addEvent(`назначен маршрут ${decision.route}; решение зафиксировано контрольной суммой`);
    announce(`Проверка завершена. Назначен маршрут ${decision.route}.`);
  } catch (error) {
    showError(error instanceof Error ? error.message : "Не удалось измерить модель.");
  } finally {
    setLoading(false);
    elements["run-check"].disabled = !state.triangles.length;
  }
}

async function makeReport(metrics, decision) {
  const payload = {
    schema_version: 1,
    product: "SafeSort browser demonstrator",
    generated_at: new Date().toISOString(),
    input: { name: state.fileName, size_bytes: state.fileSize, triangles: state.triangles.length, assumed_units: "mm" },
    measurement: { dimensions_mm: metrics.dimensions.map((value) => Number(value.toFixed(4))), circularity_k_estimate: Number(metrics.circularity.toFixed(6)), method: "PCA OBB + projected inscribed/circumscribed radii" },
    decision: { route: decision.route, reason: decision.reason, official_rule_order: ["dimension", "circularity"] },
    privacy: { uploaded: false, runtime_network_required: false },
  };
  const bytes = new TextEncoder().encode(JSON.stringify(payload));
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  payload.sha256 = [...new Uint8Array(digest)].map((value) => value.toString(16).padStart(2, "0")).join("");
  return payload;
}

function showResult(metrics, decision) {
  const [length, width, height] = metrics.dimensions;
  elements["metric-length"].textContent = formatNumber(length);
  elements["metric-width"].textContent = formatNumber(width);
  elements["metric-height"].textContent = formatNumber(height);
  elements["metric-k"].textContent = formatNumber(metrics.circularity);
  elements["route-letter"].textContent = decision.route;
  elements["route-name"].textContent = ROUTES[decision.route].name;
  elements["route-subtitle"].textContent = ROUTES[decision.route].subtitle;
  elements["route-reason"].textContent = decision.reason;
  elements["route-card"].className = `route-card route-${decision.route.toLowerCase()}`;
  elements["process-route"].textContent = `маршрут ${decision.route}`;
  elements["empty-result"].hidden = true;
  elements["result-content"].hidden = false;
  elements["download-report"].disabled = false;
}

function showError(message) {
  setLoading(false);
  state.report = null;
  elements["error-message"].textContent = message;
  elements["error-card"].hidden = false;
  elements["result-content"].hidden = true;
  elements["empty-result"].hidden = true;
  elements["download-report"].disabled = true;
  addEvent(`безопасный отказ: ${message}`);
  announce(`Ошибка: ${message}`);
}

function resetError() {
  elements["error-card"].hidden = true;
}

function setLoading(active) {
  elements["loading-view"].hidden = !active;
  elements["viewer-shell"].setAttribute("aria-busy", String(active));
}

function makeBox(length, width, height) {
  const x = length / 2, y = width / 2, z = height / 2;
  const v = [[-x,-y,-z],[x,-y,-z],[x,y,-z],[-x,y,-z],[-x,-y,z],[x,-y,z],[x,y,z],[-x,y,z]];
  return [[0,2,1],[0,3,2],[4,5,6],[4,6,7],[0,1,5],[0,5,4],[1,2,6],[1,6,5],[2,3,7],[2,7,6],[3,0,4],[3,4,7]].map((face) => face.map((index) => v[index]));
}

function makeCylinder(radius, height, segments = 48) {
  const triangles = [];
  for (let index = 0; index < segments; index += 1) {
    const a = 2 * Math.PI * index / segments;
    const b = 2 * Math.PI * (index + 1) / segments;
    const p1 = [radius * Math.cos(a), radius * Math.sin(a), -height / 2];
    const p2 = [radius * Math.cos(b), radius * Math.sin(b), -height / 2];
    const p3 = [radius * Math.cos(a), radius * Math.sin(a), height / 2];
    const p4 = [radius * Math.cos(b), radius * Math.sin(b), height / 2];
    triangles.push([[0, 0, -height / 2], p2, p1], [[0, 0, height / 2], p3, p4], [p1, p2, p4], [p1, p4, p3]);
  }
  return triangles;
}

function loadSample(route) {
  const triangles = route === "C" ? makeBox(500, 110, 80) : route === "D" ? makeCylinder(55, 140) : makeBox(120, 72, 48);
  state.triangles = triangles;
  state.points = enrichedPoints(triangles);
  state.fileName = `пример-${route}.stl`;
  state.fileSize = 0;
  elements["file-meta"].textContent = `${state.fileName} · встроенная тестовая геометрия · ${triangles.length} треугольников`;
  elements["run-check"].disabled = false;
  elements["empty-view"].hidden = true;
  elements["empty-result"].hidden = false;
  elements["result-content"].hidden = true;
  resetError();
  addEvent(`загружен встроенный пример маршрута ${route}`);
  render();
  runCheck();
}

function render() {
  const canvas = elements.viewer;
  const rectangle = canvas.getBoundingClientRect();
  const ratio = Math.min(2, window.devicePixelRatio || 1);
  const width = Math.max(1, Math.floor(rectangle.width * ratio));
  const height = Math.max(1, Math.floor(rectangle.height * ratio));
  if (canvas.width !== width || canvas.height !== height) { canvas.width = width; canvas.height = height; }
  const context = canvas.getContext("2d");
  context.clearRect(0, 0, width, height);
  if (!state.triangles.length) return;
  const points = state.points;
  const center = [0, 1, 2].map((axis) => (Math.min(...points.map((point) => point[axis])) + Math.max(...points.map((point) => point[axis]))) / 2);
  const span = Math.max(...[0, 1, 2].map((axis) => Math.max(...points.map((point) => point[axis])) - Math.min(...points.map((point) => point[axis]))));
  const scale = Math.min(width, height) * state.zoom / Math.max(span, 1);
  const cosineX = Math.cos(state.rotationX), sineX = Math.sin(state.rotationX), cosineY = Math.cos(state.rotationY), sineY = Math.sin(state.rotationY);
  const project = (point) => {
    const x = point[0] - center[0], y = point[1] - center[1], z = point[2] - center[2];
    const x1 = cosineY * x + sineY * z;
    const z1 = -sineY * x + cosineY * z;
    const y1 = cosineX * y - sineX * z1;
    const z2 = sineX * y + cosineX * z1;
    return [width / 2 + x1 * scale, height / 2 - y1 * scale, z2];
  };
  const stride = Math.max(1, Math.ceil(state.triangles.length / 18000));
  const projected = [];
  for (let index = 0; index < state.triangles.length; index += stride) {
    const triangle = state.triangles[index].map(project);
    projected.push({ triangle, depth: triangle.reduce((sum, point) => sum + point[2], 0) / 3 });
  }
  projected.sort((a, b) => a.depth - b.depth);
  for (const face of projected) {
    const [a, b, c] = face.triangle;
    const cross = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
    const shade = Math.max(112, Math.min(210, 160 + cross / 180));
    context.beginPath();
    context.moveTo(a[0], a[1]);
    context.lineTo(b[0], b[1]);
    context.lineTo(c[0], c[1]);
    context.closePath();
    context.fillStyle = `rgb(${shade},${shade + 5},${shade + 10})`;
    context.strokeStyle = "rgba(37,53,74,0.46)";
    context.lineWidth = Math.max(0.55, ratio * 0.45);
    context.fill();
    context.stroke();
  }
}

function chooseView(view) {
  const rotations = { iso: [-0.5, 0.72], top: [-Math.PI / 2, 0], front: [0, 0], side: [0, Math.PI / 2] };
  [state.rotationX, state.rotationY] = rotations[view];
  document.querySelectorAll("[data-view]").forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.view === view)));
  render();
}

function downloadReport() {
  if (!state.report) return;
  const blob = new Blob([`${JSON.stringify(state.report, null, 2)}\n`], { type: "application/json" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `safesort-${state.report.decision.route}-report.json`;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(link.href), 0);
  addEvent("отчёт JSON скачан");
}

elements["stl-input"].addEventListener("change", (event) => loadFile(event.target.files[0]));
elements["change-file"].addEventListener("click", () => elements["stl-input"].click());
elements["retry-button"].addEventListener("click", () => elements["stl-input"].click());
elements["run-check"].addEventListener("click", runCheck);
elements["download-report"].addEventListener("click", downloadReport);
document.querySelectorAll("[data-sample]").forEach((button) => button.addEventListener("click", () => loadSample(button.dataset.sample)));
document.querySelectorAll("[data-view]").forEach((button) => button.addEventListener("click", () => chooseView(button.dataset.view)));

for (const eventName of ["dragenter", "dragover"]) elements["dropzone"].addEventListener(eventName, (event) => { event.preventDefault(); elements["dropzone"].classList.add("dragging"); });
for (const eventName of ["dragleave", "drop"]) elements["dropzone"].addEventListener(eventName, (event) => { event.preventDefault(); elements["dropzone"].classList.remove("dragging"); });
elements["dropzone"].addEventListener("drop", (event) => loadFile(event.dataTransfer.files[0]));

elements.viewer.addEventListener("pointerdown", (event) => { state.drag = [event.clientX, event.clientY]; elements.viewer.setPointerCapture(event.pointerId); });
elements.viewer.addEventListener("pointermove", (event) => {
  if (!state.drag) return;
  state.rotationY += (event.clientX - state.drag[0]) * 0.009;
  state.rotationX += (event.clientY - state.drag[1]) * 0.009;
  state.drag = [event.clientX, event.clientY];
  render();
});
elements.viewer.addEventListener("pointerup", () => { state.drag = null; });
elements.viewer.addEventListener("wheel", (event) => { event.preventDefault(); state.zoom = Math.max(0.35, Math.min(1.4, state.zoom - event.deltaY * 0.001)); render(); }, { passive: false });
elements.viewer.addEventListener("keydown", (event) => {
  const delta = event.shiftKey ? 0.2 : 0.08;
  if (event.key === "ArrowLeft") state.rotationY -= delta;
  else if (event.key === "ArrowRight") state.rotationY += delta;
  else if (event.key === "ArrowUp") state.rotationX -= delta;
  else if (event.key === "ArrowDown") state.rotationX += delta;
  else return;
  event.preventDefault();
  render();
});

window.addEventListener("resize", render);

const forcedState = new URLSearchParams(window.location.search).get("state");
if (forcedState === "loading") setLoading(true);
if (forcedState === "fault") showError("Тестовый отказ датчика глубины: маршрут B заблокирован до восстановления.");
if (forcedState === "partial") { loadSample("B"); elements["route-reason"].textContent = "частичный отчёт: подтверждение выхода ещё не получено"; }
if (forcedState === "tampered") showError("Контрольная сумма отчёта не совпала. Пакет помечен как изменённый.");

addEvent("демонстратор готов; сеть для анализа не используется");
