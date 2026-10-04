"""Kurage 感染症マップ（kkansen）— 全国の都道府県と名古屋市の区の、感染症の流行状況を地図で。

公開: https://kurage.exbridge.jp/kkansen.php/（heteml の透過プロキシ → このサーバー :18382）
数字は公式の値をそのまま出す。警報・注意報の基準値を超えたかは diseases.py の基準値で判定し、「目安」として示す。
受診すべきかどうかのような判断は書かない。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import urllib.parse
import urllib.request

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import diseases as D
from . import store

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = "Kurage 感染症マップ"
PUBLIC = os.environ.get("KKANSEN_PUBLIC", "https://kurage.exbridge.jp/kkansen.php")
BUY = os.environ.get("KKANSEN_BUY", "")
PV = os.environ.get("KKANSEN_PV", "")          # 紹介動画（mp4）の URL。空ならトップに出さない
PV_POSTER = os.environ.get("KKANSEN_PV_POSTER", "")
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")
T = Jinja2Templates(directory=os.path.join(HERE, "templates"))


def root(request: Request) -> str:
    """プロキシ配下でも壊れない相対の起点（/kkansen.php/ の下で深さに応じて ../ を重ねる）"""
    path = request.url.path
    depth = path.count("/") - 1
    return "./" if depth <= 0 else "../" * depth


def fmt(v, nd=2):
    if v is None:
        return "—"
    if isinstance(v, float) and v.is_integer() and nd == 0:
        return f"{int(v):,}"
    return f"{v:,.{nd}f}" if nd else f"{int(round(v)):,}"


T.env.filters["n0"] = lambda v: fmt(v, 0)
T.env.filters["n2"] = lambda v: fmt(v, 2)
T.env.globals.update(SITE=SITE, D=D, level_label=D.level_label)


def ctx(request: Request, **kw) -> dict:
    c = store.db()
    idwr = store.latest(c, "idwr")
    ngy = store.latest(c, "nagoya")
    base = {"request": request, "root": root(request), "public": PUBLIC, "buy": BUY, "pv": PV, "pv_poster": PV_POSTER, "idwr": idwr, "ngy": ngy,
            "refreshed": store.meta(c, "refreshed"), "canonical": PUBLIC + request.url.path.rstrip("/").replace("//", "/") + ("/" if request.url.path.endswith("/") else "")}
    c.close()
    base.update(kw)
    return base


def xshare(text: str, path: str, slot: str, tags: list[str] | None = None) -> str:
    """X の投稿画面を開く URL。共有されたリンクには ref=x-share-<slot> を付けて、Xからの戻りを数えられるようにする"""
    url = f"{PUBLIC}{path}" + ("&" if "?" in path else "?") + f"ref=x-share-{slot}"
    q = {"text": text, "url": url}
    if tags:
        q["hashtags"] = ",".join(t.lstrip("#") for t in tags)
    return "https://x.com/intent/post?" + urllib.parse.urlencode(q)


def lvtxt(lv: str) -> str:
    return f"（{D.level_label(lv)}の目安）" if lv else ""


def svg_series(series: list[tuple[int, float | None]], lines: list[tuple[float, str, str]] | None = None, w: int = 640, h: int = 200, unit: str = "定点当たり") -> str:
    """週ごとの推移の折れ線（外部ライブラリなしの SVG）"""
    pts = [(x, y) for x, y in series if y is not None]
    if len(pts) < 2:
        return ""
    xs = [p[0] for p in pts]
    ymax = max([p[1] for p in pts] + [l[0] for l in (lines or [])] + [1])
    ymax *= 1.1
    L, R, Tp, B = 40, 12, 12, 26
    def X(x): return L + (x - min(xs)) / max(1, (max(xs) - min(xs))) * (w - L - R)
    def Y(y): return Tp + (1 - y / ymax) * (h - Tp - B)
    path = " ".join(f"{'M' if i == 0 else 'L'}{X(x):.1f},{Y(y):.1f}" for i, (x, y) in enumerate(pts))
    g = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="週ごとの推移（{unit}）" style="width:100%;height:auto;max-width:{w}px">']
    for k in range(5):
        yv = ymax * k / 4
        g.append(f'<line x1="{L}" x2="{w - R}" y1="{Y(yv):.1f}" y2="{Y(yv):.1f}" stroke="#e3eaee"/><text x="{L - 6}" y="{Y(yv) + 4:.1f}" font-size="11" text-anchor="end" fill="#5d6b7a">{yv:.0f}</text>')
    for v, label, color in lines or []:
        g.append(f'<line x1="{L}" x2="{w - R}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="{color}" stroke-dasharray="5 4"/><text x="{w - R}" y="{Y(v) - 4:.1f}" font-size="11" text-anchor="end" fill="{color}">{label} {v:g}</text>')
    step = max(1, (max(xs) - min(xs)) // 8)
    for x in range(min(xs), max(xs) + 1, step):
        g.append(f'<text x="{X(x):.1f}" y="{h - 8}" font-size="11" text-anchor="middle" fill="#5d6b7a">{x}週</text>')
    g.append(f'<path d="{path}" fill="none" stroke="#0a8f85" stroke-width="2.5"/>')
    lx, ly = pts[-1]
    g.append(f'<circle cx="{X(lx):.1f}" cy="{Y(ly):.1f}" r="4" fill="#0a8f85"/><text x="{X(lx) - 6:.1f}" y="{Y(ly) - 8:.1f}" font-size="12" font-weight="700" text-anchor="end" fill="#12202f">{ly:.2f}</text>')
    g.append("</svg>")
    return "".join(g)


def threshold_lines(slug: str) -> list[tuple[float, str, str]]:
    d = D.BY_SLUG[slug]
    out = []
    if d["warn_on"]:
        out.append((d["warn_on"], "警報", "#c0392b"))
    if d["advisory"]:
        out.append((d["advisory"], "注意報", "#b7791f"))
    return out


# ---------------- 画面 ----------------

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    c = store.db()
    w = store.latest(c, "idwr")
    rank = store.ranking(c, w["year"], w["week"]) if w else []
    nw = store.latest(c, "nagoya")
    wards = store.ward_map(c, "influenza", nw["year"], nw["week"]) if nw else {}
    week_cl = store.closures(c, days=7)
    season_cl = store.closures(c)
    c.close()
    lines = [f"・{r['name'].split('（')[0]} {fmt(r['per'])}" + (f"（警報レベルの目安 {r['warn']}都道府県）" if r["warn"] else (f"（注意報レベルの目安 {r['adv']}都道府県）" if r["adv"] else "")) for r in rank[:3]]
    share = xshare(f"いま流行っている感染症（全国・{w['year']}年{w['week']}週・定点当たり）\n" + "\n".join(lines), "/", "home", ["感染症", "インフルエンザ"]) if w else ""
    return T.TemplateResponse(request, "index.html", ctx(request, nav="home", rank=rank, wards=wards, week_cl=week_cl, season_cl=season_cl, share=share))


@app.get("/map/", response_class=HTMLResponse)
def map_page(request: Request, d: str = "influenza", area: str = "japan"):
    if d not in D.BY_SLUG:
        d = "influenza"
    return T.TemplateResponse(request, "map.html", ctx(request, nav="map", dis=D.BY_SLUG[d], area=area))


@app.get("/d/{slug}/", response_class=HTMLResponse)
def disease_page(request: Request, slug: str):
    if slug not in D.BY_SLUG:
        raise HTTPException(404)
    c = store.db()
    w = store.latest(c, "idwr")
    m = store.pref_map(c, slug, w["year"], w["week"]) if w else {}
    series = store.pref_series(c, slug, "総数", w["year"]) if w else []
    nw = store.latest(c, "nagoya")
    wm = store.ward_map(c, slug, nw["year"], nw["week"]) if nw else {}
    c.close()
    prefs = sorted(((p, v) for p, v in m.items() if p != "総数"), key=lambda kv: -(kv[1]["per"] or 0))
    t = m.get("総数") or {}
    top = "、".join(f"{p} {fmt(v['per'])}" for p, v in prefs[:3])
    share = xshare(f"【{D.BY_SLUG[slug]['name']}】全国の定点当たり {fmt(t.get('per'))}（前週 {fmt(t.get('prev'))}・{w['year']}年{w['week']}週）。多いのは {top}", f"/d/{slug}/", f"d-{slug}", [D.BY_SLUG[slug]['name'].split('（')[0].replace('（', ''), "感染症"]) if w else ""
    return T.TemplateResponse(request, "disease.html", ctx(request, nav="d", dis=D.BY_SLUG[slug], m=m, prefs=prefs, wm=wm, share=share,
                                                  chart=svg_series(series, threshold_lines(slug))))


@app.get("/p/{code}/", response_class=HTMLResponse)
def pref_page(request: Request, code: str):
    pref = next((p for p, s in D.PREF_SLUG.items() if s == code), None)
    if not pref:
        raise HTTPException(404)
    c = store.db()
    w = store.latest(c, "idwr")
    rows = []
    for slug in D.ORDER:
        m = store.pref_map(c, slug, w["year"], w["week"])
        if pref in m:
            rows.append({**D.BY_SLUG[slug], **m[pref], "nat": m.get("総数", {}).get("per")})
    zz = store.zensu(c, w["year"], w["week"], pref)
    flu = store.pref_series(c, "influenza", pref, w["year"])
    cov = store.pref_series(c, "covid19", pref, w["year"])
    c.close()
    def _rk(r):
        rel = (r["per"] or 0) / (r["nat"] or 1)
        if (r["per"] or 0) < 0.3:
            rel *= 0.1   # 髄膜炎のような数のごく少ない病気が、全国比だけで上に来ないようにする
        return ({"warn": 0, "advisory": 1}.get(r["level"], 2), r["slug"] == "ari", -rel)
    rows.sort(key=_rk)
    lines = [f"・{r['name'].split('（')[0]} {fmt(r['per'])}{lvtxt(r['level'])}" for r in rows if r["per"] and r["slug"] != "ari"][:3]
    share = xshare(f"【{pref}】いま流行っている感染症（{w['year']}年{w['week']}週・定点当たり）\n" + "\n".join(lines), f"/p/{code}/", f"p-{code}", [pref, "感染症"])
    return T.TemplateResponse(request, "pref.html", ctx(request, nav="p", pref=pref, code=code, rows=rows, zz=zz, share=share,
                                               flu=svg_series(flu, threshold_lines("influenza")), cov=svg_series(cov)))


@app.get("/nagoya/", response_class=HTMLResponse)
def nagoya_page(request: Request, d: str = "influenza"):
    if d not in D.BY_SLUG:
        d = "influenza"
    c = store.db()
    nw = store.latest(c, "nagoya")
    wm = store.ward_map(c, d, nw["year"], nw["week"]) if nw else {}
    series = store.ward_series(c, d, "計", nw["year"]) if nw else []
    cl = store.closures(c)
    c.close()
    by_ward = {}
    for r in cl:
        by_ward.setdefault(r["ward"], 0)
        by_ward[r["ward"]] += 1
    key = "count" if d == "covid19" else "per"
    topw = sorted(((k, v) for k, v in wm.items() if k != "計" and v.get(key) is not None), key=lambda kv: -kv[1][key])[:3]
    share = xshare(f"【名古屋市】{D.BY_SLUG[d]['name']}（{nw['week']}週）。多い区は " + "、".join(f"{k}区 {fmt(v[key], 0 if key == 'count' else 2)}" for k, v in topw) + f"。学級閉鎖は今シーズン{len(cl)}件", f"/nagoya/?d={d}", f"nagoya-{d}", ["名古屋市", "感染症"]) if nw else ""
    return T.TemplateResponse(request, "nagoya.html", ctx(request, nav="nagoya", dis=D.BY_SLUG[d], wm=wm, by_ward=by_ward, cl=cl[:30], share=share,
                                                 chart=svg_series(series, threshold_lines(d) if d != "covid19" else None,
                                                                  unit="報告数" if d == "covid19" else "定点当たり")))


@app.get("/nagoya/{ws}/", response_class=HTMLResponse)
def ward_page(request: Request, ws: str):
    ward = D.SLUG_WARD.get(ws)
    if not ward:
        raise HTTPException(404)
    c = store.db()
    nw = store.latest(c, "nagoya")
    rows = []
    for slug in D.ORDER:
        wm = store.ward_map(c, slug, nw["year"], nw["week"])
        if ward in wm:
            rows.append({**D.BY_SLUG[slug], **wm[ward], "city": wm.get("計", {})})
    flu = store.ward_series(c, "influenza", ward, nw["year"])
    cl = store.closures(c, ward=ward + "区")
    c.close()
    lines = [f"・{r['name'].split('（')[0]} {int(r['count'])}人{lvtxt(r['level'])}" for r in rows if r["count"]][:3]
    share = xshare(f"【名古屋市{ward}区】いま流行っている感染症（{nw['week']}週）\n" + "\n".join(lines) + f"\n今シーズンの学級閉鎖など {len(cl)}件", f"/nagoya/{ws}/", f"ward-{ws}", [f"名古屋市{ward}区", "感染症"])
    return T.TemplateResponse(request, "ward.html", ctx(request, nav="nagoya", ward=ward, ws=ws, rows=rows, cl=cl, share=share, flu=svg_series(flu, threshold_lines("influenza"))))


@app.get("/gakkyu/", response_class=HTMLResponse)
def gakkyu_page(request: Request, ward: str = ""):
    c = store.db()
    cl = store.closures(c, ward=(ward + "区") if ward in D.NAGOYA_WARDS else None)
    allc = store.closures(c)
    c.close()
    by_ward = {}
    by_day = {}
    for r in allc:
        by_ward[r["ward"]] = by_ward.get(r["ward"], 0) + 1
        by_day[r["found"]] = by_day.get(r["found"], 0) + 1
    days = sorted(by_day.items())[-21:]
    topw = sorted(by_ward.items(), key=lambda kv: -kv[1])[:3]
    share = xshare(f"【名古屋市】インフルエンザなどによる学級閉鎖・学年閉鎖、今シーズン{len(allc)}件。多い区は " + "、".join(f"{k} {v}件" for k, v in topw), "/gakkyu/", "gakkyu", ["名古屋市", "学級閉鎖", "インフルエンザ"])
    return T.TemplateResponse(request, "gakkyu.html", ctx(request, nav="gakkyu", cl=cl, by_ward=by_ward, days=days, ward=ward, total=len(allc), share=share))


@app.get("/zensu/", response_class=HTMLResponse)
def zensu_page(request: Request):
    c = store.db()
    w = store.latest(c, "idwr")
    zz = store.zensu(c, w["year"], w["week"])
    aichi = {r["disease"]: r for r in store.zensu(c, w["year"], w["week"], "愛知県")}
    c.close()
    return T.TemplateResponse(request, "zensu.html", ctx(request, nav="zensu", zz=zz, aichi=aichi))


@app.get("/about", response_class=HTMLResponse)
def about(request: Request):
    return T.TemplateResponse(request, "about.html", ctx(request, nav="about"))


# ---------------- API ----------------

@app.get("/api/pref")
def api_pref(d: str = "influenza"):
    if d not in D.BY_SLUG:
        raise HTTPException(400, "d は感染症の名前（例: influenza, covid19）")
    c = store.db()
    w = store.latest(c, "idwr")
    m = store.pref_map(c, d, w["year"], w["week"])
    c.close()
    return {"disease": D.BY_SLUG[d], "year": w["year"], "week": w["week"], "start": w["start"], "end": w["end"], "source": w["url"], "data": m}


@app.get("/api/nagoya")
def api_nagoya(d: str = "influenza"):
    if d not in D.BY_SLUG:
        raise HTTPException(400, "d は感染症の名前（例: influenza, covid19）")
    c = store.db()
    w = store.latest(c, "nagoya")
    m = store.ward_map(c, d, w["year"], w["week"])
    cl = store.closures(c)
    c.close()
    by_ward = {}
    for r in cl:
        by_ward[r["ward"].replace("区", "")] = by_ward.get(r["ward"].replace("区", ""), 0) + 1
    return {"disease": D.BY_SLUG[d], "year": w["year"], "week": w["week"], "start": w["start"], "end": w["end"], "source": w["url"], "data": m, "closures_by_ward": by_ward}


@app.get("/api/closures")
def api_closures(ward: str = ""):
    c = store.db()
    rows = [dict(r) for r in store.closures(c, ward=(ward + "区") if ward else None)]
    url = store.meta(c, "closure_url")
    c.close()
    return {"source": url, "rows": rows}


GSI_SEARCH = "https://msearch.gsi.go.jp/address-search/AddressSearch?q="
GSI_REV = "https://mreversegeocoder.gsi.go.jp/reverse-geocoder/LonLatToAddress?lat={lat}&lon={lon}"


def _get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "kkansen/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


@app.get("/api/lookup")
def api_lookup(q: str = "", lat: float | None = None, lon: float | None = None):
    """住所か現在地 → 都道府県（と名古屋市なら区）。地理院の住所検索・逆ジオコーダを使う"""
    try:
        if q.strip():
            res = _get_json(GSI_SEARCH + urllib.parse.quote(q.strip()))
            if not res:
                return JSONResponse({"error": "その住所が見つかりませんでした。市区町村名から入れてください"}, status_code=404)
            lon, lat = res[0]["geometry"]["coordinates"]
        if lat is None or lon is None:
            return JSONResponse({"error": "住所か現在地を入れてください"}, status_code=400)
        rv = _get_json(GSI_REV.format(lat=lat, lon=lon)).get("results") or {}
        code = str(rv.get("muniCd", ""))
    except Exception:
        return JSONResponse({"error": "住所の検索に失敗しました。少し待ってからもう一度お試しください"}, status_code=502)
    if len(code) < 4:
        return JSONResponse({"error": "日本国内の場所を入れてください"}, status_code=404)
    pref = D.PREFS[int(code[:2]) - 1]
    out = {"lat": lat, "lon": lon, "pref": pref, "pref_code": code[:2].zfill(2), "ward": None}
    if code.startswith("231") and len(code) == 5 and 23101 <= int(code) <= 23116:
        out["ward"] = D.NAGOYA_WARDS[int(code) - 23101]
        out["ward_slug"] = D.WARD_SLUG[out["ward"]]
    return out


# ---------------- 検索エンジン・AI 向け ----------------

@app.get("/robots.txt", response_class=PlainTextResponse)
def robots():
    return f"User-agent: *\nAllow: /\nSitemap: {PUBLIC}/sitemap.xml\n"


@app.get("/sitemap.xml")
def sitemap():
    c = store.db()
    w = store.latest(c, "idwr")
    c.close()
    lm = w["end"] if w else dt.date.today().isoformat()
    urls = ["/", "/map/", "/nagoya/", "/gakkyu/", "/zensu/", "/about"] + [f"/d/{s}/" for s in D.ORDER] + [f"/p/{c}/" for c in D.PREF_SLUG.values()] + [f"/nagoya/{s}/" for s in D.WARD_SLUG.values()]
    body = "".join(f"<url><loc>{PUBLIC}{u}</loc><lastmod>{lm}</lastmod></url>" for u in urls)
    return Response(f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>', media_type="application/xml")


@app.get("/llms.txt", response_class=PlainTextResponse)
def llms():
    c = store.db()
    w = store.latest(c, "idwr")
    nw = store.latest(c, "nagoya")
    rank = store.ranking(c, w["year"], w["week"])[:6] if w else []
    c.close()
    lines = [f"# {SITE}", "",
             "> いま流行っている感染症を、全国の都道府県と名古屋市の区ごとに地図で見るサイト。国（国立健康危機管理研究機構）の感染症発生動向調査の速報と、名古屋市の週報・学級閉鎖の発表を毎週・毎日取り込む。株式会社エクスブリッジ製。",
             "", "## 何が分かるか",
             "- 定点把握の19疾患（インフルエンザ・新型コロナ・RSウイルス・溶連菌・感染性胃腸炎・マイコプラズマ肺炎・手足口病・りんご病など）と急性呼吸器感染症（ARI）の、都道府県別の定点当たり報告数",
             "- 名古屋市16区の患者報告数と定点当たり報告数（市の週報から）、学級閉鎖・学年閉鎖・休校の一覧（学校名・区・期間）",
             "- 全数把握の感染症（麻しん・百日咳・梅毒・結核など）の今週の届け出数",
             "- 警報・注意報レベル：国の基準値（インフルエンザは定点当たり30で警報、10で注意報など）に対して、都道府県・区の値が超えているかを目安として示す（正式な発令は各自治体）",
             "", f"## いまの状況（{w['year']}年{w['week']}週 {w['start']}〜{w['end']}・全国の定点当たり）" if w else ""]
    for r in rank:
        lines.append(f"- {r['name']}: {fmt(r['per'])}（前週 {fmt(r['prev'])}）" + (f"・警報レベルの都道府県 {r['warn']}" if r['warn'] else "") + (f"・注意報レベル {r['adv']}" if r['adv'] else ""))
    lines += ["", "## 注意", "- 数字は公式の速報値で、あとで確定値に直ることがある。受診すべきかどうかの判断はしない。",
              "- 都道府県・区に警報・注意報の基準値を当てはめたのは目安。正式な警報・注意報は自治体が保健所の管内ごとに出す。",
              "", "## ページ", f"- 地図: {PUBLIC}/map/", f"- 名古屋市（区・学級閉鎖）: {PUBLIC}/nagoya/", f"- 学級閉鎖: {PUBLIC}/gakkyu/",
              f"- 病名ごと: {PUBLIC}/d/influenza/ など", f"- 都道府県ごと: {PUBLIC}/p/23/ （愛知県）など", f"- データについて: {PUBLIC}/about",
              "", "## API（JSON）", f"- {PUBLIC}/api/pref?d=influenza", f"- {PUBLIC}/api/nagoya?d=covid19", f"- {PUBLIC}/api/closures"]
    return "\n".join(lines) + "\n"
