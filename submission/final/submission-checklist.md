# Чек-лист финальной сдачи SafeSort

Внутренний дедлайн комплекта: **02.08.2026 18:00 МСК**. Официальный дедлайн: **02.08.2026 23:59 МСК**. Факт загрузки отмечает только авторизованный участник после реального подтверждения портала.

## 1. Зафиксировать релиз

- [ ] Рабочее дерево чистое; functional freeze соблюдён.
- [ ] `python run_scenario.py release check --repeat 3 --clean-clone` завершился кодом 0 три раза.
- [ ] `python run_scenario.py quality --checks all` завершился кодом 0.
- [ ] Secret/dependency/licence/privacy/network audit: 0 unresolved high.
- [ ] В manifest записаны `dirty=false`, commit, base/custom image digest, seed, tool/config/calibration hashes.
- [ ] `v1.0.0-submission` создан на проверенном commit, а `git ls-remote origin refs/tags/v1.0.0-submission` возвращает тот же объект.
- [ ] Один и тот же tag указан в README, report, presentation, video и release notes.

## 2. Проверить честность доказательств

- [ ] Webots physical smoke отделён от numerical proxy/discrete-event/synthetic/browser UX.
- [ ] В physical bundle записан актуальный hash калибровки; все более старые трассы исключены из отчёта и видео.
- [ ] `EvaluatorSupervisor` только наблюдает: в нём нет вызовов, меняющих translation/rotation/physics товара.
- [ ] Нет фразы «10 564 физических маршрута»: это пятиракурсный sensor model + continuous-time conveyor proxy.
- [ ] Реальные выданные STL имеют отдельные Chrome/Webots item traces; proxy-набор не назван фактическими STL.
- [ ] B/C/D в видео имеют requested route и matching exit; если кадр только logic/proxy, это видно в подписи.
- [ ] Missing-exit canary движет товар тем же физическим путём, но завершает прогон `FAULT`/ненулевым кодом без `SUCCESS`.
- [ ] Power-loss trace подписан `Webots fault` только при наличии реального Webots angle/torque/exit trace.
- [ ] Профиль 5143/ч подписан analytical/discrete-event, не «часовой Webots run».
- [ ] 7200/ч остаётся `UNSUPPORTED`.
- [ ] У каждой числовой метрики есть evidence type, scenario ID, seed, первичный файл и SHA-256.
- [ ] Abstain включён в официальный знаменатель и не называется успешной сортировкой.

## 3. GitHub-репозиторий команды

Загрузить небольшие и текстовые материалы:

- [ ] исходный код `src/`, Webots controllers/world/protos, `web/`;
- [ ] `README.md` с quick start и индексом всех 38 acceptance IDs;
- [ ] `pyproject.toml`, `uv.lock`, Dockerfile, toolchain/config/calibration;
- [ ] сценарии, тесты, schemas, criteria contract;
- [ ] architecture, calculations, FMEA, simulation, reproducibility, ADR, clarifications;
- [ ] инструкции сдачи и release notes;
- [ ] LICENSE, SBOM/licence report и sanitized privacy audit;
- [ ] ни одного raw Telegram export, PDF/CAD/STL без разрешения на публикацию;
- [ ] репозиторий доступен гостю без логина, если правила требуют публичный доступ.

## 4. Облачное хранилище организатора

Загрузить крупные файлы:

- [ ] основную видеодемонстрацию без ограничения времени;
- [ ] проверенную резервную запись защиты/demo;
- [ ] большие модели и наборы;
- [ ] STEP/STL/CAD, если организатор разрешает/требует их размещение;
- [ ] крупные файлы симуляции и бинарные release assets;
- [ ] папка/ссылки имеют гостевой доступ на просмотр и загрузку;
- [ ] ссылки не требуют аккаунта команды и не истекают до завершения оценки.

## 5. Судейский bundle

- [ ] В `submission/final` присутствуют README, portal text, presentation PDF, demonstration MP4, report PDF, scripts, web copy и checksums.
- [ ] `python tools/check_submission.py --bundle submission/final` завершился кодом 0.
- [ ] Все строки `checksums.sha256` проверены из чистой копии.
- [ ] Tamper canary обнаруживает изменённый файл.
- [ ] PDF открываются, MP4 воспроизводится offline, web открывается локально.
- [ ] Никаких абсолютных путей, временных ссылок, debug output или устаревших агрегатов.

## 6. Демо и защита

- [ ] Основная репетиция длится 6:00–6:30; записаны дата, commit и фактический таймер.
- [ ] В первые 60 секунд понятно, что решается и почему demo имеет два уровня.
- [ ] Виртуальный конвейер Webots — центральная сцена, не второстепенный скриншот.
- [ ] Browser flow: supplied STL, renamed unseen, boundary, invalid, retry.
- [ ] Chrome console/network clean; focus/labels/contrast/keyboard проверены.
- [ ] Backup video rehearsal переключается ≤20 с.
- [ ] Полный recovery rehearsal проходит offline.
- [ ] На сцене открыты все локальные файлы; уведомления отключены.

## 7. Описание на платформе

- [ ] `portal-description.txt` не длиннее 1500 символов.
- [ ] Release-target ссылка на `demonstration.mp4` открывается без авторизации после публикации asset.
- [ ] Release-target ссылка на `presentation.pdf` открывается без авторизации после публикации asset.
- [ ] При добавлении web/repository links они открываются в гостевом окне.
- [ ] Текст не обещает реальное оборудование, непроверенный throughput или публичный upload.
- [ ] После публикации release assets обе ссылки проверены в гостевом окне, затем bundle/checksums пересобраны и проверены заново.

## 8. Организаторский репозиторий

Целевой репозиторий организатора: `https://github.com/hackathonsrus/ozone-tech_naraka_top_30.git`.

- [ ] До выдачи доступа продолжаем работать в `https://github.com/proger89/deca123` без изменения origin.
- [ ] После выдачи доступа зеркало создаётся из точного `v1.0.0-submission`, без новых функциональных правок.
- [ ] Сравнены commit/tree hash исходного релиза и зеркала.
- [ ] Инструкции запуска и release assets доступны из зеркала.
- [ ] Результат mirror verification сохранён в handoff.

## 9. Финальная отправка авторизованным участником

- [ ] В поле «Решение» вставлен финальный текст с реальными ссылками.
- [ ] Нажата кнопка отправки решения.
- [ ] Сохранены время МСК, скриншот/ID подтверждения и точный portal text.
- [ ] Подтверждение добавлено в handoff без персональных данных/секретов.

Если последние четыре пункта не подтверждены фактически, статус остаётся «пакет готов к загрузке», а не «решение отправлено».
