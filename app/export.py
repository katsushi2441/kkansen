"""画面とデータを、前もって静的なファイルに書き出す（heteml などのレンタルサーバーだけで動かすため）。

  .venv/bin/python -m app.export [出力先]      # 既定 outputs/static

- 動いている FastAPI（既定 http://127.0.0.1:18382）から全URLぶん画面を取って、ファイルにする。病名・地域・区の切り替え（?d= ?area= ?ward=）も組み合わせごとに書き出す。
- 地図が読むJSON（/api/pref・/api/nagoya・/api/closures）も同じく書き出す。
- manifest.json に「URL（パス＋決まった引数）→ ファイル名・種類・ハッシュ」を書く。公開側の php/kkansen_static.php がこれを引く。
- 住所から都道府県・区を調べる /api/lookup は国土地理院を呼ぶだけなので、PHP 側で動かす（書き出さない）。
- MCP（/mcp）は当社のサーバーに残す。止まっていたら PHP 側がすぐに「使えません」と返す。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys

import urllib.error
import urllib.parse
import urllib.request

from . import diseases as D

BASE = os.environ.get("KKANSEN_LOCAL", "http://127.0.0.1:18382")

# 引数のうち、画面の中身を変えるものだけ（ref= などの計測用は無視する）。PHP 側も同じ表を持つ
PARAMS = {"/map/": ["area", "d"], "/nagoya/": ["d"], "/gakkyu/": ["ward"],
          "/api/pref": ["d"], "/api/nagoya": ["d"], "/api/closures": ["ward"]}


def key_of(path: str, q: dict[str, str]) -> str:
    keep = PARAMS.get(path, [])
    qs = "&".join(f"{k}={q[k]}" for k in keep if k in q and q[k] != "")
    return path + ("?" + qs if qs else "")


def urls() -> list[tuple[str, dict[str, str]]]:
    u: list[tuple[str, dict[str, str]]] = [("/", {}), ("/zensu/", {}), ("/about", {}), ("/robots.txt", {}), ("/sitemap.xml", {}), ("/llms.txt", {}),
                                            ("/map/", {}), ("/nagoya/", {}), ("/gakkyu/", {}), ("/api/closures", {})]
    for s in D.ORDER:
        u += [(f"/d/{s}/", {}), ("/map/", {"d": s, "area": "japan"}), ("/map/", {"d": s, "area": "nagoya"}), ("/map/", {"d": s}),
              ("/nagoya/", {"d": s}), ("/api/pref", {"d": s}), ("/api/nagoya", {"d": s})]
    for slug in D.PREF_SLUG.values():
        u.append((f"/p/{slug}/", {}))
    for w, ws in D.WARD_SLUG.items():
        u += [(f"/nagoya/{ws}/", {}), ("/gakkyu/", {"ward": w}), ("/api/closures", {"ward": w})]
    for f in os.listdir(os.path.join(os.path.dirname(__file__), "static")):
        u.append((f"/static/{f}", {}))
    return u


def main(out: str) -> None:
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(out)
    def get(path: str, q: dict[str, str]):
        url = BASE + urllib.parse.quote(path) + ("?" + urllib.parse.urlencode(q) if q else "")
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"X-Forwarded-Proto": "https", "X-Forwarded-Host": "kurage.exbridge.jp"}), timeout=60) as r:
                return r.status, r.read(), r.headers.get("content-type", "application/octet-stream")
        except urllib.error.HTTPError as e:
            return e.code, e.read(), e.headers.get("content-type", "text/html; charset=utf-8")
    manifest: dict[str, dict] = {}
    seen = set()
    for path, q in urls():
        key = key_of(path, q)
        if key in seen:
            continue
        seen.add(key)
        code, body, ctype = get(path, q)
        if code != 200:
            print("  書き出せない", code, key)
            continue
        ext = os.path.splitext(path)[1] or (".json" if "json" in ctype else ".xml" if "xml" in ctype else ".txt" if "text/plain" in ctype else ".html")
        h = hashlib.sha1(body).hexdigest()
        name = hashlib.sha1(key.encode()).hexdigest()[:16] + ext
        open(os.path.join(out, name), "wb").write(body)
        manifest[key] = {"f": name, "t": ctype, "h": h}
    _, nf, _ = get("/__not_found__/", {})
    open(os.path.join(out, "404.html"), "wb").write(nf)
    manifest["__404__"] = {"f": "404.html", "t": "text/html; charset=utf-8", "h": hashlib.sha1(nf).hexdigest()}
    json.dump({"params": PARAMS, "ward_slug": D.WARD_SLUG, "files": manifest}, open(os.path.join(out, "manifest.json"), "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))
    print(f"書き出し {len(manifest)}件 → {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "outputs", "static"))
