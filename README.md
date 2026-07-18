# Ozon Geometry-First SafeSort Cell

Расчётно-верифицируемая цифровая модель сортировочной ячейки для задачи 3 RoboZone/Ozon.

Система измеряет неизвестные товары только виртуальными датчиками, применяет официальные правила B/C/D, управляет сортировщиком и подтверждает физический выход в Webots. Имя файла, имя объекта сцены и эталонный класс недоступны исполняющему алгоритму.

## Проверенный физический smoke-сценарий

Для запуска нужен только Docker Desktop; локальная установка Webots и GPU не требуются:

```powershell
python run_scenario.py run --scenario scenarios/smoke/unknown_stl_b.yaml --seed 42 --output artifacts/phase-4
python run_scenario.py replay --bundle artifacts/phase-4 --repeat 2
python run_scenario.py verify --bundle artifacts/phase-4
```

Первый запуск автоматически собирает закреплённый Docker-образ, запускает Webots на CPU с отключённой сетью и выполняет два прогона: штатный и контрольный с отключённым подтверждением выхода. В `artifacts/phase-4` создаются журнал датчиков и приводов, проверка сцены, хэши, результат независимого оценщика, SVG-схема и MP4-трасса.

## Bootstrap smoke

```powershell
python run_scenario.py quality --checks bootstrap
```

Контейнерная проверка:

```powershell
python run_scenario.py image build --tag deca123-sim:dev
python run_scenario.py doctor --require-container
```

Код находится в `src/safesort/`, Webots-сцены — в `webots/`, сценарии — в `scenarios/`, критерии — в `criteria/`. Локальные материалы организатора в `materials/` не публикуются без лицензии.

Полный проверяемый контракт находится в `criteria/ACCEPTANCE_MATRIX.md`. Текущая подтверждённая вертикаль: неизвестный STL → RangeFinder → геометрические измерения → решение B → физическая заслонка → датчик выхода → `SUCCESS`; отсутствие подтверждения даёт `FAULT` и ненулевой код.
