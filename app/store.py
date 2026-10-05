"""SQLite に保存し、画面用に読み出す。取得は refresh()（毎時の timer から呼ぶ。新しい週・新しい閉鎖が無ければ何もしない）。"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sqlite3

from . import diseases as D
from . import sources as S

DB = os.environ.get("KKANSEN_DB", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "kkansen.sqlite"))


def db() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    c.executescript("""
    PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
    CREATE TABLE IF NOT EXISTS weeks(src TEXT, year INT, week INT, start TEXT, end TEXT, url TEXT, fetched TEXT, PRIMARY KEY(src,year,week));
    CREATE TABLE IF NOT EXISTS pref_week(year INT, week INT, pref TEXT, disease TEXT, count REAL, per REAL, PRIMARY KEY(year,week,pref,disease));
    CREATE TABLE IF NOT EXISTS zensu_week(year INT, week INT, pref TEXT, disease TEXT, count REAL, cum REAL, PRIMARY KEY(year,week,pref,disease));
    CREATE TABLE IF NOT EXISTS ward_week(year INT, week INT, ward TEXT, disease TEXT, count REAL, sentinels REAL, PRIMARY KEY(year,week,ward,disease));
    CREATE TABLE IF NOT EXISTS closures(id TEXT PRIMARY KEY, season INT, found TEXT, ward TEXT, facility TEXT, grade TEXT, enrolled INT, patients INT, absent INT, action TEXT, period TEXT, first_seen TEXT);
    """)
    return c


def meta(c, k, v=None):
    if v is not None:
        c.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (k, v))
        return v
    r = c.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
    return r[0] if r else None


def _slug(official: str) -> str | None:
    d = D.BY_OFFICIAL.get(official)
    return d["slug"] if d else None


def save_idwr(c, data: dict) -> None:
    y, w = data["year"], data["week"]
    t = data["teiten"]
    c.execute("INSERT OR REPLACE INTO weeks VALUES('idwr',?,?,?,?,?,?)", (y, w, t["start"], t["end"], data["url"], dt.datetime.now().isoformat(timespec="seconds")))
    rows = [(y, w, p, _slug(n), cnt, per) for p, n, cnt, per in t["rows"] if _slug(n)]
    if data.get("ari"):
        rows += [(y, w, p, "ari", cnt, per) for p, n, cnt, per in data["ari"]["rows"]]
    c.executemany("INSERT OR REPLACE INTO pref_week VALUES(?,?,?,?,?,?)", rows)
    c.executemany("INSERT OR REPLACE INTO zensu_week VALUES(?,?,?,?,?,?)", [(y, w, p, n, cnt, cum) for p, n, cnt, cum in data["zensu"]["rows"]])
    # 今年1週からの推移（過去の週を埋める。速報の確定で数字が変わることがあるので上書き）
    past = [(y, wk, p, _slug(n), cnt, per) for n, wk, p, cnt, per in data.get("tougai", []) if _slug(n) and wk < w]
    c.executemany("INSERT OR REPLACE INTO pref_week VALUES(?,?,?,?,?,?)", past)


def save_nagoya(c, d: dict) -> None:
    c.execute("INSERT OR REPLACE INTO weeks VALUES('nagoya',?,?,?,?,?,?)", (d["year"], d["week"], d["start"], d["end"], d["url"], dt.datetime.now().isoformat(timespec="seconds")))
    rows = []
    for name, v in d["diseases"].items():
        dd = D.BY_NAGOYA.get(name)
        if not dd:
            continue
        sent = d["sentinels"].get(v["type"], {})
        for ward in D.NAGOYA_WARDS + ["計"]:
            rows.append((d["year"], d["week"], ward, dd["slug"], v["counts"].get(ward, 0.0), sent.get(ward)))
    c.executemany("INSERT OR REPLACE INTO ward_week VALUES(?,?,?,?,?,?)", rows)


def save_closures(c, d: dict) -> int:
    now = dt.datetime.now().isoformat(timespec="seconds")
    n = 0
    for r in d["rows"]:
        cur = c.execute("INSERT OR IGNORE INTO closures VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                        (r["id"], d["season"], r["found"], r["ward"], r["facility"], r["grade"], r["enrolled"], r["patients"], r["absent"], r["action"], r["period"], now))
        n += cur.rowcount
    meta(c, "closure_url", d["url"])
    m = re.search(r"/(\d{8})[a-z]?_syuudankaze", d["url"])
    if m:   # 市のPDFの日付（ファイル名の先頭。前日判明分まで）
        meta(c, "closure_pdf_date", f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:]}")
    if n:   # 新しい件が入った日。sitemap の lastmod に使う
        meta(c, "closures_changed", dt.date.today().isoformat())
    return n


def refresh(backfill_nagoya: bool = False) -> dict:
    """新しい週が出ていれば取る。結果を返す（何を取ったか）"""
    c = db()
    out = {}
    try:
        lt = S.idwr_latest()
        if lt and not c.execute("SELECT 1 FROM weeks WHERE src='idwr' AND year=? AND week=?", lt).fetchone():
            save_idwr(c, S.fetch_idwr(*lt))
            out["idwr"] = lt
    except Exception as e:
        out["idwr_error"] = repr(e)
    try:
        nw = S.nagoya_weekly_latest()
        if nw:
            todo = [nw]
            if backfill_nagoya:
                todo = [(nw[0], w) for w in range(1, nw[1] + 1)]
            for y, w in todo:
                if c.execute("SELECT 1 FROM weeks WHERE src='nagoya' AND year=? AND week=?", (y, w)).fetchone():
                    continue
                try:
                    save_nagoya(c, S.fetch_nagoya_weekly(y, w))
                    out.setdefault("nagoya", []).append(w)
                except Exception as e:
                    out.setdefault("nagoya_skip", []).append(f"{w}:{e!r}"[:120])
    except Exception as e:
        out["nagoya_error"] = repr(e)
    try:
        out["closures_new"] = save_closures(c, S.fetch_closures())
    except Exception as e:
        out["closures_error"] = repr(e)
    meta(c, "refreshed", dt.datetime.now().isoformat(timespec="seconds"))
    c.commit()
    c.close()
    return out


# ---------------- 読み出し ----------------

def latest(c, src: str) -> sqlite3.Row | None:
    return c.execute("SELECT * FROM weeks WHERE src=? ORDER BY year DESC, week DESC LIMIT 1", (src,)).fetchone()


def pref_map(c, slug: str, y: int, w: int) -> dict:
    """{県: {'count','per','prev','level'}}。警報の継続を見るため前週も読む"""
    cur = {r["pref"]: r for r in c.execute("SELECT * FROM pref_week WHERE year=? AND week=? AND disease=?", (y, w, slug))}
    pw = c.execute("SELECT year,week FROM pref_week WHERE (year<? OR (year=? AND week<?)) AND disease=? ORDER BY year DESC, week DESC LIMIT 1", (y, y, w, slug)).fetchone()
    prev = {r["pref"]: r for r in c.execute("SELECT * FROM pref_week WHERE year=? AND week=? AND disease=?", (pw[0], pw[1], slug))} if pw else {}
    out = {}
    for p in D.PREFS + ["総数"]:
        r = cur.get(p)
        if not r:
            continue
        pr = prev.get(p)
        prev_lv = D.level(slug, pr["per"]) if pr else ""
        out[p] = {"count": r["count"], "per": r["per"], "prev": pr["per"] if pr else None, "level": D.level(slug, r["per"], prev_lv == "warn")}
    return out


def pref_series(c, slug: str, pref: str, y: int) -> list[tuple[int, float | None]]:
    return [(r["week"], r["per"]) for r in c.execute("SELECT week, per FROM pref_week WHERE year=? AND disease=? AND pref=? ORDER BY week", (y, slug, pref))]


def ranking(c, y: int, w: int) -> list[dict]:
    """いま流行っている順。全国の定点当たり・前週比・基準値を超えた都道府県の数"""
    out = []
    for slug in D.ORDER:
        m = pref_map(c, slug, y, w)
        t = m.get("総数")
        if not t:
            continue
        d = D.BY_SLUG[slug]
        nwarn = sum(1 for p, v in m.items() if p != "総数" and v["level"] == "warn")
        nadv = sum(1 for p, v in m.items() if p != "総数" and v["level"] == "advisory")
        ratio = (t["per"] / d["warn_on"]) if d["warn_on"] and t["per"] is not None else None
        peak = c.execute("SELECT MAX(per) FROM pref_week WHERE year=? AND disease=? AND pref='総数'", (y, slug)).fetchone()[0]
        if ratio is None and t["per"] is not None and peak:
            ratio = t["per"] / peak   # 基準値の無い病気は「今年の山に対して今が何割か」で並べる
            if t["per"] < 0.3:
                ratio *= 0.2          # 髄膜炎のように数がごく少ない病気は、少し増えただけで上に来ないようにする
        out.append({**d, "count": t["count"], "per": t["per"], "prev": t["prev"], "warn": nwarn, "adv": nadv, "ratio": ratio,
                    "peak": peak, "top": sorted(((p, v["per"]) for p, v in m.items() if p != "総数" and v["per"] is not None), key=lambda x: -x[1])[:3]})
    # 並べ方: 基準値のある病気は基準値に対する割合、無い病気は前週からの伸び。まず件数の多い順で安定させる
    out.sort(key=lambda r: (r["slug"] == "ari", -(r["warn"] * 2 + r["adv"]), -((r["ratio"] or 0)), -(r["count"] or 0)))
    return out


def ward_map(c, slug: str, y: int, w: int) -> dict:
    out = {}
    for r in c.execute("SELECT * FROM ward_week WHERE year=? AND week=? AND disease=?", (y, w, slug)):
        per = (r["count"] / r["sentinels"]) if (r["sentinels"] and slug != "covid19") else None
        out[r["ward"]] = {"count": r["count"], "sentinels": r["sentinels"], "per": round(per, 2) if per is not None else None, "level": D.level(slug, per)}
    return out


def ward_series(c, slug: str, ward: str, y: int) -> list[tuple[int, float | None]]:
    res = []
    for r in c.execute("SELECT week, count, sentinels FROM ward_week WHERE year=? AND disease=? AND ward=? ORDER BY week", (y, slug, ward)):
        res.append((r["week"], (r["count"] / r["sentinels"]) if (r["sentinels"] and slug != "covid19") else r["count"]))
    return res


def closures(c, ward: str | None = None, days: int | None = None, season: int | None = None) -> list[sqlite3.Row]:
    q = "SELECT * FROM closures WHERE 1=1"
    a: list = []
    if season:
        q += " AND season=?"; a.append(season)
    if ward:
        q += " AND ward=?"; a.append(ward)
    if days:
        q += " AND found>=?"; a.append((dt.date.today() - dt.timedelta(days=days)).isoformat())
    return c.execute(q + " ORDER BY found DESC, rowid DESC", a).fetchall()


def zensu(c, y: int, w: int, pref: str = "総数") -> list[sqlite3.Row]:
    return c.execute("SELECT * FROM zensu_week WHERE year=? AND week=? AND pref=? AND count>0 ORDER BY count DESC", (y, w, pref)).fetchall()
