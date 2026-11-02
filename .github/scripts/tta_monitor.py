"""沖縄県卓球協会 (https://tta.okinawa/) の更新監視スクリプト。

前回スナップショット (STATE_DIR) と比較し、差分があれば Markdown レポートを
REPORT_PATH に書き出す。初回はスナップショット保存のみ。標準ライブラリのみ使用。
"""
import html
import json
import os
import re
import sys
import urllib.request
from collections import Counter
from html.parser import HTMLParser
from urllib.parse import urljoin, urldefrag

PAGES = [p.strip() for p in os.environ.get("TTA_PAGES", "https://tta.okinawa/").split(",") if p.strip()]
STATE_DIR = os.environ.get("STATE_DIR", "state")
REPORT_PATH = os.environ.get("REPORT_PATH", "report.md")
UA = "Mozilla/5.0 (compatible; tta-update-monitor/1.0; +https://github.com/shin0303/u-mac-website)"


class Extractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "template"}
    BLOCK = {"p", "div", "li", "tr", "br", "h1", "h2", "h3", "h4", "h5", "h6",
             "section", "article", "header", "footer", "dt", "dd", "td", "th", "time"}

    def __init__(self, base):
        super().__init__(convert_charrefs=True)
        self.base = base
        self.skip = 0
        self.buf = []
        self.links = []
        self._a = None

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        if tag in self.BLOCK:
            self.buf.append("\n")
        if tag == "a":
            href = dict(attrs).get("href")
            if href and not href.startswith(("javascript:", "mailto:", "tel:", "#")):
                self._a = [urldefrag(urljoin(self.base, href))[0], []]

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        if tag in self.BLOCK:
            self.buf.append("\n")
        if tag == "a" and self._a:
            text = " ".join("".join(self._a[1]).split())
            self.links.append({"url": self._a[0], "text": text})
            self._a = None

    def handle_data(self, data):
        if self.skip:
            return
        self.buf.append(data)
        if self._a:
            self._a[1].append(data)

    def lines(self):
        out = []
        for line in "".join(self.buf).split("\n"):
            line = " ".join(line.split())
            if line:
                out.append(line)
        return out


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ja"})
    with urllib.request.urlopen(req, timeout=60) as res:
        raw = res.read()
        charset = res.headers.get_content_charset()
    if not charset:
        m = re.search(rb'charset=["\']?([\w-]+)', raw[:4096])
        charset = m.group(1).decode() if m else "utf-8"
    return raw.decode(charset, errors="replace")


def slug(url):
    return re.sub(r"[^A-Za-z0-9]+", "_", url).strip("_")[:120]


def main():
    os.makedirs(STATE_DIR, exist_ok=True)
    sections = []
    for url in PAGES:
        page = fetch(url)
        ex = Extractor(url)
        ex.feed(page)
        snap = {"url": url, "lines": ex.lines(),
                "links": sorted({(l["url"], l["text"]) for l in ex.links})}
        path = os.path.join(STATE_DIR, slug(url) + ".json")
        prev = None
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                prev = json.load(f)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False, indent=1)
        print(f"{url}: {len(snap['lines'])} lines, {len(snap['links'])} links")
        if prev is None:
            print("  初回スナップショットを保存しました（通知なし）")
            continue

        old_links = {tuple(l) for l in prev["links"]}
        new_links = [l for l in snap["links"] if tuple(l) not in old_links]
        # スポンサー欄などは表示順がランダムに入れ替わるため、順序は無視して
        # 「増えた行」「消えた行」だけを比較する
        old_c, new_c = Counter(prev["lines"]), Counter(snap["lines"])
        added, removed = new_c - old_c, old_c - new_c
        diff = []
        for line in snap["lines"]:
            if added[line] > 0:
                diff.append("+ " + line)
                added[line] -= 1
        for line in prev["lines"]:
            if removed[line] > 0:
                diff.append("- " + line)
                removed[line] -= 1
        if not new_links and not diff:
            print("  変化なし")
            continue

        part = [f"## {url}"]
        if new_links:
            part.append("### 新しく出現したリンク")
            for u, t in new_links[:50]:
                part.append(f"- [{html.escape(t) or u}]({u})")
        if diff:
            part.append("### 本文の差分（+ 追加 / - 削除）")
            body = "\n".join(diff)
            if len(body) > 50000:
                body = body[:50000] + "\n…（長いため省略）"
            part.append("```diff\n" + body + "\n```")
        sections.append("\n\n".join(part))
        print(f"  変化あり: 新リンク {len(new_links)} 件, 差分 {len(diff)} 行")

    if sections:
        with open(REPORT_PATH, "w", encoding="utf-8") as f:
            f.write("沖縄県卓球協会のホームページに更新を検知しました。\n\n" + "\n\n".join(sections))


if __name__ == "__main__":
    sys.exit(main())
