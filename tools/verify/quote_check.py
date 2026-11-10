"""Check that every verbatim quote in a verdicts file really occurs in the stored text file.

Usage: quote_check.py <verdicts.json> [more verdicts.json ...]
Only verdicts with status supported or partly_supported are checked.
Whitespace and case are normalised; a mismatch needs a human look (it may be a
punctuation difference), it does not prove the claim is false.
"""
import html
import json
import re
import sys


def norm(s):
    return re.sub(r"\s+", " ", s).strip().lower()


total = 0
problems = 0
for path in sys.argv[1:]:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as exc:  # missing or malformed file
        print(f"{path}: cannot read ({exc})")
        problems += 1
        continue
    verdicts = data.get("verdicts", []) if isinstance(data, dict) else data
    for v in verdicts:
        if v.get("status") not in ("supported", "partly_supported"):
            continue
        total += 1
        quote = v.get("quote", "")
        if not quote:
            print(f"{path}: {v.get('claim_id')} has no quote")
            problems += 1
            continue
        try:
            with open(v.get("checked_file", ""), encoding="utf-8") as fh:
                text = fh.read()
            if v.get("checked_file", "").endswith((".html", ".htm")):
                text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", text)
                text = re.sub(r"<[^>]+>", " ", text)
                text = html.unescape(text)
            elif v.get("checked_file", "").endswith(".json"):
                text = json.dumps(json.loads(text), ensure_ascii=False)
        except Exception as exc:
            print(f"{path}: {v.get('claim_id')} file error ({exc})")
            problems += 1
            continue
        if norm(quote) not in norm(text):
            print(f"{path}: {v.get('claim_id')} quote not found in {v.get('checked_file')}")
            problems += 1
print(f"checked {total} positive verdicts; problems: {problems}")
