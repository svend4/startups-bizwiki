#!/usr/bin/env python3
"""Выгрузка комментариев темы «Ask HN: Who is hiring?» в CSV (правила версии 2).

Пример:
    python3 tools/hn_hiring_export.py --story 50338728 --out data/hn-hiring-2026-11.csv
    python3 tools/hn_hiring_export.py --story 50338728 --out data/hn-hiring-2026-11.csv \
        --prev data/hn-hiring-2026-10.csv

Скрипт читает публичное API Hacker News (https://github.com/HackerNews/API)
и для каждого комментария записывает только производные признаки: домен ссылки,
формат работы, упоминания зарплаты, ИИ, технологий и ролей.

В CSV НЕ попадают: текст комментариев, адреса электронной почты и полные ссылки.
Флаг contact_email_present лишь отмечает, что контакт есть в посте.

Признаки определяются регулярными выражениями, то есть это оценка, а не точная
разметка. Точность измерена на двух выборках по 30 постов против эталона из трёх
независимых оценщиков (docs/analiz-idei.md, раздел «Точность признаков»).
Правила версии 2 настроены по выборке разработки; holdout-выборка использовалась
только для проверки. Версия 1 сохранена в tools/hn_hiring_export_v1.py.
"""

import argparse
import collections
import concurrent.futures as cf
import csv
import html
import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urlparse

HN_ITEM = "https://hacker-news.firebaseio.com/v0/item/{}.json"

# Сервисы подбора персонала (ATS) и короткие ссылки на их страницы вакансий.
ATS_HOSTS = {
    "ashbyhq.com", "greenhouse.io", "grnh.se", "lever.co", "workable.com",
    "recruitee.com", "join.com", "personio.com", "myworkdayjobs.com",
    "pinpointhq.com", "rippling.com", "smartrecruiters.com", "bamboohr.com",
    "breezy.hr", "devitjobs.com",
}
# Общие сервисы: ссылка не говорит, какая это компания.
NEUTRAL_HOSTS = {
    "forms.gle", "notion.site", "typeform.com", "tally.so", "youtube.com",
    "youtu.be", "google.com", "netlify.app", "workatastartup.com", "wellfound.com",
    "linkedin.com", "github.com",
}
# Служебные ссылки самого HN и сервисов поиска работы, их пропускаем.
SKIP_HOSTS = {"ycombinator.com", "gethnjobs.com", "hnwork.app"}

# Технологии. Для языков и инструментов, которые пишут и со строчной буквы, включено (?i).
TECH = {
    "Python": r"(?i)\bpython\b", "TypeScript": r"(?i)\btypescript\b", "JavaScript": r"(?i)\bjavascript\b",
    "React": r"(?i)\breact\b(?!\s+native)", "Next.js": r"(?i)next\.?js", "Node.js": r"(?i)\bnode(\.js)?\b",
    # Go в перечислении языков: «Python, Go» или «and Go»; глагол «go to market» не считается.
    "Golang": r"\bGolang\b|(?:,|/|\band|\bor)\s+Go\b(?![-\s]to\b)",
    "Rust": r"\bRust\b", "Java": r"\bJava\b", "Kotlin": r"(?i)\bkotlin\b",
    "Scala": r"\bScala\b", "C++": r"C\+\+", "C#/.NET": r"C#|\.NET\b",
    "Ruby/Rails": r"(?i)\bruby\b|\bRails\b", "PHP": r"\bPHP\b", "Elixir": r"(?i)\belixir\b",
    "Swift": r"\bSwift\b", "Clojure": r"(?i)\bclojure\b",
    "PostgreSQL": r"(?i)\bpostgres(ql)?\b", "MySQL": r"(?i)\bmysql\b", "MongoDB": r"(?i)\bmongo(db)?\b",
    "Redis": r"(?i)\bredis\b", "Kafka": r"(?i)\bkafka\b",
    "Kubernetes": r"(?i)\bkubernetes\b|\bk8s\b", "Docker": r"(?i)\bdocker\b", "AWS": r"(?i)\baws\b",
    "GCP": r"\bGCP\b|Google Cloud", "Azure": r"(?i)\bazure\b", "Terraform": r"(?i)\bterraform\b",
    "PyTorch": r"(?i)\bpytorch\b", "TensorFlow": r"(?i)\btensorflow\b", "CUDA": r"\bCUDA\b",
    "Spark": r"\bSpark\b", "Snowflake": r"(?i)\bsnowflake\b", "dbt": r"(?i)\bdbt\b",
    "Airflow": r"(?i)\bairflow\b", "Elasticsearch/OpenSearch": r"(?i)elasticsearch|opensearch",
    "Vector DB": r"(?i)vector (database|db|search|store)|pinecone|weaviate|qdrant|pgvector|milvus",
    "LLM/GPT/Claude": r"\bLLMs?\b|\bGPT\b|OpenAI|Anthropic|\bClaude\b|Gemini|Mistral|Llama",
    "RAG": r"\bRAG\b|retrieval[- ]augmented",
    "LangChain/LlamaIndex": r"(?i)langchain|llamaindex",
    "GraphQL": r"(?i)graphql", "Flutter": r"(?i)flutter", "React Native": r"(?i)react native",
    "iOS": r"\biOS\b", "Android": r"\bAndroid\b",
    # Слово «crypto» само по себе не считается технологией: «crypto wallet» — продукт, а не стек.
    "Solidity/crypto": r"Solidity|Ethereum|Solana|(?i:blockchain)|Web3|DeFi|on-chain|(?i:smart contract)|(?<!wallet )(?i:crypto)(?! wallet)",
    "Linux": r"(?i)\blinux\b",
}

# Роли. Совпадение засчитывается только рядом со словом из названия должности (см. JOB_NOUN).
ROLES = {
    "Frontend": r"[Ff]ront-?end", "Backend": r"[Bb]ack-?end", "Full-stack": r"[Ff]ull[- ]?stack",
    "DevOps/SRE/Platform": r"DevOps|\bSRE\b|Site Reliability|[Pp]latform [Ee]ngineer|[Ii]nfra(structure)? [Ee]ngineer",
    "Data/Analytics": r"[Dd]ata (engineer|[Ss]cien|[Aa]naly)",
    "ML/AI engineer": r"\bML\b|[Mm]achine [Ll]earning|AI [Ee]ngineer|[Rr]esearch [Ee]ngineer|[Rr]esearch [Ss]cientist",
    "Mobile": r"\biOS\b|Android|[Mm]obile",
    "Embedded/Hardware": r"[Ee]mbedded (?:[Ss]oftware|[Ff]irmware|[Ss]ystems|Linux|[Ee]ngineer)|[Ff]irmware|FPGA|[Hh]ardware (?:[Ee]ngineer|[Dd]esign)|[Rr]obotic",
    "Security": r"[Ss]ecurity", "QA": r"\bQA\b|[Tt]est [Ee]ngineer",
    "Product/PM": r"[Pp]roduct [Mm]anager|\bPM\b", "Design": r"[Dd]esigner|\bUX\b|\bUI\b",
    "Sales/GTM": r"[Ss]ales|[Aa]ccount [Ee]xecutive|\bGTM\b|[Bb]usiness [Dd]evelopment",
    "Marketing": r"[Mm]arketing", "Support/CS": r"[Ss]upport|[Cc]ustomer [Ss]uccess",
}
# Слова из названия должности. Роль засчитывается, если рядом (±80 символов, в той же строке)
# есть одно из них: так отсекаются упоминания в описании продукта («machine learning», «designers»).
JOB_NOUN = re.compile(
    r"engineer|developer|designer|manager|scientist|analyst|architect|specialist|\blead\b|\bintern\b"
    r"|recruiter|representative|executive|associate|consultant|\bhead\b|\bCSM\b|\bSRE\b|\bSWE\b|\bQA\b"
    r"|\bAE\b|\bSDR\b|\bBDR\b|\bFounding\b|researcher|technician|operator|coordinator|director|officer"
    r"|advocate|strategist|evangelist",
    re.I,
)

LOCATIONS = [
    "San Francisco", "SF", "New York", "NYC", "Seattle", "Boston", "Austin", "Los Angeles",
    "Chicago", "London", "Berlin", "Munich", "Paris", "Amsterdam", "Stockholm", "Zurich",
    "Dublin", "Lisbon", "Madrid", "Tel Aviv", "Israel", "India", "Bangalore", "Singapore",
    "Tokyo", "Toronto", "Vancouver", "Canada", "Australia", "Sydney", "Brazil", "Mexico",
    "Europe", "EU", "UK", "US", "USA", "Germany", "Poland",
]

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Адреса, записанные словами: «name [at] mail.com» или «name (at) mail.com».
EMAIL_OBF_RE = re.compile(
    r"[A-Za-z0-9._%+-]+\s?\[at\]\s?[A-Za-z0-9.-]+\s?\.\s?[A-Za-z]{2,}"
    r"|[A-Za-z0-9._%+-]+\s?\(at\)\s?[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
    re.I,
)
URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")
HREF_RE = re.compile(r'href="([^"]+)"')

# Суммы: «$160K», «£115k», «€100-140k», «$130,000». Ищутся построчно.
MONEY_RE = re.compile(
    r"(?:\$|€|£|USD|EUR|GBP|CHF)\s?\d{2,3},\d{3}\b"
    r"|(?:\$|€|£|USD|EUR|GBP|CHF)\s?\d+(?:\.\d+)?\s?[kK]\b"
)
# Рядом с суммой такие слова означают не зарплату: выручка, финансирование, бонус, цена продукта.
PAY_NEG_RE = re.compile(
    r"revenue|users|customers|clients|raised|funding|valuation|bonus|signing|\bARR\b|\bMRR\b|GMV"
    r"|generated|saved|bookings|budget|pricing|\bprice|per month|/month|/mo\b|subscription|credits?"
    r"|/user|grants?|\bNYT\b",
    re.I,
)
PER_RE = re.compile(r"\d[\d,.]*\s?(?:/|per\s)\s?(?:hr|hour|yr|year|annum)\b", re.I)

SELF_START_RE = re.compile(r"(hi[,!]?\s+)?(i'm|i am|my name is)\b", re.I)
SELF_INFO_RE = re.compile(r"^\s*(location|remote|technologies|cv|resume)\s*:", re.I)
SELF_PHRASE_RE = re.compile(
    r"willing to relocate|available for (hire|work)|open to (work|opportunities)|looking for (a )?(role|job|work|opportunit)",
    re.I,
)
ONSITE_RE = re.compile(r"\bon-?site\b|in[- ]office|\bin[- ]person\b|\bin the office\b", re.I)
HYBRID_RE = re.compile(
    r"\bhybrid\b|\b\d\s*days?\b[^.\n]{0,25}\boffice\b|\boffice\b[^.\n]{0,25}\b\d\s*days?\b"
    r"|in[- ]office\s*\d|\bcome in\b",
    re.I,
)
YC_RE = re.compile(r"\bYC\b|Y ?Combinator")
AI_RE = re.compile(
    r"\b(AI|ML|LLMs?|GenAI)\b|machine learning|deep learning|neural net|computer vision|\bNLP\b"
    r"|agentic|foundation model|\bRAG\b|GPT"
)

FIELDS = [
    "hn_item_id", "posted_utc", "first_segment", "link_domain", "ats_link",
    "remote", "onsite_mentioned", "hybrid", "salary_mentioned", "ai_mentioned", "yc_mentioned",
    "location_present", "self_promo_guess", "contact_email_present",
    "tech", "roles", "locations",
]


def fetch_json(url, tries=4):
    last = None
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # сеть или таймаут: повторяем с паузой
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"не удалось скачать {url}: {last}")


def fetch_thread(story_id, workers=8):
    story = fetch_json(HN_ITEM.format(story_id))
    kids = story.get("kids", [])
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        items = list(pool.map(lambda k: fetch_json(HN_ITEM.format(k)), kids))
    return story, items


def clean_text(raw):
    text = raw.replace("<p>", "\n").replace("</p>", "\n")
    text = re.sub(r'<a [^>]*href="([^"]+)"[^>]*>.*?</a>', lambda m: " " + m.group(1) + " ",
                  text, flags=re.S)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text)


def registrable(host):
    labels = host.lower().removeprefix("www.").split(".")
    if len(labels) >= 3 and labels[-2] in {"co", "com", "net", "org", "gov", "ac"} and len(labels[-1]) == 2:
        return ".".join(labels[-3:])  # например, example.co.uk
    return ".".join(labels[-2:])


def link_domain(urls):
    for url in urls:
        if url.startswith("mailto:"):
            continue
        try:
            host = urlparse(url).hostname or ""
        except ValueError:
            continue
        if not host:
            continue
        dom = registrable(host)
        if dom in SKIP_HOSTS:
            continue
        return dom
    return ""


def role_hits(text):
    found = set()
    for line in text.split("\n"):
        for name, pat in ROLES.items():
            if name in found:
                continue
            for m in re.finditer(pat, line):
                window = line[max(0, m.start() - 80): m.end() + 80]
                if JOB_NOUN.search(window):
                    found.add(name)
                    break
    return sorted(found)


def pay_hit(text):
    for line in text.split("\n"):
        for m in MONEY_RE.finditer(line):
            window = line[max(0, m.start() - 40): m.end() + 40]
            if not PAY_NEG_RE.search(window):
                return True
        if PER_RE.search(line):
            return True
    return False


def self_promo(text):
    t = text.lstrip()
    if SELF_START_RE.match(t) or SELF_PHRASE_RE.search(text):
        return True
    return bool(SELF_INFO_RE.match(t)) and bool(re.search(r"technologies\s*:|willing to relocate", text, re.I))


def features(item):
    raw = item.get("text", "")
    text = clean_text(raw)
    urls = HREF_RE.findall(raw) + URL_RE.findall(text)
    masked = URL_RE.sub("[ссылка]", EMAIL_RE.sub("[email]", text))
    lines = [line.strip() for line in masked.split("\n") if line.strip()]
    first = lines[0] if lines else ""
    segment = re.split(r"\s*\|\s*", first)[0][:80]
    dom = link_domain(urls)

    remote = bool(re.search(r"\bremote\b", text, re.I))
    onsite = bool(ONSITE_RE.search(text))
    hybrid = bool(HYBRID_RE.search(text))
    locs = [loc for loc in LOCATIONS if re.search(r"\b" + re.escape(loc) + r"\b", text)]

    return {
        "hn_item_id": item["id"],
        "posted_utc": datetime.fromtimestamp(item["time"], tz=timezone.utc).strftime("%Y-%m-%d"),
        "first_segment": segment,
        "link_domain": dom,
        "ats_link": dom in ATS_HOSTS,
        "remote": remote,
        "onsite_mentioned": onsite,
        "hybrid": hybrid,
        "salary_mentioned": pay_hit(text),
        "ai_mentioned": bool(AI_RE.search(text)),
        "yc_mentioned": bool(YC_RE.search(text)),
        "location_present": bool(locs) or remote or onsite or hybrid,
        "self_promo_guess": self_promo(text),
        "contact_email_present": bool(EMAIL_RE.search(text) or EMAIL_OBF_RE.search(text)),
        "tech": ";".join(k for k, pat in TECH.items() if re.search(pat, text)),
        "roles": ";".join(role_hits(text)),
        "locations": ";".join(locs),
    }


def is_usable(item):
    return bool(item) and not item.get("deleted") and not item.get("dead") and bool(item.get("text"))


def is_true(value):
    # В CSV булевы значения читаются как строки "True"/"False", а "False" тоже истинно в Python.
    return value is True or value == "True"


def company_domains(rows):
    return {r["link_domain"] for r in rows
            if r["link_domain"] and not is_true(r["ats_link"]) and r["link_domain"] not in NEUTRAL_HOSTS}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--story", type=int, required=True, help="id темы, например 50338728")
    ap.add_argument("--out", required=True, help="куда записать CSV")
    ap.add_argument("--prev", help="CSV предыдущего месяца: посчитать повторяющиеся фирмы")
    args = ap.parse_args()

    story, items = fetch_thread(args.story)
    status = collections.Counter()
    rows = []
    for item in items:
        if not is_usable(item):
            status["недоступен (deleted/dead)"] += 1
            continue
        status["доступен"] += 1
        rows.append(features(item))

    with open(args.out, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    n = len(rows)
    print(f"Тема: {story.get('title')} (id {args.story})")
    print(f"Комментариев верхнего уровня: {len(items)}; статусы: {dict(status)}")
    if n == 0:
        sys.exit("Нет доступных комментариев")

    def share(key):
        c = sum(1 for r in rows if r[key] is True or r[key] == "True")
        return f"{c}/{n} = {100 * c / n:.0f}%"

    for key in ["remote", "onsite_mentioned", "hybrid", "salary_mentioned", "ai_mentioned",
                "yc_mentioned", "ats_link", "location_present", "self_promo_guess",
                "contact_email_present"]:
        print(f"  {key:22s} {share(key)}")
    print("  топ технологий:", collections.Counter(
        t for r in rows for t in r["tech"].split(";") if t).most_common(12))
    print("  топ ролей:", collections.Counter(
        t for r in rows for t in r["roles"].split(";") if t).most_common(10))

    if args.prev:
        with open(args.prev, encoding="utf-8") as fh:
            prev_rows = list(csv.DictReader(fh))
        both = company_domains(rows) & company_domains(prev_rows)
        print(f"  фирм (домены без ATS и общих сервисов) в этом и прошлом выпуске: {len(both)}")
    print(f"Записано строк: {n} -> {args.out}")


if __name__ == "__main__":
    main()
