#!/usr/bin/env python3
"""Точность признаков выгрузки против эталона из трёх независимых оценщиков.

Пример:
    python3 tools/eval/score.py --csv data/hn-hiring-2026-11.csv --set baseline
    python3 tools/eval/score.py --csv data/hn-hiring-2026-11.csv --set holdout

Эталон: tools/eval/gold.json. Для каждого поста есть три ответа оценщиков (разные
языковые модели) по определениям из docs/tochnost-priznakov.md. Эталон поста — большинство
голосов (больше половины); тег входит в эталон, если его выбрали больше половины оценщиков.

Выборка baseline использовалась для настройки правил экспорта; holdout — только для проверки.
Признаки сравниваются с колонками CSV, которые пишет tools/hn_hiring_export.py.
"""

import argparse
import collections
import csv
import json
import os

BOOL_MAP = {  # поле эталона -> колонка CSV
    "remote": "remote",
    "onsite": "onsite_mentioned",
    "hybrid": "hybrid",
    "salary_stated": "salary_mentioned",
    "ai_mentioned": "ai_mentioned",
    "yc_mentioned": "yc_mentioned",
    "contact_email_present": "contact_email_present",
    "location_present": "location_present",
    "self_promo": "self_promo_guess",
}
TAG_MAP = {"tech": "tech", "roles": "roles"}


def is_true(value):
    return str(value) == "True"


def csv_tags(value):
    return {t for t in (value or "").split(";") if t}


def prf(pairs):
    tp = sum(1 for p, g in pairs if p and g)
    fp = sum(1 for p, g in pairs if p and not g)
    fn = sum(1 for p, g in pairs if not p and g)
    tn = sum(1 for p, g in pairs if not p and not g)
    return {
        "n": len(pairs), "gold_pos": tp + fn, "pred_pos": tp + fp,
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": round(tp / (tp + fp), 3) if tp + fp else None,
        "recall": round(tp / (tp + fn), 3) if tp + fn else None,
        "accuracy": round((tp + tn) / len(pairs), 3) if pairs else None,
    }


def gold_for_post(raters):
    n = len(raters)
    gold = {}
    unanimous = {}
    for f in BOOL_MAP:
        votes = [r[f] is True for r in raters]
        gold[f] = sum(votes) > n / 2
        unanimous[f] = len(set(votes)) == 1
    for tf in TAG_MAP:
        cnt = collections.Counter(t for r in raters for t in set(r[tf]))
        gold[tf] = {t for t, c in cnt.items() if c > n / 2}
    return gold, unanimous


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", required=True, help="CSV выгрузки (колонки как в hn_hiring_export.py)")
    ap.add_argument("--set", required=True, choices=["baseline", "holdout"])
    ap.add_argument("--gold", default=os.path.join(os.path.dirname(__file__), "gold.json"))
    ap.add_argument("--out", help="куда записать подробный отчёт в JSON")
    args = ap.parse_args()

    with open(args.gold, encoding="utf-8") as fh:
        gold_doc = json.load(fh)
    labelled = gold_doc[args.set]
    with open(args.csv, encoding="utf-8") as fh:
        rows = {r["hn_item_id"]: r for r in csv.DictReader(fh)}

    gold, pred, unanimous = {}, {}, collections.defaultdict(list)
    for pid, raters in labelled.items():
        if pid not in rows:
            continue
        g, un = gold_for_post(raters)
        gold[pid] = g
        for f, u in un.items():
            unanimous[f].append(u)
        row = rows[pid]
        p = {f: is_true(row[col]) for f, col in BOOL_MAP.items()}
        for tf, col in TAG_MAP.items():
            p[tf] = csv_tags(row[col])
        pred[pid] = p

    scored = sorted(gold)
    report = {"set": args.set, "posts_scored": len(scored), "posts_in_gold": len(labelled),
              "booleans": {}, "tags": {}, "mismatches": []}
    for f, col in BOOL_MAP.items():
        pairs = [(pred[i][f], gold[i][f]) for i in scored]
        report["booleans"][f] = dict(prf(pairs), csv_column=col,
                                     unanimous_share=round(sum(unanimous[f]) / len(unanimous[f]), 3))
        for i in scored:
            if pred[i][f] != gold[i][f]:
                report["mismatches"].append({"id": i, "field": f, "regex": pred[i][f], "gold": gold[i][f]})
    for tf in TAG_MAP:
        universe = set()
        for i in scored:
            universe |= pred[i][tf] | gold[i][tf]
        pooled = []
        per_tag = {}
        for t in sorted(universe):
            pairs = [(t in pred[i][tf], t in gold[i][tf]) for i in scored]
            per_tag[t] = prf(pairs)
            pooled.extend(pairs)
            for i in scored:
                a, b = t in pred[i][tf], t in gold[i][tf]
                if a != b:
                    report["mismatches"].append({"id": i, "field": tf, "tag": t, "regex": a, "gold": b})
        report["tags"][tf] = {"micro": prf(pooled), "per_tag": per_tag}

    print(f"набор: {args.set}; постов в эталоне: {len(labelled)}; из них есть в CSV: {len(scored)}")
    print(f"{'признак':24s} {'точность':>9s} {'полнота':>8s} {'эталон+':>8s} {'CSV+':>6s} {'FP':>4s} {'FN':>4s}")
    for f, r in report["booleans"].items():
        print(f"{f:24s} {str(r['precision']):>9s} {str(r['recall']):>8s} {r['gold_pos']:>8d} {r['pred_pos']:>6d} {r['fp']:>4d} {r['fn']:>4d}")
    for tf, r in report["tags"].items():
        m = r["micro"]
        print(f"{tf:24s} {str(m['precision']):>9s} {str(m['recall']):>8s} {m['gold_pos']:>8d} {m['pred_pos']:>6d} {m['fp']:>4d} {m['fn']:>4d}  (по тегам)")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=1)
        print("отчёт записан:", args.out)


if __name__ == "__main__":
    main()
