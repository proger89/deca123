# Воспроизводимость и целостность доказательств

## Авторитетная среда

- Python 3.12.10;
- Webots R2025a;
- CPU-only baseline, `OMP_NUM_THREADS=1`;
- зависимости закреплены в `uv.lock` с хэшами;
- базовый образ Webots закреплён digest в `Dockerfile`;
- runtime-контейнер запускается с `--network none`;
- GPU, Docker Compose и локальная установка Webots не требуются.

Исторический manifest фазы 14 записал base digest `sha256:f0023e30...f099` и custom image digest `sha256:3cb06e90...f4de2`. Финальным считается только digest, заново записанный из чистого tagged commit в `submission/final`, а не значение, переписанное в документацию.

## Быстрый путь жюри

```powershell
git clone https://github.com/proger89/deca123.git
cd deca123
python run_scenario.py suite --profile release --repeat 3 --record-video --output artifacts/release
```

Первое скачивание образа исключается из холодного времени и указывается отдельно. В manifest фазы 14 были измерены 65 с cold start и 19 с smoke, но эти числа не переносятся в финальный отчёт без нового чистого замера.

## Полный финальный gate

```powershell
python run_scenario.py release check --repeat 3 --clean-clone
python run_scenario.py quality --checks all
python tools/check_submission.py --bundle submission/final
git ls-remote origin refs/tags/v1.0.0-submission
```

Релиз зелёный только при четырёх кодах 0. Локальный успешный unit-тест не заменяет clean-clone, а наличие тега не заменяет проверку bundle.

## Что фиксирует каждый run

- commit SHA и dirty flag;
- base/custom image digests;
- версии Python/Webots и режим CPU;
- seed, basic timestep и float tolerance;
- хэши архитектуры, калибровки, uncertainty bands, сценариев и toolchain;
- исходный event-log и его SHA-256;
- отдельные semantic hashes повторов;
- перечень файлов и `checksums.sha256`;
- `network=none` и тип доказательства каждого семейства метрик.

В phase-15 tagged release `dirty` обязан быть `false`. Если manifest показывает `true`, это development evidence и он не может считаться финальным bundle.

## Семантический хэш

Семантический хэш строится из нормализованных решений/метрик с сортированными ключами и объявленной float tolerance. Он игнорирует несущественные различия времени файлов, но должен меняться при изменении решения, маршрута, статуса, порядка или метрики.

Три одинаковых хэша фазы 14 доказывают детерминизм одной замороженной сводки. Они не доказывают, что все ранние reliability-числа независимо пересчитаны. Для этого clean-clone должен запустить настоящие генераторы и сохранить их первичные логи.

## Защита от ручной правки

`checksums.sha256` покрывает все файлы bundle, кроме самого списка. Команда:

```powershell
python run_scenario.py verify --bundle artifacts/phase-14 --tamper-canary
```

временно изменяет `report.html`, обязана обнаружить несоответствие и восстановить исходный файл. Публикация запрещена при missing file, checksum failure или расхождении source-event hash между CSV/HTML/PDF/KPI.

## Воспроизведение отдельных доказательств

| Цель | Команда | Тип доказательства |
|---|---|---|
| Кандидат на Webots full-cycle smoke | `python run_scenario.py run --scenario scenarios/smoke/unknown_stl_b.yaml --seed 42 --output artifacts/smoke` | считается physical proof только с актуальным calibration hash и совпавшим exit |
| Проверка smoke | `python run_scenario.py verify --bundle artifacts/smoke` | trace/schema/exit; код 0 не заменяет аудит датчиков и отсутствия physics mutation |
| Синхронизация пяти видов | `python run_scenario.py suite --profile sensing --seed 501 --output artifacts/sensing` | sensing harness + smoke regression |
| Геометрия | `python run_scenario.py suite --profile geometry --seed 601 --output artifacts/geometry` | synthetic geometry harness |
| Неопределённость | `python run_scenario.py suite --profile uncertainty --seed 701 --output artifacts/uncertainty` | numerical harness |
| Заслонки | `python run_scenario.py suite --profile gates --seed 901 --output artifacts/gates` | unit/physics-proxy + smoke regression |
| Reliability | `python run_scenario.py suite --profile reliability-release --output artifacts/reliability` | numerical route harness |
| Throughput | `python run_scenario.py suite --profile hour-flow --seed 1201 --output artifacts/hour-flow` | discrete-event + analytical |
| Ablations | `python run_scenario.py suite --profile ablations --output artifacts/ablations` | paired numerical harness |

## Независимость runtime и evaluator

```powershell
python run_scenario.py architecture verify
python tools/leak_test.py --with-canary
```

Первая команда проверяет реальные импорты/API/устройства. Вторая добавляет запрещённую ссылку и должна завершиться ненулевым кодом именно для canary. Остановка evaluator на одинаковом sensor replay должна сохранить runtime semantic hash.

## Сырые материалы и приватность

`materials/` исключён из Git. PDF, Telegram export, STL и STEP не имеют явной лицензии на публичное распространение. В репозитории остаются только SHA-256 и очищенное резюме официальных разъяснений. Это одновременно защищает приватность и позволяет сверить происхождение локального набора.

## Правило публикации результата

Число попадает в README, презентацию или портал только если можно ответить на четыре вопроса:

1. Какой это тип доказательства: Webots physical smoke, numerical proxy, discrete-event, synthetic geometry или browser UX?
2. Какая команда и seed его создали?
3. Где первичный файл и его checksum?
4. Прошёл ли тот же tagged commit чистый final gate?

Если хотя бы одного ответа нет, формулировка остаётся ограничением или планом проверки, а не результатом.

Для Webots действует дополнительное правило: артефакты, созданные до последнего изменения ориентации/калибровки RangeFinder или контроллеров движения, автоматически становятся историческими. Они не возвращаются в релиз только потому, что старый `evaluator-result.json` содержит `SUCCESS`; нужны новый calibration hash, read-only evaluator, непрерывная sensor-to-exit трасса и отдельный missing-exit прогон с ненулевым кодом.
