"use strict";

const MAX_BYTES = 50 * 1024 * 1024;
const MAX_TRIANGLES = 400000;
const ADAPTIVE_SECTION_FRACTIONS = [
  0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.2, 0.3, 0.4, 0.5,
  0.6, 0.7, 0.8, 0.875, 0.9, 0.925, 0.95, 0.975, 0.99, 0.995,
];
const OBB_REFINEMENT_DEGREES = [30, 10, 3, 1];
const SURFACE_NORMAL_LIMIT = 6;
const ROUTES = {
  B: { name: "Маршрут B", subtitle: "Стандартный поток" },
  C: { name: "Маршрут C", subtitle: "Габаритный контроль" },
  D: { name: "Маршрут D", subtitle: "Круглая форма" },
};

const elements = Object.fromEntries([
  "stl-input", "run-check", "viewer", "viewer-shell", "empty-view", "loading-view",
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

function principalBasis(points) {
  const mean = [0, 1, 2].map((axis) => points.reduce((sum, point) => sum + point[axis], 0) / points.length);
  const covariance = Array.from({ length: 3 }, () => [0, 0, 0]);
  for (const point of points) {
    const d = point.map((value, axis) => value - mean[axis]);
    for (let row = 0; row < 3; row += 1) for (let col = 0; col < 3; col += 1) covariance[row][col] += d[row] * d[col];
  }
  for (let row = 0; row < 3; row += 1) for (let col = 0; col < 3; col += 1) covariance[row][col] /= Math.max(1, points.length - 1);
  const vectors = jacobiEigenvectors(covariance);
  return { mean, vectors };
}

function projectPoint(point, basis) {
  const centered = point.map((value, axis) => value - basis.mean[axis]);
  return basis.vectors.map((vector) => dot(centered, vector));
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

function sectionIntersections(triangle, axis, plane) {
  const points = [];
  const epsilon = 1e-7;
  for (const [startIndex, endIndex] of [[0, 1], [1, 2], [2, 0]]) {
    const start = triangle[startIndex];
    const end = triangle[endIndex];
    const startDistance = start[axis] - plane;
    const endDistance = end[axis] - plane;
    if (Math.abs(startDistance) <= epsilon && Math.abs(endDistance) <= epsilon) {
      points.push(start, end);
    } else if (Math.abs(startDistance) <= epsilon) {
      points.push(start);
    } else if (Math.abs(endDistance) <= epsilon) {
      points.push(end);
    } else if (startDistance * endDistance < 0) {
      const ratio = startDistance / (startDistance - endDistance);
      points.push(start.map((value, coordinate) => value + ratio * (end[coordinate] - value)));
    }
  }
  return [...new Map(points.map((point) => [point.map((value) => value.toFixed(7)).join(":"), point])).values()];
}

function maxSectionCircularity(triangles, basis, principalPoints, fractions, axes = [0, 1, 2]) {
  const triangleStride = Math.max(1, Math.ceil(triangles.length / 60000));
  const principalTriangles = [];
  for (let index = 0; index < triangles.length; index += triangleStride) {
    principalTriangles.push(triangles[index].map((point) => projectPoint(point, basis)));
  }
  let best = 0;
  for (const axis of axes) {
    let minimum = Infinity;
    let maximum = -Infinity;
    for (const point of principalPoints) {
      minimum = Math.min(minimum, point[axis]);
      maximum = Math.max(maximum, point[axis]);
    }
    const projectionAxes = [0, 1, 2].filter((candidate) => candidate !== axis);
    for (const fraction of fractions) {
      const plane = minimum + (maximum - minimum) * fraction;
      const section = [];
      for (const triangle of principalTriangles) {
        for (const point of sectionIntersections(triangle, axis, plane)) {
          section.push([point[projectionAxes[0]], point[projectionAxes[1]]]);
        }
      }
      if (section.length >= 3) best = Math.max(best, polygonCircularity(section));
    }
  }
  return best;
}

function frameBounds(points, basis) {
  const minimum = [Infinity, Infinity, Infinity];
  const maximum = [-Infinity, -Infinity, -Infinity];
  for (const source of points) {
    const centered = [source[0] - basis.mean[0], source[1] - basis.mean[1], source[2] - basis.mean[2]];
    for (let axis = 0; axis < 3; axis += 1) {
      const value = dot(centered, basis.vectors[axis]);
      minimum[axis] = Math.min(minimum[axis], value);
      maximum[axis] = Math.max(maximum[axis], value);
    }
  }
  const extents = minimum.map((value, axis) => maximum[axis] - value);
  return {
    extents,
    volume: extents.reduce((product, value) => product * value, 1),
  };
}

function rotateBasisAroundLocalAxis(basis, axis, angle) {
  const vectors = basis.vectors.map((vector) => [...vector]);
  const pairs = [[1, 2], [0, 2], [0, 1]];
  const [firstIndex, secondIndex] = pairs[axis];
  const first = vectors[firstIndex];
  const second = vectors[secondIndex];
  const cosine = Math.cos(angle);
  const sine = Math.sin(angle);
  vectors[firstIndex] = first.map((value, coordinate) => cosine * value + sine * second[coordinate]);
  vectors[secondIndex] = second.map((value, coordinate) => -sine * first[coordinate] + cosine * value);
  return { mean: basis.mean, vectors };
}

function refineMinimumVolumeBasis(points, initialBasis) {
  let bestBasis = initialBasis;
  let bestBounds = frameBounds(points, bestBasis);
  for (const stepDegrees of OBB_REFINEMENT_DEGREES) {
    const stepRadians = stepDegrees * Math.PI / 180;
    for (let axis = 0; axis < 3; axis += 1) {
      const baseBasis = bestBasis;
      let axisBestBasis = bestBasis;
      let axisBestBounds = bestBounds;
      for (const multiplier of [-2, -1, 0, 1, 2]) {
        const candidateBasis = rotateBasisAroundLocalAxis(baseBasis, axis, stepRadians * multiplier);
        const candidateBounds = frameBounds(points, candidateBasis);
        if (candidateBounds.volume < axisBestBounds.volume) {
          axisBestBasis = candidateBasis;
          axisBestBounds = candidateBounds;
        }
      }
      bestBasis = axisBestBasis;
      bestBounds = axisBestBounds;
    }
  }
  return { basis: bestBasis, bounds: bestBounds };
}

function normalizeVector(vector) {
  const length = Math.hypot(...vector);
  return length > 1e-12 ? vector.map((value) => value / length) : null;
}

function crossVector(first, second) {
  return [
    first[1] * second[2] - first[2] * second[1],
    first[2] * second[0] - first[0] * second[2],
    first[0] * second[1] - first[1] * second[0],
  ];
}

function canonicalDirection(vector) {
  const normalized = normalizeVector(vector);
  if (!normalized) return null;
  let largestIndex = 0;
  for (let index = 1; index < 3; index += 1) {
    if (Math.abs(normalized[index]) > Math.abs(normalized[largestIndex])) largestIndex = index;
  }
  return normalized[largestIndex] < 0 ? normalized.map((value) => -value) : normalized;
}

function dominantSurfaceNormals(triangles, limit = SURFACE_NORMAL_LIMIT) {
  const binSize = 7.5 * Math.PI / 180;
  const bins = new Map();
  for (const triangle of triangles) {
    const firstEdge = triangle[1].map((value, axis) => value - triangle[0][axis]);
    const secondEdge = triangle[2].map((value, axis) => value - triangle[0][axis]);
    const rawNormal = crossVector(firstEdge, secondEdge);
    const twiceArea = Math.hypot(...rawNormal);
    if (!(twiceArea > 1e-10) || !Number.isFinite(twiceArea)) continue;
    const normal = canonicalDirection(rawNormal);
    if (!normal) continue;
    const theta = Math.atan2(normal[1], normal[0]);
    const phi = Math.asin(Math.max(-1, Math.min(1, normal[2])));
    const key = `${Math.round(theta / binSize)}:${Math.round(phi / binSize)}`;
    const area = twiceArea / 2;
    const bin = bins.get(key) || { area: 0, vector: [0, 0, 0] };
    bin.area += area;
    for (let axis = 0; axis < 3; axis += 1) bin.vector[axis] += normal[axis] * area;
    bins.set(key, bin);
  }
  return [...bins.values()]
    .sort((first, second) => second.area - first.area)
    .slice(0, limit)
    .map((bin) => canonicalDirection(bin.vector))
    .filter(Boolean);
}

function candidateSectionNormals(triangles, refinedBasis, pcaBasis) {
  const candidates = [];
  const duplicateCosine = Math.cos(3 * Math.PI / 180);
  const add = (source) => {
    const normal = canonicalDirection(source);
    if (!normal) return;
    if (candidates.some((candidate) => Math.abs(dot(candidate, normal)) >= duplicateCosine)) return;
    candidates.push(normal);
  };
  refinedBasis.vectors.forEach(add);
  pcaBasis.vectors.forEach(add);
  dominantSurfaceNormals(triangles).forEach(add);
  return candidates;
}

function basisFromNormal(normal, mean) {
  const reference = Math.abs(normal[0]) < 0.8 ? [1, 0, 0] : [0, 1, 0];
  const first = normalizeVector(crossVector(normal, reference));
  if (!first) throw new Error("Не удалось построить базис сечения.");
  const second = normalizeVector(crossVector(normal, first));
  if (!second) throw new Error("Не удалось построить базис сечения.");
  return { mean, vectors: [first, second, normal] };
}

function circularityAcrossCandidateNormals(triangles, allPoints, normals, mean) {
  let best = 0;
  for (const normal of normals) {
    const basis = basisFromNormal(normal, mean);
    const transformedPoints = allPoints.map((point) => projectPoint(point, basis));
    best = Math.max(
      best,
      maxSectionCircularity(triangles, basis, transformedPoints, ADAPTIVE_SECTION_FRACTIONS, [2]),
    );
  }
  return best;
}

function measure(triangles) {
  const unique = [...new Map(triangles.flat().map((point) => [point.map((value) => value.toFixed(7)).join(":"), point])).values()];
  const stride = Math.max(1, Math.ceil(unique.length / 30000));
  const points = unique.filter((_, index) => index % stride === 0);
  if (!unique.every((point) => point.every(Number.isFinite))) throw new Error("В модели есть некорректные координаты.");
  const pcaBasis = principalBasis(points);
  const refinedSearch = refineMinimumVolumeBasis(points, pcaBasis);
  const refined = { basis: refinedSearch.basis, bounds: frameBounds(unique, refinedSearch.basis) };
  const extents = [...refined.bounds.extents].sort((first, second) => second - first);
  if (extents.some((value) => value <= 0 || !Number.isFinite(value))) throw new Error("Модель вырождена: один из размеров равен нулю.");
  const sectionNormals = candidateSectionNormals(triangles, refined.basis, pcaBasis);
  const circularity = circularityAcrossCandidateNormals(triangles, unique, sectionNormals, pcaBasis.mean);
  if (!(circularity > 0)) throw new Error("Не удалось построить замкнутое сечение для оценки K.");
  return {
    dimensions: extents,
    circularity,
    points,
    dimensionFrame: "refined minimum-volume OBB",
    circularityMethod: "refined OBB + dominant surface-normal adaptive sections",
    sectionPlanes: sectionNormals.length * ADAPTIVE_SECTION_FRACTIONS.length,
  };
}

function classify(metrics) {
  const [length, width, height] = metrics.dimensions;
  if (!(length > 10 && width > 10 && height > 10 && length < 450 && width < 320 && height < 320)) {
    return { route: "C", reason: "хотя бы один размер вне строгих границ 10 < L < 450 мм и 10 < W,H < 320 мм" };
  }
  if (metrics.circularity > 0.8) return { route: "D", reason: `размеры допустимы, но K = ${formatNumber(metrics.circularity)} > 0,80` };
  return { route: "B", reason: `размеры допустимы и K = ${formatNumber(metrics.circularity)} ≤ 0,80` };
}

function buildConveyorMesh(triangles) {
  const stride = Math.max(1, Math.ceil(triangles.length / 700));
  const sampled = [];
  const minimum = [Infinity, Infinity, Infinity];
  const maximum = [-Infinity, -Infinity, -Infinity];
  for (let index = 0; index < triangles.length; index += stride) {
    const triangle = triangles[index];
    if (!triangle.every((point) => point.every(Number.isFinite))) continue;
    sampled.push(triangle);
    for (const point of triangle) {
      for (let axis = 0; axis < 3; axis += 1) {
        minimum[axis] = Math.min(minimum[axis], point[axis]);
        maximum[axis] = Math.max(maximum[axis], point[axis]);
      }
    }
  }
  if (!sampled.length) return [];
  const center = minimum.map((value, axis) => (value + maximum[axis]) / 2);
  const span = Math.max(...minimum.map((value, axis) => maximum[axis] - value), 1);
  const rotationX = -0.55;
  const rotationY = 0.72;
  const cosineX = Math.cos(rotationX);
  const sineX = Math.sin(rotationX);
  const cosineY = Math.cos(rotationY);
  const sineY = Math.sin(rotationY);
  const project = (point) => {
    const x = point[0] - center[0];
    const y = point[1] - center[1];
    const z = point[2] - center[2];
    const x1 = cosineY * x + sineY * z;
    const z1 = -sineY * x + cosineY * z;
    const y1 = cosineX * y - sineX * z1;
    const z2 = sineX * y + cosineX * z1;
    return [x1 / span, y1 / span, z2 / span];
  };
  return sampled
    .map((triangle) => {
      const projected = triangle.map(project);
      return { triangle: projected, depth: projected.reduce((sum, point) => sum + point[2], 0) / 3 };
    })
    .sort((a, b) => a.depth - b.depth);
}

function setMode(mode, announceChange = false) {
  if (!new Set(["model", "conveyor"]).has(mode)) return;
  state.mode = mode;
  document.querySelectorAll("[data-mode]").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.mode === mode));
  });
  const viewButtons = document.querySelector(".view-buttons");
  if (viewButtons) {
    viewButtons.hidden = mode === "conveyor";
    viewButtons.style.display = mode === "conveyor" ? "none" : "flex";
  }
  elements.viewer.setAttribute(
    "aria-label",
    mode === "conveyor"
      ? "Виртуальный конвейер. Нажмите Enter или пробел, чтобы повторить цикл; клавишу F — чтобы показать безопасный отказ."
      : "Трёхмерный просмотр загруженной STL-модели. Модель можно вращать перетаскиванием или стрелками.",
  );
  if (announceChange) announce(mode === "conveyor" ? "Открыт виртуальный конвейер." : "Открыт просмотр товара.");
  render();
}

function cancelCycle(resetStatus = false) {
  state.cycle.serial += 1;
  if (state.cycle.frame) window.cancelAnimationFrame(state.cycle.frame);
  state.cycle.frame = 0;
  state.cycle.active = false;
  state.cycle.fault = false;
  state.cycle.requestedRoute = null;
  state.cycle.effectiveRoute = null;
  state.cycle.progress = 0;
  state.cycle.stage = -1;
  state.cycle.complete = false;
  if (elements["repeat-cycle"]) elements["repeat-cycle"].disabled = !state.decision;
  if (elements["fault-cycle"]) elements["fault-cycle"].disabled = !state.decision;
  if (resetStatus && elements["cycle-status"]) elements["cycle-status"].textContent = "ожидает запуска";
}

function cycleStage(progress) {
  if (progress < 0.14) return 0;
  if (progress < 0.48) return 1;
  if (progress < 0.64) return 2;
  if (progress < 0.94) return 3;
  return 4;
}

function updateCycleStage(stage) {
  if (stage === state.cycle.stage) return;
  state.cycle.stage = stage;
  const route = state.cycle.effectiveRoute;
  const requested = state.cycle.requestedRoute;
  const regular = [
    "STL передан цифровому симулятору; товар принят входной лентой",
    "5 датчиков формируют пакеты карт глубины (depth-view)",
    `решение ${requested} принято; заслонка ${requested} открыта, остальные закрыты`,
    `товар движется по ветке ${route} к выходному датчику`,
    `выход ${route} подтверждён; цикл завершён без потери товара`,
  ];
  const failSafe = [
    "STL передан цифровому симулятору; включён тест отказа привода",
    "5 датчиков сформировали пакеты карт глубины; решение сохранено",
    `команда приводу не подтверждена: автоматический маршрут ${requested} заблокирован`,
    "пассивная безопасная заслонка направляет товар в карантинный маршрут C",
    "безопасный выход C подтверждён; линия остановлена для диагностики",
  ];
  const message = (state.cycle.fault ? failSafe : regular)[stage];
  elements["cycle-status"].textContent = message;
  addEvent(`конвейер: ${message}`);
  announce(message);
  if (stage === 4) {
    state.cycle.active = false;
    state.cycle.complete = true;
    elements["repeat-cycle"].disabled = false;
    elements["fault-cycle"].disabled = false;
  }
}

function startCycle(requestedRoute, fault = false) {
  if (!state.triangles.length || !state.decision) return;
  cancelCycle();
  const serial = state.cycle.serial;
  state.cycle.active = true;
  state.cycle.fault = fault;
  state.cycle.requestedRoute = requestedRoute;
  state.cycle.effectiveRoute = fault ? "C" : requestedRoute;
  state.cycle.progress = 0;
  state.cycle.stage = -1;
  state.cycle.complete = false;
  elements["repeat-cycle"].disabled = true;
  elements["fault-cycle"].disabled = true;
  setMode("conveyor");
  updateCycleStage(0);

  if (reducedMotionQuery.matches) {
    for (let stage = 1; stage <= 4; stage += 1) updateCycleStage(stage);
    state.cycle.progress = 1;
    render();
    return;
  }

  const duration = fault ? 5600 : 5000;
  let startedAt = null;
  const tick = (timestamp) => {
    if (serial !== state.cycle.serial) return;
    if (startedAt === null) startedAt = timestamp;
    state.cycle.progress = Math.min(1, (timestamp - startedAt) / duration);
    updateCycleStage(cycleStage(state.cycle.progress));
    render();
    if (state.cycle.progress < 1) state.cycle.frame = window.requestAnimationFrame(tick);
    else state.cycle.frame = 0;
  };
  state.cycle.frame = window.requestAnimationFrame(tick);
}

async function loadFile(file) {
  const token = ++state.loadToken;
  resetError();
  if (!file || !file.name.toLowerCase().endsWith(".stl")) return showError("Выберите файл с расширением .stl.");
  if (file.size > MAX_BYTES) return showError("Файл больше 50 МБ. Упростите сетку или используйте офлайн-симулятор.");
  cancelCycle(true);
  state.triangles = [];
  state.points = [];
  state.conveyorMesh = [];
  state.decision = null;
  setMode("model");
  setLoading(true);
  addEvent(`получен файл ${file.name}, ${file.size.toLocaleString("ru-RU")} байт`);
  try {
    const buffer = await file.arrayBuffer();
    if (token !== state.loadToken) return;
    const triangles = parseStl(buffer);
    state.triangles = triangles;
    state.points = enrichedPoints(triangles);
    state.conveyorMesh = buildConveyorMesh(triangles);
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
    addEvent("построены уточнённый OBB и адаптивные сечения по осям и нормалям поверхности");
    const metrics = measure(state.triangles);
    const decision = classify(metrics);
    state.metrics = metrics;
    state.decision = decision;
    state.report = await makeReport(metrics, decision);
    showResult(metrics, decision);
    addEvent(`назначен маршрут ${decision.route}; решение зафиксировано контрольной суммой`);
    announce(`Проверка завершена. Назначен маршрут ${decision.route}.`);
    startCycle(decision.route);
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
    measurement: {
      dimensions_mm: metrics.dimensions.map((value) => Number(value.toFixed(4))),
      circularity_k_estimate: Number(metrics.circularity.toFixed(6)),
      dimension_frame: metrics.dimensionFrame,
      method: metrics.circularityMethod,
      section_planes: metrics.sectionPlanes,
    },
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
  cancelCycle();
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

function makeSphere(radius, latitudeSegments = 18, longitudeSegments = 48) {
  const triangles = [];
  const point = (latitude, longitude) => [
    radius * Math.cos(latitude) * Math.cos(longitude),
    radius * Math.cos(latitude) * Math.sin(longitude),
    radius * Math.sin(latitude),
  ];
  for (let latitudeIndex = 0; latitudeIndex < latitudeSegments; latitudeIndex += 1) {
    const latitudeA = -Math.PI / 2 + Math.PI * latitudeIndex / latitudeSegments;
    const latitudeB = -Math.PI / 2 + Math.PI * (latitudeIndex + 1) / latitudeSegments;
    for (let longitudeIndex = 0; longitudeIndex < longitudeSegments; longitudeIndex += 1) {
      const longitudeA = 2 * Math.PI * longitudeIndex / longitudeSegments;
      const longitudeB = 2 * Math.PI * (longitudeIndex + 1) / longitudeSegments;
      const a = point(latitudeA, longitudeA);
      const b = point(latitudeA, longitudeB);
      const c = point(latitudeB, longitudeA);
      const d = point(latitudeB, longitudeB);
      if (latitudeIndex > 0) triangles.push([a, d, c]);
      if (latitudeIndex < latitudeSegments - 1) triangles.push([a, b, d]);
    }
  }
  return triangles;
}

function loadSample(route) {
  cancelCycle(true);
  const triangles = route === "C" ? makeBox(500, 110, 80) : route === "D" ? makeSphere(60) : makeBox(120, 72, 48);
  state.triangles = triangles;
  state.points = enrichedPoints(triangles);
  state.conveyorMesh = buildConveyorMesh(triangles);
  state.decision = null;
  setMode("model");
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
  return runCheck();
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
  if (state.mode === "conveyor") {
    renderConveyor(context, width, height, ratio);
    return;
  }
  renderModel(context, width, height, ratio);
}

function bounds3(points) {
  const minimum = [Infinity, Infinity, Infinity];
  const maximum = [-Infinity, -Infinity, -Infinity];
  for (const point of points) {
    for (let axis = 0; axis < 3; axis += 1) {
      minimum[axis] = Math.min(minimum[axis], point[axis]);
      maximum[axis] = Math.max(maximum[axis], point[axis]);
    }
  }
  return { minimum, maximum };
}

function renderModel(context, width, height, ratio) {
  if (!state.triangles.length) return;
  const points = state.points;
  const { minimum, maximum } = bounds3(points);
  const center = minimum.map((value, axis) => (value + maximum[axis]) / 2);
  const span = Math.max(...minimum.map((value, axis) => maximum[axis] - value));
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

function drawPolyline(context, points, width, color, dash = []) {
  context.beginPath();
  points.forEach((point, index) => {
    const method = index === 0 ? "moveTo" : "lineTo";
    context[method](point[0], point[1]);
  });
  context.lineWidth = width;
  context.lineCap = "round";
  context.lineJoin = "round";
  context.strokeStyle = color;
  context.setLineDash(dash);
  context.stroke();
  context.setLineDash([]);
}

function roundedRect(context, x, y, width, height, radius) {
  const safeRadius = Math.min(radius, width / 2, height / 2);
  context.beginPath();
  context.moveTo(x + safeRadius, y);
  context.arcTo(x + width, y, x + width, y + height, safeRadius);
  context.arcTo(x + width, y + height, x, y + height, safeRadius);
  context.arcTo(x, y + height, x, y, safeRadius);
  context.arcTo(x, y, x + width, y, safeRadius);
  context.closePath();
}

function conveyorPath(route, width, height) {
  const scale = ([x, y]) => [x * width, y * height];
  const paths = {
    B: [[0.60, 0.53], [0.96, 0.53]],
    C: [[0.60, 0.55], [0.76, 0.72], [0.96, 0.80]],
    D: [[0.60, 0.51], [0.76, 0.34], [0.96, 0.24]],
  };
  return paths[route].map(scale);
}

function pointAlongPolyline(points, progress) {
  const lengths = points.slice(1).map((point, index) => Math.hypot(point[0] - points[index][0], point[1] - points[index][1]));
  const total = lengths.reduce((sum, value) => sum + value, 0);
  let remaining = Math.max(0, Math.min(1, progress)) * total;
  for (let index = 0; index < lengths.length; index += 1) {
    if (remaining <= lengths[index] || index === lengths.length - 1) {
      const fraction = lengths[index] ? remaining / lengths[index] : 0;
      const from = points[index];
      const to = points[index + 1];
      return {
        x: from[0] + (to[0] - from[0]) * fraction,
        y: from[1] + (to[1] - from[1]) * fraction,
        angle: Math.atan2(to[1] - from[1], to[0] - from[0]),
      };
    }
    remaining -= lengths[index];
  }
  const last = points.at(-1);
  return { x: last[0], y: last[1], angle: 0 };
}

function productPosition(progress, route, width, height) {
  if (progress <= 0.64) {
    const fraction = progress / 0.64;
    return { x: width * (0.07 + 0.53 * fraction), y: height * 0.53, angle: 0 };
  }
  return pointAlongPolyline(conveyorPath(route, width, height), (progress - 0.64) / 0.36);
}

function drawMovingProduct(context, position, size, color, fault) {
  if (!state.conveyorMesh.length) return;
  context.save();
  context.translate(position.x, position.y);
  context.rotate(position.angle);
  context.fillStyle = "rgba(0, 0, 0, 0.28)";
  context.beginPath();
  context.ellipse(2, size * 0.38, size * 0.58, size * 0.18, 0, 0, Math.PI * 2);
  context.fill();
  for (const face of state.conveyorMesh) {
    const [a, b, c] = face.triangle;
    const shade = Math.round(Math.max(145, Math.min(224, 185 + face.depth * 70)));
    context.beginPath();
    context.moveTo(a[0] * size * 1.35, -a[1] * size * 1.35);
    context.lineTo(b[0] * size * 1.35, -b[1] * size * 1.35);
    context.lineTo(c[0] * size * 1.35, -c[1] * size * 1.35);
    context.closePath();
    context.fillStyle = `rgb(${shade},${Math.min(234, shade + 6)},${Math.min(242, shade + 13)})`;
    context.strokeStyle = fault ? "rgba(255,170,90,0.72)" : color;
    context.lineWidth = Math.max(0.45, size * 0.012);
    context.fill();
    context.stroke();
  }
  context.restore();
}

function drawRouteBadge(context, route, x, y, color, active, ratio) {
  const radius = 17 * ratio;
  context.beginPath();
  context.arc(x, y, radius, 0, Math.PI * 2);
  context.fillStyle = active ? color : "#203d60";
  context.fill();
  context.strokeStyle = active ? "#ffffff" : "#7691b0";
  context.lineWidth = 1.4 * ratio;
  context.stroke();
  context.fillStyle = "#ffffff";
  context.font = `700 ${14 * ratio}px "Segoe UI", Arial, sans-serif`;
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.fillText(route, x, y + ratio);
}

function drawGate(context, route, width, height, ratio, activeRoute, fault) {
  const positions = {
    B: [0.67, 0.53, Math.PI / 2],
    C: [0.665, 0.615, -0.72],
    D: [0.665, 0.445, 0.72],
  };
  const [x, y, closedAngle] = positions[route];
  const isOpen = activeRoute === route && state.cycle.progress >= 0.48;
  const isBlockedB = fault && route === "B" && state.cycle.progress >= 0.48;
  context.save();
  context.translate(x * width, y * height);
  context.rotate(isOpen ? 0 : closedAngle);
  context.fillStyle = isBlockedB ? "#ff6b5f" : isOpen ? "#5ee08a" : "#a9b9cb";
  roundedRect(context, -18 * ratio, -3 * ratio, 36 * ratio, 6 * ratio, 3 * ratio);
  context.fill();
  context.restore();
  if (isBlockedB) {
    context.fillStyle = "#ffb4ae";
    context.font = `700 ${10 * ratio}px "Segoe UI", Arial, sans-serif`;
    context.textAlign = "center";
    context.fillText("B ЗАБЛОКИРОВАН", x * width, y * height - 15 * ratio);
  }
}

function renderConveyor(context, width, height, ratio) {
  const routeColors = { B: "#3fd77a", C: "#ffb45b", D: "#bd8cff" };
  const activeRoute = state.cycle.effectiveRoute || state.decision?.route || null;
  const beltWidth = Math.max(38 * ratio, Math.min(width, height) * 0.105);
  const entry = [[0.035 * width, 0.53 * height], [0.60 * width, 0.53 * height]];

  context.fillStyle = "#071d3c";
  context.fillRect(0, 0, width, height);
  context.strokeStyle = "rgba(145, 182, 221, 0.06)";
  context.lineWidth = ratio;
  const grid = 34 * ratio;
  for (let x = 0; x <= width; x += grid) { context.beginPath(); context.moveTo(x, 0); context.lineTo(x, height); context.stroke(); }
  for (let y = 0; y <= height; y += grid) { context.beginPath(); context.moveTo(0, y); context.lineTo(width, y); context.stroke(); }

  context.fillStyle = "#c8dbef";
  context.font = `600 ${Math.max(11, 12 * ratio)}px "Segoe UI", Arial, sans-serif`;
  context.textAlign = "center";
  context.textBaseline = "middle";
  const compact = width / ratio < 650;
  const veryCompact = width / ratio < 430;
  const processLabel = veryCompact
    ? "5 датчиков → решение → выход"
    : compact
      ? "STL → 5 датчиков → заслонка → выход"
      : "STL → 5 датчиков глубины → решение → заслонка → подтверждённый выход";
  context.fillText(processLabel, width * (veryCompact ? 0.50 : compact ? 0.52 : 0.55), 40 * ratio);

  const allPaths = { B: conveyorPath("B", width, height), C: conveyorPath("C", width, height), D: conveyorPath("D", width, height) };
  drawPolyline(context, entry, beltWidth + 5 * ratio, "#0a1324");
  drawPolyline(context, entry, beltWidth, "#1a3a5f");
  for (const route of ["B", "C", "D"]) {
    drawPolyline(context, allPaths[route], beltWidth + 5 * ratio, "#0a1324");
    drawPolyline(context, allPaths[route], beltWidth, activeRoute === route ? "#244f72" : "#183450");
    drawPolyline(context, allPaths[route], 1.2 * ratio, activeRoute === route ? routeColors[route] : "#6883a2", [8 * ratio, 9 * ratio]);
  }
  drawPolyline(context, entry, 1.2 * ratio, "#70a6d8", [8 * ratio, 9 * ratio]);

  const sensorStart = 0.25;
  const sensorStep = 0.058;
  for (let index = 0; index < 5; index += 1) {
    const x = (sensorStart + sensorStep * index) * width;
    const threshold = 0.20 + index * 0.055;
    const active = state.cycle.progress >= threshold;
    context.strokeStyle = active ? "#5ee8ff" : "#597998";
    context.lineWidth = active ? 3 * ratio : 1.5 * ratio;
    context.beginPath();
    context.moveTo(x, 0.53 * height - beltWidth * 0.64);
    context.lineTo(x, 0.53 * height + beltWidth * 0.64);
    context.stroke();
    context.fillStyle = active ? "#baf6ff" : "#91a8c1";
    context.font = `700 ${10 * ratio}px "Segoe UI", Arial, sans-serif`;
    context.textAlign = "center";
    context.fillText(String(index + 1), x, 0.53 * height - beltWidth * 0.83);
  }
  context.fillStyle = "#a8c0d9";
  context.font = `600 ${10.5 * ratio}px "Segoe UI", Arial, sans-serif`;
  context.fillText("5 ДАТЧИКОВ ГЛУБИНЫ", 0.365 * width, 0.53 * height + beltWidth * 0.88);

  for (const route of ["B", "C", "D"]) drawGate(context, route, width, height, ratio, activeRoute, state.cycle.fault);
  drawRouteBadge(context, "D", width * 0.956, height * 0.24, routeColors.D, activeRoute === "D", ratio);
  drawRouteBadge(context, "B", width * 0.956, height * 0.53, routeColors.B, activeRoute === "B", ratio);
  drawRouteBadge(context, "C", width * 0.956, height * 0.80, routeColors.C, activeRoute === "C", ratio);

  if (state.triangles.length) {
    const position = productPosition(state.cycle.progress, activeRoute || "B", width, height);
    const productSize = Math.max(46 * ratio, Math.min(width, height) * 0.12);
    drawMovingProduct(context, position, productSize, routeColors[activeRoute] || "#70a6d8", state.cycle.fault);
  }

  if (state.cycle.complete && activeRoute) {
    const destination = productPosition(1, activeRoute, width, height);
    const label = `Выход ${activeRoute} подтверждён`;
    context.font = `700 ${11 * ratio}px "Segoe UI", Arial, sans-serif`;
    const labelWidth = context.measureText(label).width + 24 * ratio;
    const labelX = Math.max(8 * ratio, Math.min(width - labelWidth - 8 * ratio, destination.x - labelWidth));
    const labelY = activeRoute === "D" ? destination.y + 30 * ratio : destination.y - 43 * ratio;
    roundedRect(context, labelX, labelY, labelWidth, 28 * ratio, 6 * ratio);
    context.fillStyle = state.cycle.fault ? "#8a351e" : "#0c5b35";
    context.fill();
    context.fillStyle = "#ffffff";
    context.textAlign = "center";
    context.fillText(label, labelX + labelWidth / 2, labelY + 14 * ratio);
  }

  context.fillStyle = "#8faac6";
  context.font = `500 ${10 * ratio}px "Segoe UI", Arial, sans-serif`;
  context.textAlign = "left";
  const previewLabel = compact
    ? "Цифровой предпросмотр · 5 depth-view пакетов"
    : "Цифровой предпросмотр; основной runtime получает пять пакетов карт глубины";
  context.fillText(previewLabel, 15 * ratio, height - 14 * ratio);
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
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(link.href), 1500);
  addEvent("отчёт JSON скачан");
}

elements["stl-input"].addEventListener("change", (event) => loadFile(event.target.files[0]));
elements["retry-button"].addEventListener("click", () => elements["stl-input"].click());
elements["run-check"].addEventListener("click", runCheck);
elements["download-report"].addEventListener("click", downloadReport);
document.querySelectorAll("[data-sample]").forEach((button) => button.addEventListener("click", () => loadSample(button.dataset.sample)));
document.querySelectorAll("[data-view]").forEach((button) => button.addEventListener("click", () => chooseView(button.dataset.view)));
document.querySelectorAll("[data-mode]").forEach((button) => button.addEventListener("click", () => setMode(button.dataset.mode, true)));
elements["repeat-cycle"].addEventListener("click", () => startCycle(state.decision?.route));
elements["fault-cycle"].addEventListener("click", () => startCycle(state.decision?.route, true));

for (const eventName of ["dragenter", "dragover"]) elements["dropzone"].addEventListener(eventName, (event) => { event.preventDefault(); elements["dropzone"].classList.add("dragging"); });
for (const eventName of ["dragleave", "drop"]) elements["dropzone"].addEventListener(eventName, (event) => { event.preventDefault(); elements["dropzone"].classList.remove("dragging"); });
elements["dropzone"].addEventListener("drop", (event) => loadFile(event.dataTransfer.files[0]));

elements.viewer.addEventListener("pointerdown", (event) => {
  if (state.mode !== "model") return;
  state.drag = [event.clientX, event.clientY];
  elements.viewer.setPointerCapture(event.pointerId);
});
elements.viewer.addEventListener("pointermove", (event) => {
  if (!state.drag) return;
  state.rotationY += (event.clientX - state.drag[0]) * 0.009;
  state.rotationX += (event.clientY - state.drag[1]) * 0.009;
  state.drag = [event.clientX, event.clientY];
  render();
});
elements.viewer.addEventListener("pointerup", () => { state.drag = null; });
elements.viewer.addEventListener("wheel", (event) => {
  if (state.mode !== "model") return;
  event.preventDefault();
  state.zoom = Math.max(0.35, Math.min(1.4, state.zoom - event.deltaY * 0.001));
  render();
}, { passive: false });
elements.viewer.addEventListener("keydown", (event) => {
  if (state.mode === "conveyor") {
    if (event.key === "Enter" || event.key === " ") startCycle(state.decision?.route);
    else if (event.key.toLowerCase() === "f") startCycle(state.decision?.route, true);
    else return;
    event.preventDefault();
    return;
  }
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

setMode("model");

const forcedState = new URLSearchParams(window.location.search).get("state");
if (forcedState === "loading") setLoading(true);
if (forcedState === "fault") showError("Тестовый отказ датчика глубины: маршрут B заблокирован до восстановления.");
if (forcedState === "partial") {
  loadSample("B").then(() => {
    cancelCycle();
    elements["route-reason"].textContent = "частичный отчёт: подтверждение выхода ещё не получено";
    elements["cycle-status"].textContent = "решение B рассчитано, подтверждение физического выхода ожидается";
  });
}
if (forcedState === "tampered") showError("Контрольная сумма отчёта не совпала. Пакет помечен как изменённый.");

addEvent("демонстратор готов; сеть для анализа не используется");
