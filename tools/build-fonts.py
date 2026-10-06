#!/usr/bin/env python3
"""Rebuild the self-hosted font subsets in fonts/.

The page only ever shows ~1,150 distinct characters. Google's full Noto CJK
webfonts cost ~3 MB over ~46 requests; subsetting those characters out of the
upstream variable fonts costs ~460 KB over 3 requests, same origin.

Run this whenever index.html gains characters that were not in it before —
otherwise those characters quietly fall back to a system font.

    pip install fonttools brotli
    python tools/build-fonts.py

Sources come from github.com/google/fonts (all three are OFL; the licences are
kept next to the subsets in fonts/). They are 12-17 MB each, so set
FONT_SRC_DIR to a directory holding them to skip the download on a rerun.
"""
import html.parser
import os
import pathlib
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
FONTS = ROOT / "fonts"
BASE = "https://raw.githubusercontent.com/google/fonts/main/ofl"

# family dir, upstream variable file, output name, weight range, which charset
FAMILIES = [
    ("notosanstc",    "NotoSansTC[wght].ttf",    "busan-sans.woff2",  (400, 700), "all"),
    ("notoseriftc",   "NotoSerifTC[wght].ttf",   "busan-serif.woff2", (700, 900), "headings"),
    ("jetbrainsmono", "JetBrainsMono[wght].ttf", "busan-mono.woff2",  (400, 600), "latin"),
]

# insurance beyond whatever the page happens to contain today
EXTRA = "".join(chr(c) for c in range(0x20, 0x7F))
EXTRA += "‧—–…「」『』（）、。，：；！？〈〉《》·　×→←↑↓℃₩％±"


class Headings(html.parser.HTMLParser):
    """Text inside h1-h6 and the brand wordmark — everything --serif renders.

    If index.html ever applies var(--serif) somewhere else, add it here or those
    characters will fall back to a system serif.
    """

    TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.text = []

    def handle_starttag(self, tag, attrs):
        classes = dict(attrs).get("class", "").split()
        if tag in self.TAGS or "bt" in classes:
            self.depth += 1
        elif self.depth:
            self.depth += 1

    def handle_endtag(self, tag):
        if self.depth:
            self.depth -= 1

    def handle_data(self, data):
        if self.depth:
            self.text.append(data)


def charsets():
    src = (ROOT / "index.html").read_text(encoding="utf-8")
    everything = set(src)
    h = Headings()
    h.feed(src)
    return {
        # the body font has to cover every character on the page
        "all": everything,
        # the display serif only ever sets headings
        "headings": set("".join(h.text)),
        # JetBrains Mono ships no CJK at all, so CJK in it would be dead weight
        "latin": {c for c in everything if ord(c) < 0x2E80},
    }


def pack(chars):
    return "".join(sorted((chars | set(EXTRA)) - set("\r\n\t")))


def fetch(url, dest):
    name = url.rsplit("/", 1)[-1].replace("%5B", "[").replace("%5D", "]")
    cache = os.environ.get("FONT_SRC_DIR")
    if cache and name.endswith(".ttf") and (pathlib.Path(cache) / name).exists():
        dest.write_bytes((pathlib.Path(cache) / name).read_bytes())
        print("  cached", name, flush=True)
        return
    print("  fetching", name, flush=True)
    with urllib.request.urlopen(url, timeout=120) as r, open(dest, "wb") as f:
        while True:
            chunk = r.read(1 << 18)
            if not chunk:
                break
            f.write(chunk)
    print("  got %s (%d KB)" % (name, dest.stat().st_size // 1024), flush=True)


def run(*args):
    subprocess.run([sys.executable, "-m", *args], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    sets = charsets()
    FONTS.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = pathlib.Path(tmpdir)
        for folder, src, out, (lo, hi), which in FAMILIES:
            text = pack(sets[which])
            chars = tmp / ("charset-%s.txt" % which)
            chars.write_text(text, encoding="utf-8")
            print("%s  (%s: %d glyphs)" % (out, which, len(text)), flush=True)
            full = tmp / src.replace("[wght]", "")
            fetch("%s/%s/%s" % (BASE, folder, urllib.parse.quote(src)), full)
            fetch("%s/%s/OFL.txt" % (BASE, folder), FONTS / ("OFL-%s.txt" % full.stem))
            trimmed = tmp / ("%s-range.ttf" % full.stem)
            run("fontTools.varLib.instancer", str(full),
                "wght=%d:%d" % (lo, hi), "-o", str(trimmed))
            run("fontTools.subset", str(trimmed),
                "--text-file=%s" % chars, "--flavor=woff2",
                "--layout-features=*", "--output-file=%s" % (FONTS / out))
            print("  ->", (FONTS / out).stat().st_size // 1024, "KB", flush=True)


if __name__ == "__main__":
    main()
