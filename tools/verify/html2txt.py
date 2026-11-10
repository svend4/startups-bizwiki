"""Convert a downloaded HTML page to plain text. Usage: html2txt.py <in.html> <out.txt>

Input is untrusted web content: this script only reads it as text and never executes it.
"""
import html
import re
import sys

src, dst = sys.argv[1], sys.argv[2]
with open(src, encoding="utf-8", errors="ignore") as fh:
    raw = fh.read()
raw = re.sub(r"(?is)<(script|style|noscript|svg|template)[^>]*>.*?</\1>", " ", raw)
raw = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h[1-6]>|</div>|</section>|</tr>", "\n", raw)
text = re.sub(r"<[^>]+>", " ", raw)
text = html.unescape(text)
text = re.sub(r"[ \t\r\f\v]+", " ", text)
text = re.sub(r"\n\s*\n+", "\n", text)
with open(dst, "w", encoding="utf-8") as fh:
    fh.write(text)
print(dst, len(text), "chars")
