"""MCP（Model Context Protocol）の入口。AI エージェントから、感染症の流行状況を道具（tool）として呼べるようにする。

POST /mcp に JSON-RPC 2.0 で話す（Streamable HTTP。セッションは持たず、毎回 JSON を返すだけ）。
読み取り専用。返す数字は画面と同じ store の値で、出典 URL・対象週・注意書きを必ず付ける。
  Claude Code: claude mcp add --transport http kkansen https://kurage.exbridge.jp/kkansen.php/mcp
"""
from __future__ import annotations

import json
import os
from typing import Any, Callable

from . import diseases as D
from . import store

PUBLIC = os.environ.get("KKANSEN_PUBLIC", "https://kurage.exbridge.jp/kkansen.php")
VERSIONS = ["2025-06-18", "2025-03-26", "2024-11-05"]
NOTE = ("数字は国（国立健康危機管理研究機構）の感染症発生動向調査の速報と名古屋市の発表をそのまま載せたもので、あとで確定値に直ることがある。"
        "警報・注意報レベルは国の基準値を都道府県・区の値に当てはめた目安で、正式な発令は自治体が保健所の管内ごとに行う。受診の判断には使わない。")
INSTRUCTIONS = ("Kurage 感染症マップ（株式会社エクスブリッジ）の MCP です。日本の都道府県ごとの定点把握の感染症（インフルエンザ・新型コロナ・RSウイルス・溶連菌など19疾患と急性呼吸器感染症）と、"
                "名古屋市16区の患者数・学級閉鎖を返します。答えるときは、返ってきた対象週（いつの週の数字か）と出典 URL を利用者に示してください。"
                "医療上の判断（受診すべきか等）はしないでください。")


class ToolError(Exception):
    """利用者に返す、入力の誤り"""


# ---------------- 入力の読み替え ----------------

def _disease(v: str | None, default: str | None = "influenza") -> dict | None:
    if not v:
        return D.BY_SLUG[default] if default else None
    s = v.strip()
    if s in D.BY_SLUG:
        return D.BY_SLUG[s]
    for d in D.BY_SLUG.values():
        names = [d["official"], d["name"], d["nagoya"], *d["aliases"]]
        if any(s == n for n in names):
            return d
    for d in D.BY_SLUG.values():
        names = [d["official"], d["name"], *d["aliases"]]
        if any(s in n or n in s for n in names):
            return d
    raise ToolError(f"感染症「{v}」が見つかりません。使える名前: " + "、".join(d["name"] for d in D.BY_SLUG.values()))


def _pref(v: str) -> str:
    s = (v or "").strip()
    if not s:
        raise ToolError("都道府県を指定してください（例: 愛知県、23）")
    if s.isdigit() and 1 <= int(s) <= 47:
        return D.PREFS[int(s) - 1]
    for p in D.PREFS:
        if s == p or (p[-1] in "都府県" and s == p[:-1]):
            return p
    raise ToolError(f"都道府県「{v}」が見つかりません")


def _ward(v: str | None) -> str | None:
    if not v:
        return None
    s = v.strip().removeprefix("名古屋市").removesuffix("区")
    if s in D.NAGOYA_WARDS:
        return s
    if s in D.SLUG_WARD:
        return D.SLUG_WARD[s]
    raise ToolError(f"名古屋市の区「{v}」が見つかりません。区: " + "、".join(w + "区" for w in D.NAGOYA_WARDS))


def _week(w) -> dict:
    return {"year": w["year"], "week": w["week"], "start": w["start"], "end": w["end"], "source": w["url"]}


def _lv(lv: str) -> str | None:
    return D.level_label(lv) + "の目安" if lv else None


def _r(v):
    return round(v, 2) if isinstance(v, float) else v


def _n(v):
    """患者数・件数（CSV 由来で 31428.0 のように来る）を整数に"""
    return int(v) if isinstance(v, float) and v.is_integer() else v


# ---------------- 道具 ----------------

def t_trending(a: dict) -> dict:
    c = store.db()
    w = store.latest(c, "idwr")
    rank = store.ranking(c, w["year"], w["week"])
    c.close()
    n = max(1, min(int(a.get("limit") or 10), len(rank)))
    return {"target_week": _week(w), "unit": "全国の定点当たり報告数（定点医療機関1か所あたりの1週間の患者数）",
            "order": "警報・注意報レベルの都道府県が多い順、次に基準値に近い順（基準値の無い感染症は今年の山に対する今の割合）",
            "diseases": [{"disease": r["name"], "slug": r["slug"], "per_sentinel": _r(r["per"]), "previous_week": _r(r["prev"]), "patients": _n(r["count"]),
                          "prefectures_at_warning_level": r["warn"], "prefectures_at_advisory_level": r["adv"],
                          "top_prefectures": [{"prefecture": p, "per_sentinel": _r(v)} for p, v in r["top"]],
                          "page": f"{PUBLIC}/d/{r['slug']}/"} for r in rank[:n]],
            "page": f"{PUBLIC}/", "note": NOTE}


def t_prefecture(a: dict) -> dict:
    p = _pref(a.get("prefecture", ""))
    one = _disease(a.get("disease"), default=None)
    c = store.db()
    w = store.latest(c, "idwr")
    out = []
    for slug in ([one["slug"]] if one else D.ORDER):
        m = store.pref_map(c, slug, w["year"], w["week"])
        v, t = m.get(p), m.get("総数")
        if not v:
            continue
        out.append({"disease": D.BY_SLUG[slug]["name"], "slug": slug, "per_sentinel": _r(v["per"]), "previous_week": _r(v["prev"]), "patients": _n(v["count"]),
                    "level": _lv(v["level"]), "national_per_sentinel": _r(t["per"]) if t else None})
    c.close()
    if not one:
        # 急性呼吸器感染症（ARI）は対象が広く桁が違うので最後に置く
        out.sort(key=lambda r: (r["slug"] == "ari", -(r["per_sentinel"] or 0)))
    return {"prefecture": p, "target_week": _week(w), "diseases": out, "page": f"{PUBLIC}/p/{D.PREF_SLUG[p]}/", "note": NOTE}


def t_by_prefecture(a: dict) -> dict:
    d = _disease(a.get("disease"))
    c = store.db()
    w = store.latest(c, "idwr")
    m = store.pref_map(c, d["slug"], w["year"], w["week"])
    c.close()
    rows = [{"prefecture": p, "per_sentinel": _r(v["per"]), "previous_week": _r(v["prev"]), "patients": _n(v["count"]), "level": _lv(v["level"])}
            for p, v in m.items() if p != "総数"]
    rows.sort(key=lambda r: -(r["per_sentinel"] or 0))
    t = m.get("総数")
    return {"disease": d["name"], "target_week": _week(w), "national_per_sentinel": _r(t["per"]) if t else None,
            "thresholds": {"warning_start": d["warn_on"], "warning_end": d["warn_off"], "advisory": d["advisory"]},
            "prefectures": rows, "map": f"{PUBLIC}/map/?d={d['slug']}", "page": f"{PUBLIC}/d/{d['slug']}/", "note": NOTE}


def t_nagoya(a: dict) -> dict:
    d = _disease(a.get("disease"))
    ward = _ward(a.get("ward"))
    c = store.db()
    w = store.latest(c, "nagoya")
    m = store.ward_map(c, d["slug"], w["year"], w["week"])
    c.close()
    unit = "報告数（新型コロナは市が区ごとの定点数を出していないため患者数のみ）" if d["slug"] == "covid19" else "定点当たり報告数（区の患者数÷区の定点医療機関数）"
    rows = [{"ward": k + "区", "patients": _n(v["count"]), "sentinels": v["sentinels"], "per_sentinel": v["per"], "level": _lv(v["level"])}
            for k, v in m.items() if k != "計" and (not ward or k == ward)]
    total = m.get("計")
    return {"city": "名古屋市", "disease": d["name"], "target_week": _week(w), "unit": unit, "wards": rows,
            "city_total_patients": _n(total["count"]) if total else None,
            "page": f"{PUBLIC}/nagoya/{D.WARD_SLUG[ward]}/" if ward else f"{PUBLIC}/nagoya/", "note": NOTE}


def t_closures(a: dict) -> dict:
    ward = _ward(a.get("ward"))
    days = a.get("days")
    days = int(days) if days else None
    c = store.db()
    rows = store.closures(c, ward=(ward + "区") if ward else None, days=days)
    src = store.meta(c, "closure_url")
    c.close()
    lim = max(1, min(int(a.get("limit") or 50), 200))
    by_ward: dict[str, int] = {}
    for r in rows:
        by_ward[r["ward"]] = by_ward.get(r["ward"], 0) + 1
    return {"city": "名古屋市", "what": "集団かぜ（インフルエンザ様疾患）による学級閉鎖・学年閉鎖・休校", "source": src,
            "filter": {"ward": (ward + "区") if ward else None, "last_days": days}, "count": len(rows), "count_by_ward": by_ward,
            "rows": [{"found": r["found"], "ward": r["ward"], "facility": r["facility"], "grade_class": r["grade"], "enrolled": r["enrolled"],
                      "patients": r["patients"], "absent": r["absent"], "action": r["action"], "period": r["period"]} for r in rows[:lim]],
            "page": f"{PUBLIC}/gakkyu/", "note": NOTE}


def t_trend(a: dict) -> dict:
    d = _disease(a.get("disease"))
    ward = _ward(a.get("ward"))
    c = store.db()
    if ward:
        w = store.latest(c, "nagoya")
        s = store.ward_series(c, d["slug"], ward, w["year"])
        area, page = f"名古屋市{ward}区", f"{PUBLIC}/nagoya/{D.WARD_SLUG[ward]}/"
        unit = "報告数" if d["slug"] == "covid19" else "定点当たり報告数"
    else:
        p = _pref(a["prefecture"]) if a.get("prefecture") else "総数"
        w = store.latest(c, "idwr")
        s = store.pref_series(c, d["slug"], p, w["year"])
        area, page = ("全国" if p == "総数" else p), (f"{PUBLIC}/p/{D.PREF_SLUG[p]}/" if p != "総数" else f"{PUBLIC}/d/{d['slug']}/")
        unit = "定点当たり報告数"
    c.close()
    return {"disease": d["name"], "area": area, "year": w["year"], "unit": unit,
            "weeks": [{"week": wk, "value": _r(v)} for wk, v in s], "latest_week": _week(w), "page": page, "note": NOTE}


def t_zensu(a: dict) -> dict:
    p = _pref(a["prefecture"]) if a.get("prefecture") else "総数"
    c = store.db()
    w = store.latest(c, "idwr")
    rows = store.zensu(c, w["year"], w["week"], p)
    c.close()
    return {"area": "全国" if p == "総数" else p, "what": "全数把握の感染症（麻しん・百日咳・梅毒・結核など）の今週の届け出数と今年の累計",
            "target_week": _week(w), "diseases": [{"disease": r["disease"], "this_week": _n(r["count"]), "this_year": _n(r["cum"])} for r in rows],
            "page": f"{PUBLIC}/zensu/", "note": NOTE}


def t_address(a: dict) -> dict:
    from .main import api_lookup   # 地理院の住所検索（循環 import を避けて呼ぶ時に読む）
    q = (a.get("address") or "").strip()
    if not q:
        raise ToolError("住所を指定してください（例: 名古屋市南区、札幌市中央区）")
    r = api_lookup(q=q)
    if not isinstance(r, dict):
        raise ToolError(json.loads(r.body).get("error", "住所を調べられませんでした"))
    out = {"address_query": q, "prefecture": r["pref"]}
    out["prefecture_status"] = t_prefecture({"prefecture": r["pref"]})
    if r.get("ward"):
        out["nagoya_ward"] = r["ward"] + "区"
        out["ward_influenza"] = t_nagoya({"disease": "influenza", "ward": r["ward"]})["wards"]
        cl = t_closures({"ward": r["ward"], "days": 14, "limit": 20})
        out["ward_closures_last_14_days"] = {"count": cl["count"], "rows": cl["rows"], "source": cl["source"]}
    out["note"] = NOTE + "住所は都道府県（名古屋市は区）を決めるためだけに使い、保存しない。"
    return out


S_DISEASE = {"type": "string", "description": "感染症の名前か slug（例: インフルエンザ, コロナ, 溶連菌, influenza, covid19）。省略時はインフルエンザ"}
S_PREF = {"type": "string", "description": "都道府県名（例: 愛知県, 東京都, 北海道）か都道府県コード（1〜47）"}
S_WARD = {"type": "string", "description": "名古屋市の区（例: 南区, 千種）"}

TOOLS: list[tuple[str, str, str, dict, Callable[[dict], dict]]] = [
    ("get_trending", "いま流行っている感染症（全国）",
     "全国でいま流行っている感染症を、警報・注意報レベルの都道府県が多い順に返す。定点当たり報告数・前週・多い都道府県つき。",
     {"limit": {"type": "integer", "description": "何件返すか（既定10、最大20）"}}, t_trending),
    ("get_prefecture_status", "都道府県の流行状況",
     "1つの都道府県の、感染症ごとの定点当たり報告数・前週・警報/注意報レベルの目安・全国値を返す。disease を省くと全疾患。",
     {"prefecture": S_PREF, "disease": {**S_DISEASE, "description": "感染症の名前（省略時は全疾患）"}}, t_prefecture),
    ("get_disease_by_prefecture", "感染症ごとの都道府県一覧",
     "1つの感染症について、47都道府県の定点当たり報告数を多い順に返す。警報・注意報の基準値つき。",
     {"disease": S_DISEASE}, t_by_prefecture),
    ("get_nagoya_wards", "名古屋市の区ごとの流行状況",
     "名古屋市16区の患者報告数と定点当たり報告数を返す（市の週報から。国の速報より1週早いことがある）。ward で1区に絞れる。",
     {"disease": S_DISEASE, "ward": S_WARD}, t_nagoya),
    ("get_nagoya_class_closures", "名古屋市の学級閉鎖",
     "名古屋市の集団かぜによる学級閉鎖・学年閉鎖・休校を、学校名・区・学年組・患者数・期間で返す（今シーズン、新しい順）。",
     {"ward": S_WARD, "days": {"type": "integer", "description": "直近何日に判明した分か（省略時は今シーズン全部）"},
      "limit": {"type": "integer", "description": "最大件数（既定50）"}}, t_closures),
    ("get_trend", "今年の週ごとの推移",
     "1つの感染症の、今年の週ごとの推移を返す。prefecture を省くと全国、ward を指定すると名古屋市のその区。",
     {"disease": S_DISEASE, "prefecture": S_PREF, "ward": S_WARD}, t_trend),
    ("get_notifiable_diseases", "全数把握の感染症",
     "麻しん・百日咳・梅毒・結核など、全数把握の感染症の今週の届け出数と今年の累計を返す。prefecture を省くと全国。",
     {"prefecture": S_PREF}, t_zensu),
    ("get_status_by_address", "住所から地域の流行状況",
     "住所（市区町村まででよい）から都道府県を決め、その都道府県の流行状況を返す。名古屋市内なら区の数字と直近14日の学級閉鎖も返す。住所は保存しない。",
     {"address": {"type": "string", "description": "住所（例: 名古屋市南区, 大阪市北区）"}}, t_address),
]
REQUIRED = {"get_prefecture_status": ["prefecture"], "get_status_by_address": ["address"]}
BY_NAME = {t[0]: t for t in TOOLS}


def tools_list() -> list[dict]:
    return [{"name": n, "title": title, "description": desc,
             "inputSchema": {"type": "object", "properties": props, "required": REQUIRED.get(n, []), "additionalProperties": False},
             "annotations": {"title": title, "readOnlyHint": True, "openWorldHint": False}} for n, title, desc, props, _ in TOOLS]


def call(name: str, args: dict) -> dict:
    t = BY_NAME.get(name)
    if not t:
        raise KeyError(name)
    try:
        data = t[4](args or {})
    except ToolError as e:
        return {"content": [{"type": "text", "text": str(e)}], "isError": True}
    except Exception as e:  # データがまだ無い等
        return {"content": [{"type": "text", "text": f"取得に失敗しました: {e.__class__.__name__}"}], "isError": True}
    return {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}], "structuredContent": data}


def handle(msg: Any) -> dict | None:
    """JSON-RPC 1件を処理する。通知（id なし）には None を返す"""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or "method" not in msg:
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}}
    mid, method, params = msg.get("id"), msg["method"], msg.get("params") or {}
    if "id" not in msg:
        return None
    try:
        if method == "initialize":
            want = params.get("protocolVersion")
            res = {"protocolVersion": want if want in VERSIONS else VERSIONS[0], "capabilities": {"tools": {"listChanged": False}},
                   "serverInfo": {"name": "kkansen", "title": "Kurage 感染症マップ", "version": "1.0.0", "websiteUrl": PUBLIC + "/"},
                   "instructions": INSTRUCTIONS}
        elif method == "ping":
            res = {}
        elif method == "tools/list":
            res = {"tools": tools_list()}
        elif method == "tools/call":
            try:
                res = call(params.get("name", ""), params.get("arguments") or {})
            except KeyError:
                return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"Unknown tool: {params.get('name')}"}}
        elif method in ("resources/list", "prompts/list"):
            res = {method.split("/")[0]: []}
        else:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Method not found: {method}"}}
    except Exception as e:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": f"Internal error: {e.__class__.__name__}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": res}
