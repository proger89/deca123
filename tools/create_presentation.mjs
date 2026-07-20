import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";

const artifactModule = process.env.ARTIFACT_TOOL_MODULE;
if (!artifactModule) {
  throw new Error("Set ARTIFACT_TOOL_MODULE to @oai/artifact-tool/dist/artifact_tool.mjs");
}
const { Presentation, PresentationFile } = await import(pathToFileURL(artifactModule).href);

const root = process.cwd();
const output = path.join(root, "submission", "final");
const renders = path.join(root, "artifacts", "presentation-render");

const C = {
  navy: "#071a37",
  navy2: "#0c2b55",
  blue: "#0b6ff4",
  cyan: "#dff2ff",
  ink: "#0b1f3a",
  muted: "#5f6f85",
  line: "#d7e0eb",
  bg: "#f4f7fb",
  white: "#ffffff",
  green: "#157f5b",
  amber: "#c36a00",
  red: "#b42318",
};

async function bytes(file) {
  const value = await fs.readFile(path.join(root, file));
  return value.buffer.slice(value.byteOffset, value.byteOffset + value.byteLength);
}

async function writeBlob(file, blob) {
  await fs.writeFile(file, new Uint8Array(await blob.arrayBuffer()));
}

function text(slide, value, position, style = {}) {
  const shape = slide.shapes.add({
    geometry: "textbox",
    position,
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  shape.text = value;
  shape.text.style = {
    fontFamily: "Aptos",
    fontSize: 20,
    color: C.ink,
    verticalAlignment: "middle",
    ...style,
  };
  return shape;
}

function box(slide, position, fill = C.white, line = C.line, radius = "rounded-xl") {
  return slide.shapes.add({
    geometry: "roundRect",
    position,
    fill,
    line: { style: "solid", fill: line, width: 1 },
    borderRadius: radius,
  });
}

function badge(slide, value, position, fill, color = C.white) {
  const shape = box(slide, position, fill, fill, "rounded-full");
  shape.text = value;
  shape.text.style = {
    fontFamily: "Aptos",
    fontSize: 15,
    bold: true,
    color,
    alignment: "center",
    verticalAlignment: "middle",
  };
  return shape;
}

function base(presentation, kicker, titleValue, footer) {
  const slide = presentation.slides.add();
  slide.background.fill = C.bg;
  text(slide, kicker.toUpperCase(), { left: 64, top: 34, width: 520, height: 24 }, { fontSize: 13, bold: true, color: C.blue });
  text(slide, titleValue, { left: 64, top: 66, width: 1120, height: 64 }, { fontSize: 36, bold: true, color: C.ink });
  text(slide, `SafeSort · ${footer}`, { left: 1030, top: 658, width: 186, height: 20 }, { fontSize: 12, color: C.muted, alignment: "right" });
  return slide;
}

async function addImage(slide, file, position, alt, fit = "cover") {
  slide.images.add({
    blob: await bytes(file),
    contentType: "image/png",
    alt,
    fit,
    position,
    geometry: "roundRect",
    borderRadius: "rounded-xl",
  });
}

function metric(slide, value, label, left, top, color = C.blue) {
  text(slide, value, { left, top, width: 235, height: 62 }, { fontSize: 42, bold: true, color });
  text(slide, label, { left, top: top + 66, width: 255, height: 64 }, { fontSize: 17, color: C.muted });
}

async function main() {
  await fs.mkdir(output, { recursive: true });
  await fs.mkdir(renders, { recursive: true });
  const deck = Presentation.create({ slideSize: { width: 1280, height: 720 } });

  // 1. Open with the result, not with the technology.
  {
    const slide = deck.slides.add();
    slide.background.fill = C.navy;
    badge(slide, "ЗАДАЧА 3 · ROBOZONE / OZON", { left: 68, top: 55, width: 280, height: 34 }, C.blue);
    text(slide, "SafeSort", { left: 68, top: 126, width: 485, height: 72 }, { fontSize: 58, bold: true, color: C.white });
    text(slide, "Измерили → направили → подтвердили", { left: 68, top: 216, width: 495, height: 80 }, { fontSize: 30, bold: true, color: "#d7e4f4" });
    text(slide, "Цифровой испытательный стенд сортировочной ячейки", { left: 68, top: 322, width: 480, height: 70 }, { fontSize: 21, color: "#7fc8ff" });
    await addImage(slide, "artifacts/design-audit/04-supplied-box-route-b.png", { left: 590, top: 74, width: 620, height: 492 }, "Рабочее браузерное демо SafeSort с загруженным STL и маршрутом B");
    text(slide, "Неизвестный товар → маршрут B → выход B подтверждён", { left: 590, top: 584, width: 620, height: 34 }, { fontSize: 20, bold: true, color: C.white, alignment: "center" });
    text(slide, "Работает локально · запускается через Docker · STL остаётся в браузере", { left: 68, top: 610, width: 880, height: 28 }, { fontSize: 16, color: "#c8d8ec" });
  }

  // 2. Explain the two contours and where computer vision lives.
  {
    const slide = base(deck, "Как работает система", "Во время сортировки контроллер видит датчики, а не файл STL", "2/6");
    box(slide, { left: 64, top: 166, width: 474, height: 388 }, C.white);
    text(slide, "Подготовка испытания", { left: 94, top: 188, width: 410, height: 38 }, { fontSize: 23, bold: true, color: C.navy2 });
    text(slide, "STL задаёт форму виртуального товара", { left: 94, top: 249, width: 410, height: 52 }, { fontSize: 21, bold: true });
    text(slide, "В браузере жюри проверяет размеры, форму и выбранный маршрут.", { left: 94, top: 316, width: 410, height: 82 }, { fontSize: 19, color: C.muted });
    text(slide, "Файл не передаётся автоматически в Webots.", { left: 94, top: 437, width: 410, height: 54 }, { fontSize: 18, bold: true, color: C.blue });

    box(slide, { left: 570, top: 166, width: 618, height: 388 }, C.white);
    text(slide, "Цикл сортировки в Webots", { left: 600, top: 188, width: 548, height: 38 }, { fontSize: 23, bold: true, color: C.navy2 });
    const chain = [
      ["1", "5 карт\nглубины"],
      ["2", "Размеры\nи форма"],
      ["3", "Маршрут\nB / C / D"],
      ["4", "Заслонки"],
      ["5", "Датчик\nвыхода"],
    ];
    for (let i = 0; i < 4; i += 1) {
      slide.shapes.add({ geometry: "chevron", position: { left: 701 + i * 106, top: 330, width: 34, height: 46 }, fill: "#8fbdf7", line: { style: "solid", fill: "#8fbdf7", width: 0 } });
    }
    chain.forEach(([n, label], i) => {
      const left = 592 + i * 106;
      badge(slide, n, { left: left + 24, top: 272, width: 42, height: 42 }, C.blue);
      text(slide, label, { left, top: 328, width: 90, height: 72 }, { fontSize: 16, bold: true, alignment: "center" });
    });
    text(slide, "Компьютерное зрение здесь — восстановление геометрии по пяти картам глубины.", { left: 610, top: 446, width: 538, height: 70 }, { fontSize: 20, bold: true, color: C.navy2, alignment: "center" });
  }

  // 3. Separate the official rules from the team's engineering contribution.
  {
    const slide = base(deck, "Где наша разработка", "Правила заданы условием. Мы построили проверяемый цикл вокруг них", "3/6");
    text(slide, "Задано организаторами", { left: 64, top: 164, width: 500, height: 40 }, { fontSize: 23, bold: true, color: C.navy2 });
    const rules = [
      ["B", "размеры допустимы, K ≤ 0,8", C.green],
      ["C", "хотя бы один размер не проходит границу", C.amber],
      ["D", "размеры допустимы, K > 0,8", C.red],
    ];
    rules.forEach(([letter, rule, color], i) => {
      badge(slide, letter, { left: 64, top: 228 + i * 94, width: 58, height: 58 }, color);
      text(slide, rule, { left: 146, top: 225 + i * 94, width: 400, height: 64 }, { fontSize: 19, color: C.ink });
    });
    slide.shapes.add({ geometry: "rect", position: { left: 585, top: 164, width: 1, height: 388 }, fill: C.line, line: { style: "solid", fill: C.line, width: 0 } });
    text(slide, "Разработано командой", { left: 630, top: 164, width: 520, height: 40 }, { fontSize: 23, bold: true, color: C.navy2 });
    const contributions = [
      "Пять карт глубины, чтобы измерить товар со всех сторон",
      "Измерение размеров и формы при повороте товара",
      "Управление двумя заслонками по положению на ленте",
      "Успех только после датчика выхода; иначе безопасная остановка",
    ];
    contributions.forEach((value, i) => {
      badge(slide, String(i + 1), { left: 630, top: 224 + i * 82, width: 40, height: 40 }, C.blue);
      text(slide, value, { left: 692, top: 216 + i * 82, width: 470, height: 58 }, { fontSize: 18, bold: i === 3, color: i === 3 ? C.red : C.ink });
    });
    text(slide, "Во время сортировки правильный ответ заранее неизвестен.", { left: 64, top: 574, width: 1124, height: 36 }, { fontSize: 21, bold: true, color: C.blue, alignment: "center" });
  }

  // 4. Three independent proof layers.
  {
    const slide = base(deck, "Три независимые проверки", "Каждая проверка отвечает на свой вопрос", "4/6");
    const items = [
      ["1. Неизвестная геометрия", "artifacts/design-audit/04-supplied-box-route-b.png", "Браузер: размеры, форма, маршрут и объяснение"],
      ["2. Исполнение маршрута", "artifacts/design-audit/webots-final/d.png", "Webots: движение, заслонки и датчик выхода"],
      ["3. Отказ датчика", "artifacts/design-audit/webots-final/fault.png", "Нет подтверждения — цикл завершается с FAULT"],
    ];
    for (let i = 0; i < items.length; i += 1) {
      const [titleValue, file, label] = items[i];
      const left = 64 + i * 386;
      text(slide, titleValue, { left, top: 160, width: 354, height: 42 }, { fontSize: 21, bold: true, color: C.navy2 });
      await addImage(slide, file, { left, top: 217, width: 354, height: 270 }, titleValue);
      text(slide, label, { left, top: 505, width: 354, height: 68 }, { fontSize: 17, color: C.muted, alignment: "center" });
    }
  }

  // 5. The failure story in plain operator language.
  {
    const slide = base(deck, "Безопасное поведение", "Нет сигнала выхода — нет успешного цикла и нет следующего товара", "5/6");
    await addImage(slide, "artifacts/design-audit/webots-final/fault.png", { left: 64, top: 165, width: 555, height: 390 }, "Кадр Webots при отключённом датчике выхода");
    badge(slide, "ДАТЧИК ВЫХОДА ОТКЛЮЧЁН", { left: 86, top: 185, width: 230, height: 32 }, C.red);
    const steps = [
      ["1", "Товар продолжает движение", "Webots рассчитывает движение и положения заслонок"],
      ["2", "Подтверждения выхода нет", "маршрут не засчитывается как выполненный"],
      ["3", "Оператор видит FAULT", "следующий выпуск заблокирован до явного сброса"],
    ];
    steps.forEach(([n, h, d], i) => {
      badge(slide, n, { left: 660, top: 176 + i * 126, width: 42, height: 42 }, i === 2 ? C.red : C.blue);
      text(slide, h, { left: 724, top: 168 + i * 126, width: 438, height: 42 }, { fontSize: 21, bold: true, color: i === 2 ? C.red : C.ink });
      text(slide, d, { left: 724, top: 210 + i * 126, width: 438, height: 48 }, { fontSize: 17, color: C.muted });
    });
  }

  // 6. Honest readiness and the transition to the live demo.
  {
    const slide = base(deck, "Готовность", "Цифровой стенд уже проверяет логику. Оборудование потребует отдельной калибровки", "6/6");
    text(slide, "Уже готово и проверено", { left: 64, top: 164, width: 500, height: 40 }, { fontSize: 23, bold: true, color: C.navy2 });
    const ready = [
      "11 из 11 выданных STL совпали с независимой проверкой",
      "Маршруты B, C и D подтверждены датчиками выхода в Webots",
      "Отказ датчика переводит цикл в FAULT и блокирует выпуск",
      "0 небезопасных маршрутов в 10 564 численных циклах",
    ];
    ready.forEach((value, i) => {
      badge(slide, "✓", { left: 64, top: 224 + i * 72, width: 38, height: 38 }, C.green);
      text(slide, value, { left: 120, top: 216 + i * 72, width: 460, height: 54 }, { fontSize: 18, color: C.ink });
    });
    slide.shapes.add({ geometry: "rect", position: { left: 610, top: 164, width: 1, height: 356 }, fill: C.line, line: { style: "solid", fill: C.line, width: 0 } });
    text(slide, "Следующий шаг на оборудовании", { left: 650, top: 164, width: 500, height: 40 }, { fontSize: 23, bold: true, color: C.navy2 });
    const next = [
      "выбрать камеры, приводы и промышленный контроллер",
      "перенести калибровку виртуальных датчиков на реальный стенд",
      "проверить скорость и надёжность на физических товарах",
    ];
    next.forEach((value, i) => {
      badge(slide, String(i + 1), { left: 650, top: 224 + i * 88, width: 40, height: 40 }, C.blue);
      text(slide, value, { left: 712, top: 216 + i * 88, width: 444, height: 58 }, { fontSize: 18, color: C.ink });
    });
    box(slide, { left: 650, top: 490, width: 538, height: 86 }, C.navy2, C.navy2);
    text(slide, "Теперь проверим неизвестный STL в браузере", { left: 678, top: 507, width: 482, height: 52 }, { fontSize: 22, bold: true, color: C.white, alignment: "center" });
  }

  // 7. Appendix: exact rules for technical questions.
  {
    const slide = base(deck, "Резерв · точные правила", "Как вычисляются B, C и D", "резерв 1/3");
    const rules = [
      ["C", "Сначала габариты", "Каждый размер строго больше 10 мм; отсортированные размеры строго меньше 450 × 320 × 320 мм. Иначе C.", C.amber],
      ["D", "Затем форма", "При допустимых габаритах K = r / R. Если K > 0,8, маршрут D.", C.red],
      ["B", "Остальные допустимые", "При допустимых габаритах и K ≤ 0,8 товар идёт в B.", C.green],
    ];
    rules.forEach(([letter, h, d, color], i) => {
      const top = 170 + i * 137;
      badge(slide, letter, { left: 72, top, width: 62, height: 62 }, color);
      text(slide, h, { left: 164, top: top - 3, width: 340, height: 42 }, { fontSize: 22, bold: true });
      text(slide, d, { left: 520, top: top - 10, width: 640, height: 82 }, { fontSize: 18, color: C.muted });
    });
    text(slide, "Равенство строгой границе не проходит. Проверка C всегда выполняется первой.", { left: 64, top: 590, width: 1124, height: 34 }, { fontSize: 20, bold: true, color: C.blue, alignment: "center" });
  }

  // 8. Appendix: geometry detail.
  {
    const slide = base(deck, "Резерв · геометрия", "Как система получает размеры и коэффициент K", "резерв 2/3");
    await addImage(slide, "artifacts/postcal-final3-gpu-b/rangefinder-front.png", { left: 64, top: 164, width: 500, height: 392 }, "Карта глубины фронтального датчика Webots", "contain");
    badge(slide, "КАРТА ГЛУБИНЫ WEBOTS", { left: 84, top: 181, width: 196, height: 30 }, C.navy2);
    text(slide, "Пять датчиков смотрят на товар с разных сторон", { left: 610, top: 173, width: 560, height: 58 }, { fontSize: 23, bold: true });
    text(slide, "Система объединяет измерения и строит ориентированный габарит, устойчивый к повороту товара.", { left: 610, top: 245, width: 560, height: 82 }, { fontSize: 20, color: C.muted });
    text(slide, "Форма оценивается по нескольким поперечным сечениям: K = r вписанной / R описанной окружности.", { left: 610, top: 348, width: 560, height: 82 }, { fontSize: 20, color: C.muted });
    box(slide, { left: 610, top: 456, width: 578, height: 100 }, C.cyan, "#a9d8f7");
    text(slide, "11 из 11 выданных STL совпали с независимой проверкой, включая повёрнутые модели.", { left: 638, top: 470, width: 522, height: 72 }, { fontSize: 22, bold: true, color: C.navy2 });
  }

  // 9. Appendix: evidence scope and performance estimate.
  {
    const slide = base(deck, "Резерв · результаты", "Что означает каждое число", "резерв 3/3");
    metric(slide, "11 / 11", "выданных STL совпали с независимой геометрической проверкой", 72, 174, C.blue);
    metric(slide, "10 564", "численных маршрута в тесте надёжности", 364, 174, C.green);
    metric(slide, "0", "небезопасных маршрутов в этих 10 564 численных циклах", 656, 174, C.red);
    metric(slide, "5 143 / ч", "расчётная оценка дискретной модели; требуется стендовая проверка", 948, 174, C.amber);
    slide.shapes.add({ geometry: "rect", position: { left: 64, top: 369, width: 1124, height: 1 }, fill: C.line, line: { style: "solid", fill: C.line, width: 0 } });
    text(slide, "Физическая симуляция в Webots", { left: 64, top: 405, width: 500, height: 36 }, { fontSize: 21, bold: true, color: C.navy2 });
    text(slide, "Маршруты B, C, D и отказ датчика выхода.", { left: 64, top: 453, width: 500, height: 58 }, { fontSize: 19, color: C.muted });
    text(slide, "Численные модели", { left: 650, top: 405, width: 500, height: 36 }, { fontSize: 21, bold: true, color: C.navy2 });
    text(slide, "Точность геометрии, логика потока и расчётная производительность.", { left: 650, top: 453, width: 500, height: 58 }, { fontSize: 19, color: C.muted });
    text(slide, "Каждый прогон связан с журналом, seed и SHA-256.", { left: 64, top: 558, width: 1124, height: 34 }, { fontSize: 20, bold: true, color: C.blue, alignment: "center" });
  }

  for (const [index, slide] of deck.slides.items.entries()) {
    const stem = `slide-${String(index + 1).padStart(2, "0")}`;
    await writeBlob(path.join(renders, `${stem}.png`), await deck.export({ slide, format: "png", scale: 1 }));
    const layout = await slide.export({ format: "layout" });
    await fs.writeFile(path.join(renders, `${stem}.layout.json`), await layout.text());
  }
  await writeBlob(path.join(renders, "deck-montage.webp"), await deck.export({ format: "webp", montage: true, scale: 1 }));
  const pptx = await PresentationFile.exportPptx(deck);
  await pptx.save(path.join(output, "presentation.pptx"));
}

await main();
