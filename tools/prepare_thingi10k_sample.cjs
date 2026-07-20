"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const ROOT = path.resolve(__dirname, "..");
const METADATA_DIR = path.join(ROOT, ".local-data", "thingi10k", "metadata");
const OUTPUT_DIR = path.join(ROOT, "datasets", "thingi10k-sample");
const TARGET_PER_ROUTE = Number(process.env.THINGI10K_PER_ROUTE || 20);
const MAX_DOWNLOAD_BYTES = 8 * 1024 * 1024;
const MAX_FACES = 30000;
const ROUTES = ["B", "C", "D"];

function parseCsv(source) {
  const rows = [];
  let row = [];
  let value = "";
  let quoted = false;
  for (let index = 0; index < source.length; index += 1) {
    const character = source[index];
    if (quoted) {
      if (character === '"' && source[index + 1] === '"') {
        value += '"';
        index += 1;
      } else if (character === '"') quoted = false;
      else value += character;
    } else if (character === '"') quoted = true;
    else if (character === ",") {
      row.push(value);
      value = "";
    } else if (character === "\n") {
      row.push(value.replace(/\r$/, ""));
      rows.push(row);
      row = [];
      value = "";
    } else value += character;
  }
  if (value || row.length) {
    row.push(value.replace(/\r$/, ""));
    rows.push(row);
  }
  const headers = rows.shift();
  return rows.filter((fields) => fields.length === headers.length).map((fields) => Object.fromEntries(headers.map((header, index) => [header, fields[index]])));
}

function seededShuffle(values, seed = 20260720) {
  let state = seed >>> 0;
  const random = () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return state / 0x100000000;
  };
  const result = [...values];
  for (let index = result.length - 1; index > 0; index -= 1) {
    const swapIndex = Math.floor(random() * (index + 1));
    [result[index], result[swapIndex]] = [result[swapIndex], result[index]];
  }
  return result;
}

function fakeCanvasContext() {
  return new Proxy({}, { get: (target, property) => target[property] || (() => ({ width: 0 })) });
}

function fakeElement() {
  return {
    classList: { add() {}, remove() {} }, disabled: false, height: 560, hidden: false, style: {}, textContent: "", width: 900,
    addEventListener() {}, append() {}, click() {}, getBoundingClientRect() { return { height: 560, width: 900 }; },
    getContext() { return fakeCanvasContext(); }, remove() {}, setAttribute() {}, setPointerCapture() {},
  };
}

function loadProductionGeometry() {
  const elementById = new Map();
  const document = {
    body: fakeElement(), createElement: () => fakeElement(), querySelector: () => null, querySelectorAll: () => [],
    getElementById(id) {
      if (!elementById.has(id)) elementById.set(id, fakeElement());
      return elementById.get(id);
    },
  };
  const window = {
    addEventListener() {}, cancelAnimationFrame() {}, devicePixelRatio: 1, location: { search: "" },
    matchMedia: () => ({ matches: true }), requestAnimationFrame: () => 0, setTimeout,
  };
  const context = { ArrayBuffer, Blob, DataView, Date, Intl, Math, TextDecoder, URL, URLSearchParams, Uint8Array, document, setTimeout, window };
  const source = fs.readFileSync(path.join(ROOT, "web", "app.js"), "utf8");
  vm.runInNewContext(`${source}\n;globalThis.__geometry = { parseStl, measure, classify };`, context, { filename: "web/app.js" });
  return context.__geometry;
}

function exactArrayBuffer(buffer) {
  return buffer.buffer.slice(buffer.byteOffset, buffer.byteOffset + buffer.byteLength);
}

function csvValue(value) {
  const text = String(value ?? "");
  return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

async function download(fileId) {
  const url = `https://huggingface.co/datasets/Thingi10K/Thingi10K/resolve/main/raw_meshes/${fileId}.stl?download=true`;
  const response = await fetch(url, { redirect: "follow", signal: AbortSignal.timeout(60000) });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const contentLength = Number(response.headers.get("content-length") || 0);
  if (contentLength > MAX_DOWNLOAD_BYTES) throw new Error(`file is ${contentLength} bytes`);
  const buffer = Buffer.from(await response.arrayBuffer());
  if (buffer.length > MAX_DOWNLOAD_BYTES) throw new Error(`file is ${buffer.length} bytes`);
  return { buffer, url };
}

async function main() {
  if (!Number.isInteger(TARGET_PER_ROUTE) || TARGET_PER_ROUTE < 1 || TARGET_PER_ROUTE > 33) throw new Error("THINGI10K_PER_ROUTE must be 1..33");
  const geometryRows = parseCsv(fs.readFileSync(path.join(METADATA_DIR, "geometry_data.csv"), "utf8"));
  const inputRows = parseCsv(fs.readFileSync(path.join(METADATA_DIR, "input_summary.csv"), "utf8"));
  const inputById = new Map(inputRows.map((row) => [row.ID, row]));
  const candidates = seededShuffle(geometryRows.filter((row) => {
    const input = inputById.get(row.file_id);
    return input && input.Link.toLowerCase().split("?")[0].endsWith(".stl")
      && row.solid === "1" && row.num_connected_components === "1" && row.num_self_intersections === "0"
      && Number(row.num_faces) <= MAX_FACES;
  }));
  const geometry = loadProductionGeometry();
  const selected = [];
  const counts = Object.fromEntries(ROUTES.map((route) => [route, 0]));
  let attempted = 0;
  for (const candidate of candidates) {
    if (ROUTES.every((route) => counts[route] >= TARGET_PER_ROUTE)) break;
    attempted += 1;
    try {
      const { buffer, url } = await download(candidate.file_id);
      const triangles = geometry.parseStl(exactArrayBuffer(buffer));
      const metrics = geometry.measure(triangles);
      const decision = geometry.classify(metrics);
      if (counts[decision.route] >= TARGET_PER_ROUTE) continue;
      const input = inputById.get(candidate.file_id);
      const routeDir = path.join(OUTPUT_DIR, decision.route);
      fs.mkdirSync(routeDir, { recursive: true });
      const fileName = `${candidate.file_id}.stl`;
      fs.writeFileSync(path.join(routeDir, fileName), buffer);
      counts[decision.route] += 1;
      const record = {
        file_id: candidate.file_id,
        expected_route: decision.route,
        length_mm: metrics.dimensions[0].toFixed(3),
        width_mm: metrics.dimensions[1].toFixed(3),
        height_mm: metrics.dimensions[2].toFixed(3),
        k: metrics.circularity.toFixed(6),
        triangles: triangles.length,
        bytes: buffer.length,
        license: input.License,
        thingiverse_source: input.Link,
        thingi10k_source: url,
        sha256: crypto.createHash("sha256").update(buffer).digest("hex"),
      };
      selected.push(record);
      process.stdout.write(`selected ${decision.route} ${counts[decision.route]}/${TARGET_PER_ROUTE}: ${candidate.file_id}\n`);
    } catch (error) {
      process.stdout.write(`skipped ${candidate.file_id}: ${error.message}\n`);
    }
  }
  if (!ROUTES.every((route) => counts[route] >= TARGET_PER_ROUTE)) throw new Error(`not enough balanced models: ${JSON.stringify(counts)} after ${attempted} attempts`);
  selected.sort((first, second) => first.expected_route.localeCompare(second.expected_route) || Number(first.file_id) - Number(second.file_id));
  fs.mkdirSync(OUTPUT_DIR, { recursive: true });
  fs.writeFileSync(path.join(OUTPUT_DIR, "manifest.json"), `${JSON.stringify({ generated_at: new Date().toISOString(), source: "Thingi10K", unit_assumption: "STL coordinates are interpreted as millimetres", filters: { solid: true, num_connected_components: 1, num_self_intersections: 0, max_faces: MAX_FACES }, counts, records: selected }, null, 2)}\n`);
  const headers = Object.keys(selected[0]);
  const csv = [headers.join(","), ...selected.map((record) => headers.map((header) => csvValue(record[header])).join(","))].join("\n");
  fs.writeFileSync(path.join(OUTPUT_DIR, "manifest.csv"), `${csv}\n`);
  process.stdout.write(`complete: ${selected.length} STL, B=${counts.B}, C=${counts.C}, D=${counts.D}, attempted=${attempted}\n`);
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error.message}\n`);
  process.exitCode = 1;
});
