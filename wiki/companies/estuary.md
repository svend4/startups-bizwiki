---
id: estuary
name: Estuary
website: https://estuary.dev/
sector: ["данные: CDC-репликация и потоковая передача (по сайту и посту)", "ИИ-интеграция данных (по сайту)"]
organization_type: "коммерческая компания с платными тарифами (по сайту); венчурное финансирование заявлено (со слов компании)"
founded: "2019 (по сайту, страница About: «2019 Estuary is founded»; со слов компании, реестр не проверен)"
headquarters: "не указано (по сайту: офисы в Нью-Йорке и Колумбусе, Огайо, и удалённая работа)"
technologies: ["Rust", "Go", "Python", "SQL", "TypeScript", "gRPC", "Raft", "Gazette"]
open_source:
  license: не указано
  repository: https://github.com/estuary/flow/
hiring:
  - thread: "Ask HN: Who is hiring? (November 2026)"
    hn_item_id: 50356058
    roles: ["Head of Engineering", "Senior Systems Engineer (Control & Data Plane)", "Product Manager", "Head of Product Marketing", "Solutions Engineer", "Customer Success Manager", "Senior Compliance Engineer"]
    location: "US-Based / Remote"
    employment: "Full-time"
    salary_in_post: "не указано"
sources:
  - {url: "https://estuary.dev/", kind: "сайт компании", accessed: "2026-11-22"}
  - {url: "https://estuary.dev/about", kind: "сайт компании (о компании, открытые позиции)", accessed: "2026-11-22"}
  - {url: "https://estuary.dev/pricing", kind: "сайт компании (тарифы)", accessed: "2026-11-22"}
  - {url: "https://estuary.dev/terms", kind: "сайт компании (условия использования)", accessed: "2026-11-22"}
  - {url: "https://news.ycombinator.com/item?id=50356058", kind: "пост компании на HN", accessed: "2026-11-22"}
verification: сайт + пост
unverified_claims: ["субсекундная CDC-репликация и потоки терабайтного масштаба (в посте и на странице About в вакансии Head of Engineering; отзыв Together AI на главной без замеров)"]
last_verified: "2026-11-22"
---

# Estuary

> **Почему в выборке:** сфера данных (перенос и потоковая обработка данных).

**Estuary** — платформа переноса данных в реальном времени.

## Кто они

Юрлицо по условиям сайта — Estuary Technologies, Inc. По сайту, компания основана в 2019 году. На странице About: CEO и соучредитель Dave Yaffe, CTO и соучредитель Johnny Graettinger. Офисы — в Нью-Йорке и Колумбусе (Огайо); штаб-квартира на сайте не названа. По странице About, в 2025 году компания привлекла серию A на $17 млн под руководством M13 (со слов компании, независимо не проверено). В посте на HN компания называет себя «VC-backed, post–Series A» стартапом.

## Чем занимаются

По сайту, платформа объединяет захват изменений из баз (log-based CDC), пакетные загрузки из SaaS и файлов и потоковую доставку. Данные хранятся в бакете клиента. Python для трансформаций доступен только в Enterprise, и только в private- и BYOC-развёртываниях. На странице тарифов: бесплатно до 10 ГБ и 2 коннектора; тариф Cloud — $0.50 за ГБ и $100 в месяц за коннектор ($50 после шестого). На сайте указаны и «150+», и «200+» коннекторов.

По главной странице, у клиентов, перешедших с тарифа за строки (row-based), расходы на 40–60% ниже; на странице тарифов сказано, что клиенты обычно экономят 40–60%. На главной также указан рейтинг 4.8 из 5 на G2. Это данные самой компании.

На главной в блоке Compliance заявлены SOC 2 Type II, HIPAA, HITECH, GDPR и CCPA; отчёты не проверены. По странице тарифов отчёт SOC 2 на тарифе Cloud выдаётся по запросу и включён только в Enterprise, а HIPAA BAA доступен только в Enterprise (private и BYOC). В вакансии Security Compliance Manager на странице About GDPR и PCI DSS названы растущим направлением («a growing focus»).

## Технологии и открытый код

Rust — основной язык роли Senior Systems Engineer в посте. Go, Python, SQL, TypeScript, gRPC и Raft упомянуты на сайте. «Gazette» — собственный фреймворк потоковой передачи, создан в 2014 году (About). В посте компания называет себя «open-source, developer-first»; на странице About упомянуты open-source коннекторы. Ссылка «GitHub» на сайте ведёт на github.com/estuary/flow/; лицензия не указана.

## Кого ищут

В посте семь ролей: Head of Engineering, Senior Systems Engineer (Control & Data Plane), Product Manager, Head of Product Marketing, Solutions Engineer, Customer Success Manager и Senior Compliance Engineer. Формат: US-Based / Remote, полная занятость.

На странице About 11 открытых позиций. Пять ролей совпадают с постом по названию. Solutions Engineer на сайте указан для Великобритании и Ирландии, а по описанию роль из поста ближе к Sales Engineer (Нью-Йорк или удалённо в США). Customer Success Manager на сайте нет. Senior Compliance Engineer, возможно, соответствует Security Compliance Manager (не подтверждено).

## Что заявлено, но не проверено

- Субсекундная CDC-репликация и потоки терабайтного масштаба (в посте; на странице About в вакансии Head of Engineering; отзыв Together AI на главной без замеров). Замеров в источниках нет.

## Пробелы

Юрлицо, год основания и инвесторы подтверждены только сайтом (в 2021 году FirstMark вложил $7 млн): реестра в источниках нет. На странице About есть блок «In the media» со ссылками на SiliconANGLE (о раунде $17 млн под руководством M13), DBTA и PR Newswire; сами статьи не читались, их независимость не проверена. Штаб-квартира на сайте не названа. Суммы зарплат не указаны ни в посте, ни на сайте. Численность сотрудников не указана. Вакансии перечислены на About; отдельной страницы карьеры нет. Условия использования датированы 20.01.2022.

## Источники

1. https://estuary.dev/ — сайт компании.
2. https://estuary.dev/about — о компании и вакансии.
3. https://estuary.dev/pricing — тарифы.
4. https://estuary.dev/terms — условия использования.
5. https://news.ycombinator.com/item?id=50356058 — пост компании на HN (в нём указан estuary.dev).

Проверено 22.11.2026.
