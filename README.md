# startups-bizwiki

Репозиторий проекта по созданию структурированной бизнес-вики (карточек компаний) на основе ежемесячных тредов Hacker News «Ask HN: Who is hiring?».

## Состояние веток

- В ветке по умолчанию `main` на данный момент находятся только файл лицензии `LICENSE` и заглушка `README.md`.
- Основная рабочая версия проекта (документация, 30 карточек компаний, CSV-выгрузки и Python-инструменты) размещена в неслитой ветке `claude/startup-wiki-hacker-news-qa7p7s`.

## Структура проекта (ветка `claude/startup-wiki-hacker-news-qa7p7s`)

- `README.md` — исходное описание проекта (3 097 байт).
- `wiki/README.md` — индекс карточек (версия 0.2 от 10.11.2026), YAML-схема карточки и 8 принципов ведения базы.
- `wiki/companies/` — 30 Markdown-карточек компаний (12 карточек первой волны и 18 карточек второй волны): `antithesis.md`, `chainsecurity.md`, `curai-health.md`, `exponent.md`, `iceye.md`, `juro.md`, `livekit.md`, `lumen-labs.md`, `mastra.md`, `nirvana-robotics.md`, `odette-technologies.md`, `opsfleet.md`, `oscilar.md`, `paradromics.md`, `piramidal.md`, `posthog.md`, `prior-labs.md`, `proxima-fusion.md`, `radar-labs.md`, `reducto.md`, `serpapi.md`, `sortrace.md`, `special.md`, `sumble.md`, `sunsave.md`, `telli.md`, `thankly.md`, `threatmark.md`, `victoriametrics.md`, `zed-industries.md`.
- `docs/` — методические и проектные документы: `analiz-idei.md`, `plan.md`, `paralleli.md`, `tochnost-priznakov.md`, `proverka-kartochek.md`.
- `data/` — табличные выгрузки `hn-hiring-2026-10.csv` и `hn-hiring-2026-11.csv` (содержат только производные атрибуты, без текстов комментариев и контактов).
- `tools/` — скрипты экспорта, оценки и проверки:
  - `hn_hiring_export.py` (v2) и `hn_hiring_export_v1.py`;
  - `eval/` (`manifest.json`, `gold.json`, `score.py`);
  - `verify/` (`hn_item_text.py`, `html2txt.py`, `quote_check.py`).

## Стек и команды запуска

Для работы скриптов экспорта в ветке `claude/startup-wiki-hacker-news-qa7p7s` требуется Python 3.9+ и доступ к API Hacker News (`hacker-news.firebaseio.com`).

Пример запуска экспортера из документации ветки:

```bash
python3 tools/hn_hiring_export.py --story 50338728 --out data/hn-hiring-2026-11.csv --prev data/hn-hiring-2026-10.csv
```

## Ветки репозитория

- `main` — защищённая ветка по умолчанию (содержит `LICENSE` и исходную заглушку `README.md`).
- `claude/startup-wiki-hacker-news-qa7p7s` — ветка без открытого Pull Request; содержит `wiki/companies/` (30 карточек), `docs/`, `data/`, `tools/` и расширенный `README.md`.

## Лицензия

В корне репозитория размещён файл `LICENSE` — **GNU Affero General Public License v3 (AGPL-3.0)**. Согласно `README.md` в ветке `claude/startup-wiki-hacker-news-qa7p7s`, лицензия AGPL-3.0 относится к коду, а вопросы лицензирования текстов карточек и данных рассмотрены отдельно в `docs/analiz-idei.md` (раздел 9).
