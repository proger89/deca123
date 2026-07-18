# Ozon Geometry-First SafeSort Cell

Расчётно-верифицируемая цифровая модель сортировочной ячейки для задачи 3 RoboZone/Ozon.

Текущий этап — детерминированный greenfield-baseline. Система будет измерять неизвестные товары только виртуальными датчиками, применять официальные правила B/C/D и подтверждать физический выход в Webots.

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

Полный acceptance/evidence contract создаётся фазой 2. До неё README не заявляет неподтверждённые метрики.

