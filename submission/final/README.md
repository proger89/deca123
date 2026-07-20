# SafeSort: комплект для жюри

Комплект собирается из одного проверенного tagged commit. Большие файлы — основное видео, тяжёлые модели/CAD и бинарные артефакты — размещаются в выданном облачном хранилище; код, конфигурация, небольшие документы и инструкции остаются в GitHub.

## Запустить интерактивное демо

Docker — основной способ запуска. На Windows дважды нажмите `start-demo.cmd` в корне репозитория или выполните:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-demo.ps1
```

Контейнер собирается, проходит healthcheck, после чего автоматически открывается `http://127.0.0.1:4173/`. NVIDIA определяется внутри Docker автоматически; при её отсутствии используется CPU. Явный выбор: `-GpuMode Gpu` или `-GpuMode Cpu`. Для CI или сервера используйте `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-demo.ps1 -NoBrowser`. Физический прогон: `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-webots.ps1 -GpuMode Auto`. Остановка: `docker compose down`.

Зоны означают: **B** — допустимые габариты и `K ≤ 0,8`; **C** — не прошёл хотя бы один габарит; **D** — габариты допустимы и `K > 0,8`. Само правило дано организаторами. Отличие SafeSort — независимое пятиракурсное измерение неизвестного товара, устойчивый геометрический расчёт, физическое исполнение на виртуальном конвейере, безопасная реакция на отказ и подтверждение фактического выхода.

## Порядок просмотра

1. `presentation.pdf` — краткая логика решения.
2. `demonstration.mp4` — неизвестный STL и виртуальный конвейер; B/C/D, выход и отказ называются Webots physical только при наличии финальных post-calibration traces.
3. `report.pdf` — первичные метрики, типы доказательств и provenance.
4. `web/index.html` — локальный браузерный демонстратор STL.
5. `defense-script.md` и `recovery-script.md` — основной и резервный сценарии защиты.

## Важное различие

Webots physical smoke доказывает движение и подтверждение выхода в виртуальном мире. Numerical physics-proxy проверяет формулу возврата заслонки. Discrete-event hour-flow проверяет очередь и дедлайны. Synthetic geometry harness проверяет алгоритм на модельных точках. Браузерный клиент объясняет загруженный STL. Эти результаты не объединяются в одно «число физических прогонов».

## Проверка перед передачей

```powershell
python run_scenario.py release check --repeat 3 --clean-clone
python run_scenario.py quality --checks all
python tools/check_submission.py --bundle submission/final
git ls-remote origin refs/tags/v1.0.0-submission
```

Комплект нельзя называть отправленным, пока авторизованный участник не загрузил ссылки в портал и не сохранил подтверждение. `portal-description.txt` использует стабильные URL будущих assets релиза `v1.0.0-submission`; до публикации assets эти URL являются целевыми, а не подтверждённо доступными ссылками.

## Документы проекта

- `../../README.md` — quick start и полный индекс критериев;
- `../../docs/architecture.md` — разделение runtime/evaluator;
- `../../docs/calculations.md` — правила и расчёты;
- `../../docs/fmea.md` — отказы и безопасные реакции;
- `../../docs/simulation.md` — границы Webots, proxy и браузера;
- `../../docs/reproducibility.md` — чистый запуск и integrity;
- `../../docs/adr-001-geometry-first.md` — выбор geometry-first.
