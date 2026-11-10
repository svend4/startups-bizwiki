"""Print the text of a Hacker News item (JSON from the public API) with e-mail addresses masked.

Usage: hn_item_text.py <item.json> <out.txt>
Input is untrusted user content: it is read as text only.
"""
import html
import json
import re
import sys

src, dst = sys.argv[1], sys.argv[2]
with open(src, encoding="utf-8") as fh:
    item = json.load(fh)
raw = item.get("text") or ""
text = raw.replace("<p>", "\n").replace("</p>", "\n")
text = re.sub(r'<a [^>]*href="([^"]+)"[^>]*>.*?</a>', lambda m: " " + m.group(1) + " ", text, flags=re.S)
text = re.sub(r"<[^>]+>", "", text)
text = html.unescape(text)
text = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[email]", text)
title = item.get("title") or ""
out = (title + "\n" if title else "") + text
with open(dst, "w", encoding="utf-8") as fh:
    fh.write(out)
print(dst, len(out), "chars")
