"""Тесты базы карточек. Запуск из корня репозитория:

    python3 -m unittest discover -s tools/eval -p 'test_*.py'
"""

import argparse
import contextlib
import datetime as dt
import importlib.util
import io
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("wiki_base", ROOT / "tools" / "wiki_base.py")
wb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wb)

TODAY = dt.date(2026, 11, 22)

VALID = """---
id: demo
name: Demo
website: https://example.com
sector: ["ИИ-агенты"]
organization_type: "тест"
founded: "2020 (тест)"
headquarters: "Берлин"
technologies: ["Python"]
open_source:
  license: не указано
  repository: не указано
hiring:
  - thread: "Ask HN: Who is hiring? (November 2026)"
    hn_item_id: 50338907
    roles: ["Engineer"]
    location: "удалённо"
    employment: "Full-time"
    salary_in_post: не указано
sources:
  - {url: "https://example.com", kind: "сайт компании", accessed: "2026-11-10"}
  - {url: "https://news.ycombinator.com/item?id=50338907", kind: "пост компании на HN", accessed: "2026-11-10"}
verification: сайт + пост
unverified_claims: []
last_verified: "2026-11-10"
---

# Demo

> **Почему в выборке:** тест.

## Кто они

Текст.

## Кого ищут

Текст.

## Пробелы

Текст.

## Источники

Текст.
"""


class CardChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.cards = self.tmp / "companies"
        self.cards.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def check(self, text, name="demo.md"):
        path = self.cards / name
        path.write_text(text, encoding="utf-8")
        return wb.check_card(path, TODAY)

    def test_template_is_valid(self):
        errors, _ = self.check(VALID)
        self.assertEqual(errors, [])

    def test_repo_cards_are_valid(self):
        for path in sorted((ROOT / "wiki" / "companies").glob("*.md")):
            errors, _ = wb.check_card(path, TODAY)
            self.assertEqual(errors, [], path.name)

    def test_non_string_key_is_reported_not_crashed(self):
        errors, _ = self.check(VALID.replace("id: demo", "id: demo\n1: тест"))
        self.assertTrue(any("ключ шапки" in e for e in errors), errors)

    def test_broken_yaml_still_checks_body(self):
        text = VALID.replace('sector: ["ИИ-агенты"]', 'sector: ["ИИ-агенты"').replace(
            "Текст.", "Пишите: press@example.com", 1)
        errors, _ = self.check(text)
        self.assertTrue(any("шапка не разбирается" in e for e in errors), errors)
        self.assertTrue(any("e-mail" in e for e in errors), errors)

    def test_null_field_is_reported(self):
        errors, _ = self.check(VALID.replace('organization_type: "тест"', "organization_type:"))
        self.assertTrue(any("«organization_type» пустое" in e for e in errors), errors)

    def test_empty_list_item_is_reported(self):
        errors, _ = self.check(VALID.replace('sector: ["ИИ-агенты"]', 'sector: ["", "ИИ"]'))
        self.assertTrue(any("элемент 1 пустой" in e for e in errors), errors)

    def test_datetime_accessed_is_rejected(self):
        errors, _ = self.check(VALID.replace('accessed: "2026-11-10"', "accessed: 2026-11-10T14:30:00", 1))
        self.assertTrue(any("«accessed» должна быть датой" in e for e in errors), errors)

    def test_future_date_is_rejected(self):
        errors, _ = self.check(VALID.replace('last_verified: "2026-11-10"', 'last_verified: "2027-11-10"'))
        self.assertTrue(any("позже даты проверки" in e for e in errors), errors)

    def test_contacts_in_body_are_found(self):
        samples = {
            "Контакт: иван@пример.рф": "e-mail",
            "Контакт: press [at] example [dot] com": "с обходом",
            "Телефон: 030 1234567.": "без «+»",
            "Телефон: +49 30 1234567": "с кодом страны",
        }
        for sample, fragment in samples.items():
            with self.subTest(sample=sample):
                errors, _ = self.check(VALID.replace("Текст.", sample, 1))
                self.assertTrue(any(fragment in e for e in errors), errors)

    def test_hn_item_id_must_match_exactly(self):
        errors, _ = self.check(VALID.replace("hn_item_id: 50338907", "hn_item_id: 5033890"))
        self.assertTrue(any("нет ссылки на пост" in e for e in errors), errors)

    def test_links_must_be_https(self):
        errors, _ = self.check(VALID.replace("website: https://example.com", "website: http://example.com"))
        self.assertTrue(any("https" in e for e in errors), errors)

    def test_salary_with_digits_under_not_stated_warns(self):
        _, warnings = self.check(
            VALID.replace("salary_in_post: не указано", 'salary_in_post: "не указано (в 2026 году, $200K)"'))
        self.assertTrue(any("salary_in_post" in w for w in warnings), warnings)


class LoadingAndExport(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.cards = self.tmp / "companies"
        self.cards.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_missing_directory_is_an_error(self):
        records, problems = wb.load_cards(self.tmp / "nope", TODAY)
        self.assertEqual(records, [])
        self.assertTrue(problems)

    def test_empty_directory_is_an_error(self):
        records, problems = wb.load_cards(self.cards, TODAY)
        self.assertEqual(records, [])
        self.assertTrue(problems)

    def test_one_broken_card_blocks_the_base(self):
        (self.cards / "good.md").write_text(VALID.replace("id: demo", "id: good"), encoding="utf-8")
        broken = VALID.replace("id: demo", "id: bad").replace('sector: ["ИИ-агенты"]', 'sector: ["ИИ-агенты"')
        (self.cards / "bad.md").write_text(broken, encoding="utf-8")
        _, problems = wb.load_cards(self.cards, TODAY)
        self.assertTrue(any(p.startswith("bad.md") for p in problems), problems)

    def test_export_refuses_and_writes_nothing(self):
        broken = VALID.replace("id: demo", "id: bad").replace("verification: сайт + пост", "verification: ок")
        (self.cards / "bad.md").write_text(broken, encoding="utf-8")
        out = self.tmp / "out"
        with contextlib.redirect_stdout(io.StringIO()):
            code = wb.cmd_export(argparse.Namespace(cards=self.cards, out_dir=out))
        self.assertEqual(code, 1)
        self.assertFalse(out.exists())

    def test_csv_cell_drops_none(self):
        self.assertEqual(wb.csv_cell([None, "x"]), " | x")
        self.assertEqual(wb.csv_cell(None), "")


class Search(unittest.TestCase):
    def test_empty_filter_value_is_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            wb.build_filter_parser().parse_args(["--tech", ""])

    def test_text_filters_match_word_start_only(self):
        self.assertFalse(wb.contains(["геолокация: инфраструктура и данные о местоположении (по сайту)"], "ИИ"))
        self.assertTrue(wb.contains(["ИИ-агенты"], "ИИ"))
        self.assertTrue(wb.contains(["AI-agents"], "ИИ"))
        self.assertTrue(wb.contains(["Software Engineers (SRE)"], "engineer"))

    def test_work_format_rules(self):
        self.assertEqual(wb.work_formats([{"location": "ONSITE", "employment": ""}]), ["офис"])
        self.assertEqual(wb.work_formats([{"location": "Berlin, in-office", "employment": ""}]), ["офис"])
        self.assertEqual(wb.work_formats([{"location": "на Восточном побережье", "employment": "Full-time"}]),
                         ["не указано"])
        self.assertEqual(wb.work_formats([{"location": "не удалённо", "employment": ""}]), ["не указано"])
        self.assertEqual(wb.work_formats([{"location": "удалённо не предусмотрено", "employment": ""}]),
                         ["не указано"])
        self.assertEqual(wb.work_formats([{"location": "гибрид или удалённо", "employment": ""}]),
                         ["удалённо", "гибрид"])

    def test_not_stated_prefix_means_no_data(self):
        self.assertFalse(wb.is_stated("не указано в собранных источниках"))
        self.assertFalse(wb.is_stated(None))
        self.assertTrue(wb.is_stated("Apache-2.0"))


if __name__ == "__main__":
    unittest.main()
