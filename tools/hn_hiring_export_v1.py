#!/usr/bin/env python3
"""Выгрузка комментариев темы «Ask HN: Who is hiring?» в CSV.

Пример:
    python3 tools/hn_hiring_export.py --story 50338728 --out data/hn-hiring-2026-11.csv
    python3 tools/hn_hiring_export.py --story 50338728 --out data/hn-hiring-2026-11.csv \
        --prev data/hn-hiring-2026-10.csv

Скрипт читает публичное API Hacker News (https://github.com/HackerNews/API)
и для каждого комментария записывает только производные признаки: домен ссылки,
формат работы, упоминания зарплаты, ИИ, технологий и ролей.

В CSV НЕ попадают: текст комментариев, адреса электронной почты и полные ссылки.
Флаг contact_email_present лишь отмечает, что контакт есть в посте.

Все признаки определяются регулярными выражениями, то есть это оценка, а не
точная разметка. Погрешность проверяйте на выборке перед выводами.
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

TECH = {
    "Python": r"\bPython\b", "TypeScript": r"\bTypeScript\b", "JavaScript": r"\bJavaScript\b",
    "React": r"\bReact\b", "Next.js": r"Next\.?js", "Node.js": r"\bNode(\.js)?\b",
    "Golang": r"\bGolang\b", "Rust": r"\bRust\b", "Java": r"\bJava\b", "Kotlin": r"\bKotlin\b",
    "Scala": r"\bScala\b", "C++": r"C\+\+", "C#/.NET": r"C#|\.NET\b",
    "Ruby/Rails": r"\bRuby\b|\bRails\b", "PHP": r"\bPHP\b", "Elixir": r"\bElixir\b",
    "Swift": r"\bSwift\b", "Clojure": r"\bClojure\b", "PostgreSQL": r"\bPostgres",
    "MySQL": r"\bMySQL\b", "MongoDB": r"\bMongo", "Redis": r"\bRedis\b", "Kafka": r"\bKafka\b",
    "Kubernetes": r"\bKubernetes\b|\bK8s\b", "Docker": r"\bDocker\b", "AWS": r"\bAWS\b",
    "GCP": r"\bGCP\b|Google Cloud", "Azure": r"\bAzure\b", "Terraform": r"\bTerraform\b",
    "PyTorch": r"\bPyTorch\b", "TensorFlow": r"\bTensorFlow\b", "CUDA": r"\bCUDA\b",
    "Spark": r"\bSpark\b", "Snowflake": r"\bSnowflake\b", "dbt": r"\bdbt\b",
    "Airflow": r"\bAirflow\b", "Elasticsearch/OpenSearch": r"Elasticsearch|OpenSearch",
    "Vector DB": r"[Vv]ector (database|DB|search|store)|Pinecone|Weaviate|Qdrant|pgvector|Milvus",
    "LLM/GPT/Claude": r"\bLLMs?\b|\bGPT\b|OpenAI|Anthropic|\bClaude\b|Gemini|Mistral|Llama",
    "RAG": r"\bRAG\b|retrieval[- ]augmented", "LangChain/LlamaIndex": r"LangChain|LlamaIndex",
    "GraphQL": r"GraphQL", "Flutter": r"Flutter", "React Native": r"React Native",
    "iOS": r"\biOS\b", "Android": r"\bAndroid\b",
    "Solidity/crypto": r"Solidity|Ethereum|Solana|blockchain|[Cc]rypto|Web3", "Linux": r"\bLinux\b",
}

ROLES = {
    "Frontend": r"[Ff]ront-?end", "Backend": r"[Bb]ack-?end", "Full-stack": r"[Ff]ull[- ]?stack",
    "DevOps/SRE/Platform": r"DevOps|\bSRE\b|Site Reliability|[Pp]latform [Ee]ngineer|[Ii]nfra(structure)? [Ee]ngineer",
    "Data/Analytics": r"[Dd]ata (engineer|scien|analy)",
    "ML/AI engineer": r"\bML\b|[Mm]achine [Ll]earning|AI [Ee]ngineer|[Rr]esearch [Ee]ngineer|[Rr]esearch [Ss]cientist",
    "Mobile": r"\biOS\b|Android|[Mm]obile", "Embedded/Hardware": r"[Ee]mbedded|[Hh]ardware|FPGA|[Rr]obotic",
    "Security": r"[Ss]ecurity", "QA": r"\bQA\b|[Tt]est [Ee]ngineer",
    "Product/PM": r"[Pp]roduct [Mm]anager|\bPM\b", "Design": r"[Dd]esigner|\bUX\b|\bUI\b",
    "Sales/GTM": r"[Ss]ales|[Aa]ccount [Ee]xecutive|\bGTM\b|[Bb]usiness [Dd]evelopment",
    "Marketing": r"[Mm]arketing", "Support/CS": r"[Ss]upport|[Cc]ustomer [Ss]uccess",
}

LOCATIONS = [
    "San Francisco", "SF", "New York", "NYC", "Seattle", "Boston", "Austin", "Los Angeles",
    "Chicago", "London", "Berlin", "Munich", "Paris", "Amsterdam", "Stockholm", "Zurich",
    "Dublin", "Lisbon", "Madrid", "Tel Aviv", "Israel", "India", "Bangalore", "Singapore",
    "Tokyo", "Toronto", "Vancouver", "Canada", "Australia", "Sydney", "Brazil", "Mexico",
    "Europe", "EU", "UK", "US", "USA", "Germany", "Poland",
]

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")
HREF_RE = re.compile(r'href="([^"]+)"')
SELF_PROMO_RE = re.compile(r"(hi[,!]?\s+)?(i'm|i am|my name is)\b", re.I)

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
    onsite = bool(re.search(r"\bon-?site\b|in[- ]office", text, re.I))
    hybrid = bool(re.search(r"\bhybrid\b", text, re.I))
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
        # Суммы вида «$42M» или «€650M+» (финансирование) сюда не попадают: нужны k или разряды.
        "salary_mentioned": bool(re.search(
            r"(\$|€|£|USD|EUR|GBP|CHF)\s?\d{2,3},\d{3}|(\$|€|£|USD|EUR|GBP|CHF)\s?\d[\d,.]*\s?[kK]\b"
            r"|\bsalary\b|\bcompensation\b|per (year|hour)|/yr|/year|/hr|\bbase\b",
            text, re.I)),
        "ai_mentioned": bool(re.search(
            r"\b(AI|ML|LLMs?|GenAI)\b|machine learning|deep learning|neural net|computer vision|\bNLP\b|agentic|foundation model|\bRAG\b|GPT",
            text)),
        "yc_mentioned": bool(re.search(r"\bYC\s?[SWFX]\d{2}\b|\bYC P\d{2}\b|Y ?Combinator", text)),
        "location_present": bool(locs) or remote or onsite or hybrid,
        "self_promo_guess": bool(SELF_PROMO_RE.match(text.lstrip())),
        "contact_email_present": bool(EMAIL_RE.search(text)),
        "tech": ";".join(k for k, pat in TECH.items() if re.search(pat, text)),
        "roles": ";".join(k for k, pat in ROLES.items() if re.search(pat, text)),
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
        c = sum(1 for r in rows if r[key])
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
