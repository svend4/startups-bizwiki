#!/usr/bin/env python3
"""База карточек вики: проверка шапок, выгрузка CSV и JSON, поиск по полям.

Команды:
  validate  проверить шапки, обязательные разделы и отсутствие контактов
  export    записать data/wiki-companies.csv и .json (только если проверка без ошибок)
  search    вывести id карточек, которые подходят под все заданные условия
  check     сверить запросы из tools/eval/base_queries.json с ручным поиском

Нужны Python 3.9+ и PyYAML (pip install pyyaml). Карточки скрипт не меняет.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CARDS_DIR = ROOT / "wiki" / "companies"
DATA_DIR = ROOT / "data"
EVAL_DIR = ROOT / "tools" / "eval"

REQUIRED_FIELDS = [
    "id", "name", "website", "sector", "organization_type", "founded",
    "headquarters", "technologies", "open_source", "hiring", "sources",
    "verification", "unverified_claims", "last_verified",
]
OPTIONAL_FIELDS = ["founders", "managing_directors", "registration"]
HIRING_FIELDS = ["thread", "hn_item_id", "roles", "location", "employment", "salary_in_post"]
SOURCE_FIELDS = ["url", "kind", "accessed"]
VERIFICATION_VALUES = [
    "сайт",
    "сайт + пост",
    "сайт + пост + доска вакансий (Greenhouse)",
    "частично",
]
REQUIRED_HEADINGS = ["Кто они", "Кого ищут", "Пробелы", "Источники"]
CLAIMS_HEADING = "Что заявлено, но не проверено"
NOT_STATED = "не указано"
WORK_FORMATS = ["удалённо", "гибрид", "офис"]
# Слова ищутся с начала слова: иначе «очно» попадает в «Восточном».
WORK_FORMAT_RULES = {
    "удалённо": re.compile(r"\bудал|\bremote", re.IGNORECASE),
    "гибрид": re.compile(r"\bгибрид|\bhybrid", re.IGNORECASE),
    "офис": re.compile(r"\bonsite|\bочно\b|\bофис", re.IGNORECASE),
}
STALE_DAYS = 90

ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
URL_RE = re.compile(r"^https?://[^\s/]+\.[^\s]+$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?<![\w/])\+\d{1,3}[\s\-()]*\d[\d\s\-()]{6,}\d")
CARD_RE = re.compile(r"^---\n(.*?)\n---\n(.*)\Z", re.S)
HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.M)
TITLE_RE = re.compile(r"^#\s+\S", re.M)

CSV_FIELDS = [
    "id", "name", "website", "sector", "organization_type", "founded", "headquarters",
    "technologies", "open_source_license", "open_source_repository", "hiring_posts",
    "hiring_post_ids", "hiring_roles", "hiring_locations", "hiring_employment",
    "salary_in_post", "work_format", "verification", "unverified_claims", "last_verified",
    "card",
]


def norm(text) -> str:
    """Сравнение без учёта регистра и с «е» вместо «ё»."""
    return str(text).casefold().replace("ё", "е")


def as_date(value):
    """Дата из шапки. YAML может разобрать дату сам, поэтому принимаем и строку, и дату."""
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str) and DATE_RE.match(value):
        try:
            return dt.date.fromisoformat(value)
        except ValueError:
            return None
    return None


def parse_day(text: str) -> dt.date:
    try:
        return dt.date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"нужна дата YYYY-MM-DD, получено {text!r}")


def read_card(path: Path):
    """Вернуть (шапка, тело). При сбое — ValueError с понятным текстом."""
    text = path.read_text(encoding="utf-8")
    match = CARD_RE.match(text)
    if not match:
        raise ValueError("нет шапки между строками ---")
    try:
        front = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        raise ValueError(f"шапка не разбирается как YAML: {exc}") from None
    if not isinstance(front, dict):
        raise ValueError("шапка должна быть набором полей «ключ: значение»")
    return front, match.group(2)


def work_formats(hiring) -> list:
    """Формат работы из текста вакансий (location и employment). Это производное поле."""
    found = set()
    for post in hiring:
        text = f"{post.get('location', '')} {post.get('employment', '')}"
        for label, rule in WORK_FORMAT_RULES.items():
            if rule.search(text):
                found.add(label)
    ordered = [label for label in WORK_FORMATS if label in found]
    return ordered or [NOT_STATED]


def check_card(path: Path, today: dt.date):
    """Вернуть (ошибки, предупреждения) для одной карточки."""
    errors, warnings = [], []
    try:
        fm, body = read_card(path)
    except (OSError, ValueError) as exc:
        return [str(exc)], []

    for field in REQUIRED_FIELDS:
        if field not in fm:
            errors.append(f"нет поля «{field}»")
    extra = sorted(set(fm) - set(REQUIRED_FIELDS) - set(OPTIONAL_FIELDS))
    if extra:
        warnings.append("поля вне схемы: " + ", ".join(extra))

    if "id" in fm:
        cid = fm["id"]
        if not isinstance(cid, str) or not ID_RE.match(cid):
            errors.append(f"«id» {cid!r}: нужны латинские буквы, цифры и дефисы")
        elif cid != path.stem:
            errors.append(f"«id» {cid!r} не совпадает с именем файла «{path.stem}»")

    for field in ("name", "organization_type", "founded", "headquarters"):
        if field in fm and not (isinstance(fm[field], str) and fm[field].strip()):
            errors.append(f"«{field}»: нужна непустая строка")
    if "website" in fm and not (isinstance(fm["website"], str) and URL_RE.match(fm["website"])):
        errors.append(f"«website»: не похоже на адрес сайта: {fm['website']!r}")
    for field in ("sector", "technologies", "sources", "hiring", "unverified_claims"):
        if field in fm and not isinstance(fm[field], list):
            errors.append(f"«{field}»: нужен список")
    if isinstance(fm.get("sector"), list) and not fm["sector"]:
        errors.append("«sector»: список пуст")

    if "open_source" in fm:
        oss = fm["open_source"]
        if not isinstance(oss, dict) or set(oss) != {"license", "repository"}:
            errors.append("«open_source»: нужен словарь с полями license и repository")

    if "verification" in fm and fm["verification"] not in VERIFICATION_VALUES:
        errors.append(f"«verification»: {fm['verification']!r} не входит в допустимые значения")

    if "last_verified" in fm:
        checked = as_date(fm["last_verified"])
        if checked is None:
            errors.append(f"«last_verified»: нужна дата YYYY-MM-DD, получено {fm['last_verified']!r}")
        elif (today - checked).days > STALE_DAYS:
            warnings.append(f"«last_verified» {checked}: старше {STALE_DAYS} дней, нужна повторная проверка")

    source_urls = []
    sources = fm.get("sources") if isinstance(fm.get("sources"), list) else []
    for i, src in enumerate(sources, 1):
        if not isinstance(src, dict) or any(key not in src for key in SOURCE_FIELDS):
            errors.append(f"sources[{i}]: нужны поля url, kind, accessed")
            continue
        source_urls.append(str(src["url"]))
        if not URL_RE.match(str(src["url"])):
            errors.append(f"sources[{i}]: адрес не похож на ссылку: {src['url']!r}")
        if as_date(src["accessed"]) is None:
            errors.append(f"sources[{i}]: «accessed» должна быть датой YYYY-MM-DD")

    hiring = fm.get("hiring") if isinstance(fm.get("hiring"), list) else []
    for i, post in enumerate(hiring, 1):
        if not isinstance(post, dict):
            errors.append(f"hiring[{i}]: нужен словарь полей")
            continue
        missing = [key for key in HIRING_FIELDS if key not in post]
        if missing:
            errors.append(f"hiring[{i}]: нет полей {', '.join(missing)}")
        if "hn_item_id" in post:
            post_id = post["hn_item_id"]
            if not isinstance(post_id, int) or isinstance(post_id, bool):
                errors.append(f"hiring[{i}]: «hn_item_id» должен быть числом")
            elif not any(f"item?id={post_id}" in url for url in source_urls):
                errors.append(f"hiring[{i}]: в sources нет ссылки на пост item?id={post_id}")
        if "roles" in post and (not isinstance(post["roles"], list) or not post["roles"]):
            errors.append(f"hiring[{i}]: «roles» должен быть непустым списком")

    headings = HEADING_RE.findall(body)
    if not TITLE_RE.search(body):
        errors.append("в теле нет заголовка первого уровня")
    for title in REQUIRED_HEADINGS:
        if title not in headings:
            errors.append(f"в теле нет раздела «## {title}»")
    if fm.get("unverified_claims") and CLAIMS_HEADING not in headings:
        errors.append(f"есть непроверенные заявления, но нет раздела «## {CLAIMS_HEADING}»")

    text = yaml.safe_dump(fm, allow_unicode=True) + body
    if EMAIL_RE.search(text):
        errors.append("похоже на e-mail-адрес; значение не выводится, найдите и уберите его")
    if PHONE_RE.search(text):
        errors.append("похоже на телефон; значение не выводится, найдите и уберите его")
    return errors, warnings


def validate_cards(cards_dir: Path, today: dt.date) -> int:
    """Напечатать результат проверки и вернуть число ошибок."""
    paths = sorted(cards_dir.glob("*.md"))
    total_errors = total_warnings = 0
    for path in paths:
        errors, warnings = check_card(path, today)
        for message in errors:
            print(f"{path.name}: ошибка: {message}")
        for message in warnings:
            print(f"{path.name}: предупреждение: {message}")
        total_errors += len(errors)
        total_warnings += len(warnings)
    print(f"карточек: {len(paths)}, ошибок: {total_errors}, предупреждений: {total_warnings}")
    return total_errors


def make_record(path: Path, fm: dict) -> dict:
    hiring = [post for post in (fm.get("hiring") or []) if isinstance(post, dict)]
    oss = fm.get("open_source") if isinstance(fm.get("open_source"), dict) else {}
    checked = as_date(fm.get("last_verified"))
    try:
        card = path.relative_to(ROOT).as_posix()
    except ValueError:
        card = path.name
    record = {
        "id": fm.get("id"),
        "name": fm.get("name"),
        "website": fm.get("website"),
        "sector": list(fm.get("sector") or []),
        "organization_type": fm.get("organization_type"),
        "founded": fm.get("founded"),
        "headquarters": fm.get("headquarters"),
        "technologies": list(fm.get("technologies") or []),
        "open_source_license": oss.get("license"),
        "open_source_repository": oss.get("repository"),
        "hiring_posts": len(hiring),
        "hiring_post_ids": [post.get("hn_item_id") for post in hiring],
        "hiring_roles": [role for post in hiring for role in (post.get("roles") or [])],
        "hiring_locations": [post.get("location") for post in hiring],
        "hiring_employment": [post.get("employment") for post in hiring],
        "salary_in_post": [post.get("salary_in_post") for post in hiring],
        "work_format": work_formats(hiring),
        "verification": fm.get("verification"),
        "unverified_claims": len(fm.get("unverified_claims") or []),
        "last_verified": checked.isoformat() if checked else fm.get("last_verified"),
        "card": card,
    }
    for key in OPTIONAL_FIELDS:
        if key in fm:
            record[key] = fm[key]
    return record


def load_records(cards_dir: Path):
    records, failures = [], []
    for path in sorted(cards_dir.glob("*.md")):
        try:
            fm, _ = read_card(path)
        except (OSError, ValueError) as exc:
            failures.append(f"{path.name}: {exc}")
            continue
        records.append(make_record(path, fm))
    return records, failures


def build_filter_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--sector", help="подстрока в списке сфер")
    parser.add_argument("--tech", help="подстрока в списке технологий")
    parser.add_argument("--role", help="подстрока в ролях вакансий")
    parser.add_argument("--location", help="подстрока в штаб-квартире или в местах вакансий")
    parser.add_argument("--work-format", type=lambda text: work_format_arg(text),
                        help="формат работы из текста вакансий: удалённо, гибрид или офис")
    parser.add_argument("--verification", help="значение поля verification")
    parser.add_argument("--open-source", action="store_true", help="лицензия указана")
    parser.add_argument("--salary", action="store_true", help="в посте указана зарплата")
    parser.add_argument("--founded", help="подстрока в поле founded")
    parser.add_argument("--verified-since", type=parse_day,
                        help="last_verified не раньше даты YYYY-MM-DD")
    return parser


def work_format_arg(text: str) -> str:
    for label in WORK_FORMATS:
        if norm(label) == norm(text):
            return label
    raise argparse.ArgumentTypeError(f"допустимо: {', '.join(WORK_FORMATS)}")


def contains(values, needle: str) -> bool:
    """Совпадение с начала слова: «ИИ» находит «ИИ-агенты», но не «положении»."""
    pattern = re.compile(r"(?<!\w)" + re.escape(norm(needle)))
    return any(pattern.search(norm(value)) for value in values if value is not None)


def is_stated(value) -> bool:
    """Данные есть, если значение не пустое и не начинается с «не указано».
    Пояснение после этих слов («не указано (сумма не названа…)») данных не добавляет."""
    if value is None:
        return False
    text = norm(str(value)).strip()
    return bool(text) and not text.startswith(norm(NOT_STATED))


def matches(record: dict, f: argparse.Namespace) -> bool:
    if f.sector is not None and not contains(record["sector"], f.sector):
        return False
    if f.tech is not None and not contains(record["technologies"], f.tech):
        return False
    if f.role is not None and not contains(record["hiring_roles"], f.role):
        return False
    if f.location is not None and not contains(
        [record["headquarters"], *record["hiring_locations"]], f.location
    ):
        return False
    if f.work_format is not None and f.work_format not in record["work_format"]:
        return False
    if f.verification is not None and norm(record["verification"]) != norm(f.verification):
        return False
    if f.open_source and not is_stated(record["open_source_license"]):
        return False
    if f.salary and not any(is_stated(value) for value in record["salary_in_post"]):
        return False
    if f.founded is not None and not contains([record["founded"]], f.founded):
        return False
    if f.verified_since is not None:
        last = record["last_verified"] or ""
        if last < f.verified_since.isoformat():
            return False
    return True


def cmd_validate(args) -> int:
    return 1 if validate_cards(args.cards, args.as_of) else 0


def cmd_export(args) -> int:
    if validate_cards(args.cards, dt.date.today()):
        print("выгрузка отменена: сначала исправьте ошибки проверки")
        return 1
    records, failures = load_records(args.cards)
    if failures:
        print("\n".join(failures))
        return 1
    records.sort(key=lambda record: str(record["id"]))
    args.out_dir.mkdir(parents=True, exist_ok=True)
    with (args.out_dir / "wiki-companies.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for record in records:
            row = {}
            for key in CSV_FIELDS:
                value = record.get(key)
                row[key] = " | ".join(str(v) for v in value) if isinstance(value, list) else ("" if value is None else value)
            writer.writerow(row)
    with (args.out_dir / "wiki-companies.json").open("w", encoding="utf-8") as handle:
        json.dump(records, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(f"записано карточек: {len(records)} в {args.out_dir}")
    return 0


def cmd_search(args) -> int:
    records, failures = load_records(args.cards)
    if failures:
        print("\n".join(failures))
        return 1
    hits = [record for record in records if matches(record, args)]
    if args.json:
        print(json.dumps(hits, ensure_ascii=False, indent=2))
    else:
        for record in hits:
            print(record["id"])
    return 0


def cmd_check(args) -> int:
    queries = json.loads((EVAL_DIR / "base_queries.json").read_text(encoding="utf-8"))
    manual = json.loads((EVAL_DIR / "base_manual.json").read_text(encoding="utf-8"))
    records, failures = load_records(args.cards)
    if failures:
        print("\n".join(failures))
        return 1
    filter_parser = build_filter_parser()
    agreed = 0
    for query in queries:
        f = filter_parser.parse_args(query["args"])
        got = sorted(record["id"] for record in records if matches(record, f))
        want = sorted(manual.get(query["id"], {}).get("ids", []))
        if got == want:
            agreed += 1
            print(f"{query['id']}: совпало, карточек: {len(got)}")
        else:
            print(f"{query['id']}: РАСХОЖДЕНИЕ")
            print(f"  только в базе: {sorted(set(got) - set(want))}")
            print(f"  только в ручном поиске: {sorted(set(want) - set(got))}")
    print(f"совпало запросов: {agreed} из {len(queries)}")
    return 0 if agreed == len(queries) else 1


def main(argv=None) -> int:
    filters = build_filter_parser()
    parser = argparse.ArgumentParser(description="База карточек вики: проверка, выгрузка, поиск.")
    commands = parser.add_subparsers(dest="command", required=True)

    p_validate = commands.add_parser("validate", help="проверить карточки")
    p_validate.add_argument("--cards", type=Path, default=CARDS_DIR)
    p_validate.add_argument("--as-of", type=parse_day, default=dt.date.today(),
                            help="дата, от которой считается давность проверки")
    p_validate.set_defaults(handler=cmd_validate)

    p_export = commands.add_parser("export", help="записать CSV и JSON")
    p_export.add_argument("--cards", type=Path, default=CARDS_DIR)
    p_export.add_argument("--out-dir", type=Path, default=DATA_DIR)
    p_export.set_defaults(handler=cmd_export)

    p_search = commands.add_parser("search", parents=[filters], help="найти карточки")
    p_search.add_argument("--cards", type=Path, default=CARDS_DIR)
    p_search.add_argument("--json", action="store_true", help="вывести полные записи, а не id")
    p_search.set_defaults(handler=cmd_search)

    p_check = commands.add_parser("check", help="сверить запросы с ручным поиском")
    p_check.add_argument("--cards", type=Path, default=CARDS_DIR)
    p_check.set_defaults(handler=cmd_check)

    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
