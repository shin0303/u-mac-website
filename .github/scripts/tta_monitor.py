"""沖縄県卓球協会 (https://tta.okinawa/) の更新監視スクリプト。

前回スナップショット (STATE_DIR) と比較し、差分があれば Markdown レポートを
REPORT_PATH に書き出す。初回はスナップショット保存のみ。標準ライブラリのみ使用。
"""
import json
import os
import re
import sys
import urllib.request
from html.parser import HTMLParser
from urllib.parse import urljoin, urldefrag, urlparse

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


def internal(links):
    """協会サイト内へのリンクで、テキストがあるものだけを返す（重複除去・順序維持）。"""
    seen, out = set(), []
    for u, t in links:
        host = urlparse(u).hostname or ""
        if (host == "tta.okinawa" or host.endswith(".tta.okinawa")) and t and t != ".":
            key = (u, t)
            if key not in seen:
                seen.add(key)
                out.append([u, t])
    return out


def slug(url):
    return re.sub(r"[^A-Za-z0-9]+", "_", url).strip("_")[:120]


def main():
    os.makedirs(STATE_DIR, exist_ok=True)
    sections = []
    failed = 0
    for url in PAGES:
        try:
            page = fetch(url)
        except Exception as e:  # 1ページの失敗で全体を止めない
            print(f"{url}: 取得失敗 {e}")
            failed += 1
            continue
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

        # 判定対象は「協会サイト内へのリンク（日付・タイトル付き）」のみ。
        # スポンサー欄は表示企業や順序が毎回ランダムに変わるため本文比較はしない。
        old_items = {tuple(l) for l in internal(prev["links"])}
        new_items = {tuple(l) for l in internal(snap["links"])}
        added = [l for l in internal(snap["links"]) if tuple(l) not in old_items]
        removed = [l for l in internal(prev["links"]) if tuple(l) not in new_items]
        if not added and not removed:
            print("  変化なし")
            continue

        part = [f"## {url}"]
        if added:
            part.append("### 新しい／変更された記事・ページ")
            part += [f"- [{t}]({u})" for u, t in added[:100]]
        if removed:
            part.append("### 消えた記事・ページ")
            part += [f"- ~~{t}~~ ({u})" for u, t in removed[:100]]
        sections.append("\n\n".join(part))
        print(f"  変化あり: 追加 {len(added)} 件, 削除 {len(removed)} 件")

    if sections:
        with open(REPORT_PATH, "w", encoding="utf-8") as f:
            f.write("沖縄県卓球協会のホームページに更新を検知しました。\n\n" + "\n\n".join(sections))
    if failed == len(PAGES):
        return 1


if __name__ == "__main__":
    sys.exit(main())
