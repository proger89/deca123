"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const ROOT = path.resolve(__dirname, "..", "..");

function fakeCanvasContext() {
  return {
    arc() {},
    arcTo() {},
    beginPath() {},
    clearRect() {},
    closePath() {},
    ellipse() {},
    fill() {},
    fillRect() {},
    fillText() {},
    lineTo() {},
    measureText() { return { width: 0 }; },
    moveTo() {},
    restore() {},
    rotate() {},
    save() {},
    setLineDash() {},
    stroke() {},
    translate() {},
  };
}

function fakeElement() {
  return {
    classList: { add() {}, remove() {} },
    disabled: false,
    height: 560,
    hidden: false,
    style: {},
    textContent: "",
    width: 900,
    addEventListener() {},
    append() {},
    click() {},
    getBoundingClientRect() { return { height: 560, width: 900 }; },
    getContext() { return fakeCanvasContext(); },
    remove() {},
    setAttribute() {},
    setPointerCapture() {},
  };
}

function loadProductionGeometry() {
  const elementById = new Map();
  const document = {
    body: fakeElement(),
    createElement: () => fakeElement(),
    getElementById(id) {
      if (!elementById.has(id)) elementById.set(id, fakeElement());
      return elementById.get(id);
    },
    querySelector: () => null,
    querySelectorAll: () => [],
  };
  const window = {
    addEventListener() {},
    cancelAnimationFrame() {},
    devicePixelRatio: 1,
    location: { search: "" },
    matchMedia: () => ({ matches: true }),
    requestAnimationFrame: () => 0,
    setTimeout,
  };
  const context = {
    ArrayBuffer,
    Blob,
    DataView,
    Date,
    Intl,
    Math,
    TextDecoder,
    URL,
    URLSearchParams,
    Uint8Array,
    console,
    document,
    setTimeout,
    window,
  };
  const source = fs.readFileSync(path.join(ROOT, "web", "app.js"), "utf8");
  vm.runInNewContext(
    `${source}\n;globalThis.__safesortGeometry = { parseStl, measure, classify };`,
    context,
    { filename: "web/app.js" },
  );
  return context.__safesortGeometry;
}

function exactArrayBuffer(buffer) {
  return buffer.buffer.slice(buffer.byteOffset, buffer.byteOffset + buffer.byteLength);
}

function rotate(point) {
  const [x, y, z] = point;
  const az = 0.47;
  const ay = -0.31;
  const ax = 0.22;
  const x1 = Math.cos(az) * x - Math.sin(az) * y;
  const y1 = Math.sin(az) * x + Math.cos(az) * y;
  const z1 = z;
  const x2 = Math.cos(ay) * x1 + Math.sin(ay) * z1;
  const y2 = y1;
  const z2 = -Math.sin(ay) * x1 + Math.cos(ay) * z1;
  return [x2, Math.cos(ax) * y2 - Math.sin(ax) * z2, Math.sin(ax) * y2 + Math.cos(ax) * z2];
}

function boxTriangles(length, width, height) {
  const x = length / 2;
  const y = width / 2;
  const z = height / 2;
  const vertices = [
    [-x, -y, -z], [x, -y, -z], [x, y, -z], [-x, y, -z],
    [-x, -y, z], [x, -y, z], [x, y, z], [-x, y, z],
  ].map(rotate);
  return [
    [0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7],
    [0, 1, 5], [0, 5, 4], [1, 2, 6], [1, 6, 5],
    [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7],
  ].map((face) => face.map((index) => vertices[index]));
}

function cylinderTriangles(radius, height, segments = 64) {
  const triangles = [];
  for (let index = 0; index < segments; index += 1) {
    const a = 2 * Math.PI * index / segments;
    const b = 2 * Math.PI * (index + 1) / segments;
    const lowA = rotate([radius * Math.cos(a), radius * Math.sin(a), -height / 2]);
    const lowB = rotate([radius * Math.cos(b), radius * Math.sin(b), -height / 2]);
    const highA = rotate([radius * Math.cos(a), radius * Math.sin(a), height / 2]);
    const highB = rotate([radius * Math.cos(b), radius * Math.sin(b), height / 2]);
    const lowCenter = rotate([0, 0, -height / 2]);
    const highCenter = rotate([0, 0, height / 2]);
    triangles.push([lowCenter, lowB, lowA], [highCenter, highA, highB], [lowA, lowB, highB], [lowA, highB, highA]);
  }
  return triangles;
}

function asciiStl(triangles) {
  const facets = triangles.map((triangle) => {
    const vertices = triangle.map((point) => `      vertex ${point.join(" ")}`).join("\n");
    return `  facet normal 0 0 0\n    outer loop\n${vertices}\n    endloop\n  endfacet`;
  });
  return Buffer.from(`solid generated\n${facets.join("\n")}\nendsolid generated\n`, "utf8");
}

function binaryStl(triangles) {
  const buffer = Buffer.alloc(84 + triangles.length * 50);
  buffer.write("SafeSort generated binary STL", 0, "ascii");
  buffer.writeUInt32LE(triangles.length, 80);
  let offset = 84;
  for (const triangle of triangles) {
    offset += 12;
    for (const point of triangle) {
      for (const value of point) {
        buffer.writeFloatLE(value, offset);
        offset += 4;
      }
    }
    offset += 2;
  }
  return buffer;
}

const geometry = loadProductionGeometry();

test("strict 450 mm boundary fixture is parsed and routed to C", () => {
  const fixture = fs.readFileSync(path.join(ROOT, "tests", "fixtures", "web", "boundary-450.stl"));
  const triangles = geometry.parseStl(exactArrayBuffer(fixture));
  const metrics = geometry.measure(triangles);
  assert.ok(Math.abs(metrics.dimensions[0] - 450) < 0.01, `measured ${metrics.dimensions[0]} mm`);
  assert.equal(geometry.classify(metrics).route, "C");
});

test("invalid STL fixture is rejected by the production parser", () => {
  const fixture = fs.readFileSync(path.join(ROOT, "tests", "fixtures", "web", "invalid.stl"));
  assert.throws(() => geometry.parseStl(exactArrayBuffer(fixture)), /STL|ASCII|binary/i);
});

test("rotated ASCII box keeps dimensions and routes to B", () => {
  const triangles = geometry.parseStl(exactArrayBuffer(asciiStl(boxTriangles(200, 100, 50))));
  const metrics = geometry.measure(triangles);
  assert.deepEqual(Array.from(metrics.dimensions, (value) => Math.round(value)), [200, 100, 50]);
  assert.ok(metrics.circularity <= 0.8, `K=${metrics.circularity}`);
  assert.equal(geometry.classify(metrics).route, "B");
});

test("rotated binary cylinder keeps dimensions and routes to D", () => {
  const triangles = geometry.parseStl(exactArrayBuffer(binaryStl(cylinderTriangles(45, 180))));
  const metrics = geometry.measure(triangles);
  assert.deepEqual(Array.from(metrics.dimensions, (value) => Math.round(value)), [180, 90, 90]);
  assert.ok(metrics.circularity > 0.8, `K=${metrics.circularity}`);
  assert.equal(geometry.classify(metrics).route, "D");
});
