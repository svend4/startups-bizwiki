#!/usr/bin/env python3
"""База карточек вики: проверка шапок, выгрузка CSV и JSON, поиск по полям.

Команды:
  validate  проверить шапки, обязательные разделы и отсутствие контактов
  export    записать data/wiki-companies.csv и .json (только если проверка без ошибок)
  search    вывести id карточек, которые подходят под все заданные условия
  check     сверить запросы из tools/eval/base_queries.json с ручным поиском

Нужны Python 3.9+ и PyYAML (pip install pyyaml). Карточки скрипт не меняет.
Тесты: python3 -m unittest discover -s tools/eval -p 'test_*.py'
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
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
KNOWN_FIELDS = set(REQUIRED_FIELDS) | set(OPTIONAL_FIELDS)
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
# Слова ищутся с начала слова. «не удалённо» и «удалённо не предусмотрено» удалённой работой не считаются.
WORK_FORMAT_RULES = {
    "удалённо": re.compile(
        r"(?<!не )(?<!no )(?<!not )\b(?:удал\w*(?!\w)(?!\s+не\b)|remote(?!\w)(?!\s+not\b))",
        re.IGNORECASE,
    ),
    "гибрид": re.compile(r"(?<!не )\b(?:гибрид|hybrid)", re.IGNORECASE),
    "офис": re.compile(r"(?<!не )\b(?:onsite|on[- ]site|очно\b|офис|in[- ]office)", re.IGNORECASE),
}
# В карточках пишут «ИИ», пользователь может ввести «AI»: для поиска это одно и то же.
SYNONYMS = {"ии": ("ии", "ai"), "ai": ("ии", "ai")}
STALE_DAYS = 90

ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
URL_RE = re.compile(r"^https://[^\s/]+\.[^\s]+$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CARD_RE = re.compile(r"^---\n(.*?)\n---\n(.*)\Z", re.S)
HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.M)
TITLE_RE = re.compile(r"^#\s+\S", re.M)
PII_RULES = [
    ("похоже на e-mail", re.compile(r"[\w.%+-]+@[\w-]+(?:\.[\w-]+)*\.[^\W\d_]{2,}")),
    ("похоже на e-mail с обходом", re.compile(r"\[at\]|\(at\)|\[dot\]|\(dot\)", re.IGNORECASE)),
    ("похоже на телефон с кодом страны", re.compile(r"(?<![\w/])\+\d{1,3}[\s\-()]*\d[\d\s\-()]{6,}\d")),
    ("похоже на телефон без «+»", re.compile(r"(?<![\w/.:])0\d(?:[\s\-]?\d){6,12}(?!\d)")),
]

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
    """Дата без времени: строка YYYY-MM-DD или дата, которую YAML разобрал сам. Дата со временем — не дата."""
    if isinstance(value, dt.datetime):
        return None
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str) and DATE_RE.match(value):
        try:
            return dt.date.fromisoformat(value)
        except ValueError:
            return None
    return None


def parse_day(text: str) -> dt.date:
    if not DATE_RE.match(text):
        raise argparse.ArgumentTypeError(f"нужна дата YYYY-MM-DD, получено {text!r}")
    try:
        return dt.date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"такой даты не существует: {text!r}")


def nonempty(text: str) -> str:
    if not text.strip():
        raise argparse.ArgumentTypeError("значение фильтра не может быть пустым")
    return text


def work_format_arg(text: str) -> str:
    for label in WORK_FORMATS:
        if norm(label) == norm(text):
            return label
    raise argparse.ArgumentTypeError(f"допустимо: {', '.join(WORK_FORMATS)}")


def split_card(path: Path):
    """Вернуть (текст шапки, тело). При сбое — ValueError с понятным текстом."""
    text = path.read_text(encoding="utf-8-sig")
    match = CARD_RE.match(text)
    if not match:
        raise ValueError("нет шапки между строками ---")
    return match.group(1), match.group(2)


def pii_problems(front_text: str, body: str) -> list:
    """Контакты в шапке и в теле. Найденное значение в сообщение не выводится."""
    problems = []
    for label, text in (("в шапке", front_text), ("в теле", body)):
        for rule_name, rule in PII_RULES:
            for match in rule.finditer(text):
                where = label
                if label == "в теле":
                    where += f", строка {text.count(chr(10), 0, match.start()) + 1}"
                problems.append(f"{rule_name} ({where}); значение не выводится, найдите и уберите его")
    return problems


def check_text_list(errors: list, name: str, container: dict, nonempty: bool = False, label=None) -> None:
    """Список текстов: не список, пустой (если нужно) или с пустыми элементами."""
    if name not in container or container[name] is None:
        return
    shown = label or name
    value = container[name]
    if not isinstance(value, list):
        errors.append(f"«{shown}»: нужен список")
        return
    if nonempty and not value:
        errors.append(f"«{shown}»: список пуст")
        return
    for i, item in enumerate(value, 1):
        if not isinstance(item, str) or not item.strip():
            errors.append(f"«{shown}»: элемент {i} пустой или не текст")


def check_card(path: Path, today: dt.date):
    """Вернуть (ошибки, предупреждения). Контакты и разделы тела проверяются, даже если шапка сломана."""
    errors, warnings = [], []
    try:
        front_text, body = split_card(path)
    except (OSError, ValueError) as exc:
        return [str(exc)], []

    headings = HEADING_RE.findall(body)
    if not TITLE_RE.search(body):
        errors.append("в теле нет заголовка первого уровня")
    for title in REQUIRED_HEADINGS:
        if title not in headings:
            errors.append(f"в теле нет раздела «## {title}»")
    errors.extend(pii_problems(front_text, body))

    try:
        fm = yaml.safe_load(front_text)
    except (yaml.YAMLError, ValueError) as exc:
        errors.append(f"шапка не разбирается (синтаксис YAML или дата): {exc}")
        return errors, warnings
    if not isinstance(fm, dict):
        errors.append("шапка должна быть набором полей «ключ: значение»")
        return errors, warnings

    for key in fm:
        if not isinstance(key, str):
            errors.append(f"ключ шапки {key!r} должен быть текстом: YAML принял его за число или логическое значение")
    for field in REQUIRED_FIELDS:
        if field not in fm:
            errors.append(f"нет поля «{field}»")
        elif fm[field] is None:
            errors.append(f"поле «{field}» пустое")
    extra = sorted(key for key in fm if isinstance(key, str) and key not in KNOWN_FIELDS)
    if extra:
        warnings.append("поля вне схемы: " + ", ".join(extra))

    if "id" in fm:
        cid = fm["id"]
        if not isinstance(cid, str) or not ID_RE.match(cid):
            errors.append(f"«id» {cid!r}: нужны латинские буквы, цифры и дефисы")
        elif cid != path.stem:
            errors.append(f"«id» {cid!r} не совпадает с именем файла «{path.stem}»")
    for field in ("name", "organization_type", "founded", "headquarters"):
        value = fm.get(field)
        if field in fm and value is not None and (not isinstance(value, str) or not value.strip()):
            errors.append(f"«{field}»: нужна непустая строка, получено {value!r}")
    if "website" in fm and fm["website"] is not None:
        if not (isinstance(fm["website"], str) and URL_RE.match(fm["website"])):
            errors.append(f"«website»: нужен адрес с https://, получено {fm['website']!r}")
    check_text_list(errors, "sector", fm, nonempty=True)
    check_text_list(errors, "technologies", fm)
    check_text_list(errors, "unverified_claims", fm)

    if "open_source" in fm and fm["open_source"] is not None:
        oss = fm["open_source"]
        if not isinstance(oss, dict) or set(oss) != {"license", "repository"}:
            errors.append("«open_source»: нужен словарь с полями license и repository")
        else:
            for key in ("license", "repository"):
                if not isinstance(oss[key], str) or not oss[key].strip():
                    errors.append(f"«open_source.{key}»: нужна строка или «не указано», получено {oss[key]!r}")
            license_text = oss["license"] if isinstance(oss["license"], str) else ""
            if license_text.startswith(NOT_STATED) and re.search(r"\d", license_text):
                warnings.append("«open_source.license» начинается с «не указано», но содержит цифры: проверьте")

    if fm.get("verification") is not None and fm["verification"] not in VERIFICATION_VALUES:
        errors.append(f"«verification»: {fm['verification']!r} не входит в допустимые значения")

    if "last_verified" in fm and fm["last_verified"] is not None:
        checked = as_date(fm["last_verified"])
        if checked is None:
            errors.append(f"«last_verified»: нужна дата YYYY-MM-DD без времени, получено {fm['last_verified']!r}")
        elif checked > today:
            errors.append(f"«last_verified» {checked} позже даты проверки {today}")
        elif (today - checked).days > STALE_DAYS:
            warnings.append(f"«last_verified» {checked}: старше {STALE_DAYS} дней, нужна повторная проверка")

    source_urls = []
    if "sources" in fm and fm["sources"] is not None:
        if not isinstance(fm["sources"], list):
            errors.append("«sources»: нужен список")
        else:
            for i, src in enumerate(fm["sources"], 1):
                if not isinstance(src, dict):
                    errors.append(f"sources[{i}]: нужен словарь полей url, kind, accessed")
                    continue
                missing = [key for key in SOURCE_FIELDS if key not in src]
                if missing:
                    errors.append(f"sources[{i}]: нет полей {', '.join(missing)}")
                url = src.get("url")
                if isinstance(url, str):
                    source_urls.append(url)
                if "url" in src and not (isinstance(url, str) and URL_RE.match(url)):
                    errors.append(f"sources[{i}]: нужна ссылка с https://, получено {url!r}")
                if "kind" in src and (not isinstance(src["kind"], str) or not src["kind"].strip()):
                    errors.append(f"sources[{i}]: «kind» должен быть непустой строкой")
                if "accessed" in src:
                    accessed = as_date(src["accessed"])
                    if accessed is None:
                        errors.append(f"sources[{i}]: «accessed» должна быть датой YYYY-MM-DD без времени")
                    elif accessed > today:
                        errors.append(f"sources[{i}]: «accessed» {accessed} позже даты проверки")

    if "hiring" in fm and fm["hiring"] is not None:
        if not isinstance(fm["hiring"], list):
            errors.append("«hiring»: нужен список")
        else:
            for i, post in enumerate(fm["hiring"], 1):
                if not isinstance(post, dict):
                    errors.append(f"hiring[{i}]: нужен словарь полей")
                    continue
                missing = [key for key in HIRING_FIELDS if key not in post]
                if missing:
                    errors.append(f"hiring[{i}]: нет полей {', '.join(missing)}")
                for key in HIRING_FIELDS:
                    if key in post and post[key] is None:
                        errors.append(f"hiring[{i}]: поле «{key}» пустое")
                for key in ("thread", "location", "employment", "salary_in_post"):
                    value = post.get(key)
                    if value is not None and not isinstance(value, str):
                        errors.append(f"hiring[{i}]: «{key}» должен быть текстом, получено {value!r}")
                salary = post.get("salary_in_post")
                if isinstance(salary, str) and salary.startswith(NOT_STATED) and re.search(r"\d", salary):
                    warnings.append(f"hiring[{i}]: «salary_in_post» начинается с «не указано», но содержит цифры: проверьте")
                if post.get("hn_item_id") is not None:
                    post_id = post["hn_item_id"]
                    if not isinstance(post_id, int) or isinstance(post_id, bool):
                        errors.append(f"hiring[{i}]: «hn_item_id» должен быть числом")
                    elif not any(re.search(rf"item\?id={post_id}(?!\d)", url) for url in source_urls):
                        errors.append(f"hiring[{i}]: в sources нет ссылки на пост item?id={post_id}")
                check_text_list(errors, "roles", post, nonempty=True, label=f"hiring[{i}].roles")

    if fm.get("unverified_claims") and CLAIMS_HEADING not in headings:
        errors.append(f"есть непроверенные заявления, но нет раздела «## {CLAIMS_HEADING}»")
    return errors, warnings


def run_validate(cards_dir: Path, today: dt.date) -> int:
    if not cards_dir.is_dir():
        print(f"каталог с карточками не найден: {cards_dir}")
        return 1
    paths = sorted(cards_dir.glob("*.md"))
    if not paths:
        print(f"в каталоге нет карточек *.md: {cards_dir}")
        return 1
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
    return 1 if total_errors else 0


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


def work_formats(hiring) -> list:
    """Формат работы из текста вакансий (location и employment). Это производное поле."""
    found = set()
    for post in hiring:
        text = f"{post.get('location') or ''} {post.get('employment') or ''}"
        for label, rule in WORK_FORMAT_RULES.items():
            if rule.search(text):
                found.add(label)
    ordered = [label for label in WORK_FORMATS if label in found]
    return ordered or [NOT_STATED]


def load_cards(cards_dir: Path, today: dt.date):
    """Вернуть (записи, ошибки). Если ошибки есть, результату верить нельзя: команды останавливаются."""
    if not cards_dir.is_dir():
        return [], [f"каталог с карточками не найден: {cards_dir}"]
    paths = sorted(cards_dir.glob("*.md"))
    if not paths:
        return [], [f"в каталоге нет карточек *.md: {cards_dir}"]
    records, problems = [], []
    for path in paths:
        errors, _ = check_card(path, today)
        if errors:
            problems.extend(f"{path.name}: ошибка: {message}" for message in errors)
            continue
        front_text, _ = split_card(path)
        records.append(make_record(path, yaml.safe_load(front_text)))
    return records, problems


def build_filter_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--sector", type=nonempty,
                        help="слово или начало слова в списке сфер; «ИИ» и «AI» равнозначны")
    parser.add_argument("--tech", type=nonempty, help="слово или начало слова в списке технологий")
    parser.add_argument("--role", type=nonempty, help="слово или начало слова в ролях вакансий")
    parser.add_argument("--location", type=nonempty,
                        help="слово или начало слова в штаб-квартире или в местах вакансий")
    parser.add_argument("--work-format", type=work_format_arg,
                        help="формат работы из текста вакансий: удалённо, гибрид или офис")
    parser.add_argument("--verification", type=nonempty, help="значение поля verification целиком")
    parser.add_argument("--open-source", action="store_true", help="лицензия указана")
    parser.add_argument("--salary", action="store_true", help="в посте указана зарплата")
    parser.add_argument("--founded", type=nonempty,
                        help="слово или начало слова в поле founded (это текст, а не год)")
    parser.add_argument("--verified-since", type=parse_day,
                        help="last_verified не раньше даты YYYY-MM-DD")
    return parser


def contains(values, needle: str) -> bool:
    """Совпадение с начала слова: «ИИ» находит «ИИ-агенты», но не «положении»."""
    key = norm(needle)
    variants = SYNONYMS.get(key, (key,))
    pattern = re.compile(r"(?<!\w)(?:" + "|".join(re.escape(v) for v in variants) + ")")
    return any(pattern.search(norm(value)) for value in values if value is not None)


def is_stated(value) -> bool:
    """Данные есть, если значение не пустое и не начинается с «не указано».
    Пояснение после этих слов («не указано (сумма не названа…)») данных не добавляет."""
    if value is None:
        return False
    text = norm(str(value)).strip()
    return bool(text) and not text.startswith(norm(NOT_STATED))


def matches(record: dict, f) -> bool:
    if f.sector is not None and not contains(record["sector"], f.sector):
        return False
    if f.tech is not None and not contains(record["technologies"], f.tech):
        return False
    if f.role is not None and not contains(record["hiring_roles"], f.role):
        return False
    if f.location is not None and not contains([record["headquarters"], *record["hiring_locations"]], f.location):
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
    if f.verified_since is not None and (record["last_verified"] or "") < f.verified_since.isoformat():
        return False
    return True


def csv_cell(value):
    if value is None:
        return ""
    if isinstance(value, list):
        return " | ".join("" if item is None else str(item) for item in value)
    return value


def write_export(records, out_dir: Path) -> None:
    """Сначала пишутся временные файлы, потом они заменяют старую выгрузку: при сбое старые файлы целы."""
    csv_path = out_dir / "wiki-companies.csv"
    json_path = out_dir / "wiki-companies.json"
    tmp_csv = out_dir / "wiki-companies.csv.tmp"
    tmp_json = out_dir / "wiki-companies.json.tmp"
    try:
        with tmp_csv.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
            writer.writeheader()
            for record in records:
                writer.writerow({key: csv_cell(record.get(key)) for key in CSV_FIELDS})
        with tmp_json.open("w", encoding="utf-8") as handle:
            json.dump(records, handle, ensure_ascii=False, indent=2, default=str)
            handle.write("\n")
        os.replace(tmp_csv, csv_path)
        os.replace(tmp_json, json_path)
    finally:
        for tmp in (tmp_csv, tmp_json):
            if tmp.exists():
                tmp.unlink()


def cmd_validate(args) -> int:
    return run_validate(args.cards, args.as_of)


def cmd_export(args) -> int:
    records, problems = load_cards(args.cards, dt.date.today())
    if problems:
        print("\n".join(problems))
        print("выгрузка отменена: сначала исправьте ошибки")
        return 1
    if args.out_dir.exists() and not args.out_dir.is_dir():
        print(f"--out-dir должен быть каталогом: {args.out_dir}")
        return 1
    args.out_dir.mkdir(parents=True, exist_ok=True)
    records.sort(key=lambda record: str(record["id"]))
    write_export(records, args.out_dir)
    print(f"записано карточек: {len(records)} в {args.out_dir}")
    return 0


def cmd_search(args) -> int:
    records, problems = load_cards(args.cards, dt.date.today())
    if problems:
        print("\n".join(problems))
        print("поиск остановлен: исправьте карточки")
        return 1
    hits = [record for record in records if matches(record, args)]
    if args.json:
        print(json.dumps(hits, ensure_ascii=False, indent=2, default=str))
    else:
        for record in hits:
            print(record["id"])
    return 0


def cmd_check(args) -> int:
    manual_path = EVAL_DIR / "base_manual.json"
    if not manual_path.exists():
        print(f"нет файла с ручным поиском: {manual_path}")
        return 1
    queries = json.loads((EVAL_DIR / "base_queries.json").read_text(encoding="utf-8"))
    manual = json.loads(manual_path.read_text(encoding="utf-8"))
    records, problems = load_cards(args.cards, dt.date.today())
    if problems:
        print("\n".join(problems))
        print("сверка остановлена: исправьте карточки")
        return 1
    filter_parser = build_filter_parser()
    agreed = 0
    for query in queries:
        qid = query["id"]
        if qid not in manual:
            print(f"{qid}: нет ручного результата")
            continue
        f = filter_parser.parse_args(query["args"])
        got = sorted(record["id"] for record in records if matches(record, f))
        want = sorted(manual[qid].get("ids", []))
        if got == want:
            agreed += 1
            print(f"{qid}: совпало, карточек: {len(got)}")
        else:
            print(f"{qid}: РАСХОЖДЕНИЕ")
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
                            help="дата, относительно которой считаются давность и будущие даты")
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
