"""Kurage 感染症マップ — 公的データの取得と読み取り。

- 全国: 国立健康危機管理研究機構（JIHS）の IDWR 速報データ（毎週・CSV）
    定点把握 19 疾患（teiten.csv）・急性呼吸器感染症（ari.csv）・全数把握 88 疾患（zensu.csv）
    今年の 1 週からの推移（teiten-tougai.csv）
- 名古屋市: 感染症発生動向調査 週報（毎週・PDF）の「患者報告数（疾病区別）」と区ごとの定点数
- 名古屋市: 集団かぜ（インフルエンザ様疾患）による学級閉鎖等の状況（ほぼ毎日・PDF）

数字は公式の値をそのまま保存する。判定（警報・注意報の基準値を超えたか）は diseases.py の基準値で行う。
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import re
import subprocess
import tempfile
import urllib.request
from html import unescape

UA = "Mozilla/5.0 (compatible; kkansen/1.0; +https://kurage.exbridge.jp/kkansen.php/)"
IDWR = "https://id-info.jihs.go.jp/surveillance/idwr/provisional/{y}/{w:02d}/"
NAGOYA_WEEKLY = "https://www.city.nagoya.jp/_res/projects/default_project/_page_/001/040/784/{y}{w:02d}.pdf"
NAGOYA_CLOSURE_PAGE = "https://www.city.nagoya.jp/kenkofukushi/eisei/1015269/1015388/1015389/1015390.html"
NAGOYA_WARDS = ["千種", "東", "北", "西", "中村", "中", "昭和", "瑞穂", "熱田", "中川", "港", "南", "守山", "緑", "名東", "天白"]


def get(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def exists(url: str) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA}, method="HEAD")
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status == 200
    except Exception:
        return False


def sjis_rows(raw: bytes) -> list[list[str]]:
    text = raw.decode("cp932", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    return [r for r in csv.reader(io.StringIO(text))]


def num(s: str) -> float | None:
    s = (s or "").strip().replace(",", "")
    if s in ("", "-", "－"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


# ---------------- 全国（IDWR 速報） ----------------

def idwr_latest(today: dt.date | None = None) -> tuple[int, int] | None:
    """いま出ている最新の週（年, 週）。今週から遡って index.html がある週を探す"""
    today = today or dt.date.today()
    y, w, _ = today.isocalendar()
    for back in range(0, 8):
        d = today - dt.timedelta(weeks=back)
        yy, ww, _ = d.isocalendar()
        if exists(IDWR.format(y=yy, w=ww) + "index.html"):
            return yy, ww
    return None


def parse_week_label(s: str) -> tuple[str, str]:
    """'2026年38週(09月14日～09月20日)' → ('2026-09-14', '2026-09-20')。1週目は前年12月から始まることがある"""
    m = re.search(r"(\d{4})年(\d+)週\((\d+)月(\d+)日[〜～~](\d+)月(\d+)日\)", s)
    if not m:
        return "", ""
    y, _, m1, d1, m2, d2 = map(int, m.groups())
    start = dt.date(y - 1 if (m1 == 12 and m2 == 1) else y, m1, d1)
    return start.isoformat(), dt.date(y, m2, d2).isoformat()


def parse_teiten(raw: bytes) -> dict:
    """定点把握（teiten.csv / ari.csv）: {'start','end','made','rows':[(pref, disease, count, per)]}"""
    rows = sjis_rows(raw)
    label = next((c for r in rows[:3] for c in r if "週(" in c), "")
    made = next((c for r in rows[:3] for c in r if "作成" in c), "")
    start, end = parse_week_label(label)
    hi = next(i for i, r in enumerate(rows) if len(r) > 1 and r[0] == "" and any(c for c in r[1:]))
    names = rows[hi]
    out = []
    for r in rows[hi + 2:]:
        if not r or not r[0].strip():
            continue
        pref = r[0].strip()
        for i, n in enumerate(names):
            if not n:
                continue
            c, p = (r[i] if i < len(r) else ""), (r[i + 1] if i + 1 < len(r) else "")
            out.append((pref, n.strip(), num(c), num(p)))
    return {"start": start, "end": end, "made": made, "rows": out}


def parse_zensu(raw: bytes) -> dict:
    """全数把握（zensu.csv）: rows=[(pref, disease, count, cumulative)]"""
    rows = sjis_rows(raw)
    label = next((c for r in rows[:3] for c in r if "週(" in c), "")
    start, end = parse_week_label(label)
    hi = next(i for i, r in enumerate(rows) if any("エボラ" in c for c in r))
    names = rows[hi]
    out = []
    for r in rows[hi + 1:]:
        if not r or not r[0].strip() or r[0].strip() in ("", "報告", "累積"):
            continue
        pref = r[0].strip()
        for i, n in enumerate(names):
            if not n:
                continue
            c, cum = (r[i] if i < len(r) else ""), (r[i + 1] if i + 1 < len(r) else "")
            out.append((pref, n.strip(), num(c), num(cum)))
    return {"start": start, "end": end, "rows": out}


def parse_tougai(raw: bytes) -> list[tuple[str, int, str, float | None, float | None]]:
    """今年1週からの推移（teiten-tougai.csv）: [(disease, week, pref, count, per)]"""
    rows = sjis_rows(raw)
    out = []
    disease = None
    weeks: list[int | None] = []
    for r in rows:
        if not r:
            continue
        if r[0] and all(not c for c in r[1:]) and "週" not in r[0] and "作成" not in r[0] and "報告数" not in r[0]:
            disease = r[0].strip()
            continue
        if len(r) > 3 and r[0] == "" and r[1] == "総数":
            weeks = [None, None, None]
            for c in r[3:]:
                m = re.match(r"(\d+)週", c)
                weeks.append(int(m.group(1)) if m else None)
            continue
        if disease and weeks and r[0].strip() and r[0].strip() not in ("",):
            pref = r[0].strip()
            for i in range(3, len(r) - 1, 2):
                w = weeks[i] if i < len(weeks) else None
                if w:
                    out.append((disease, w, pref, num(r[i]), num(r[i + 1])))
    return out


def fetch_idwr(y: int, w: int) -> dict:
    base = IDWR.format(y=y, w=w)
    data = {"year": y, "week": w, "url": base + "index.html"}
    data["teiten"] = parse_teiten(get(base + f"{y}-{w:02d}-teiten.csv"))
    try:
        data["ari"] = parse_teiten(get(base + f"{y}-{w:02d}-ari.csv"))
    except Exception:
        data["ari"] = None
    data["zensu"] = parse_zensu(get(base + f"{y}-{w:02d}-zensu.csv"))
    try:
        data["tougai"] = parse_tougai(get(base + f"{y}-{w:02d}-teiten-tougai.csv"))
    except Exception:
        data["tougai"] = []
    return data


# ---------------- 名古屋市（週報 PDF） ----------------

def nagoya_weekly_latest(today: dt.date | None = None) -> tuple[int, int] | None:
    today = today or dt.date.today()
    for back in range(0, 8):
        d = today - dt.timedelta(weeks=back)
        yy, ww, _ = d.isocalendar()
        if exists(NAGOYA_WEEKLY.format(y=yy, w=ww)):
            return yy, ww
    return None


def _bbox_words(pdf: bytes) -> list[dict]:
    """pdftotext -bbox で単語と座標を取る（ページ番号つき）"""
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(pdf)
        f.flush()
        html = subprocess.run(["pdftotext", "-bbox", f.name, "-"], capture_output=True, check=True).stdout.decode("utf-8", "replace")
    words = []
    for pi, page in enumerate(re.split(r"<page ", html)[1:]):
        for m in re.finditer(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>', page):
            x0, y0, x1, y1 = map(float, m.groups()[:4])
            words.append({"p": pi, "x0": x0, "x1": x1, "y": (y0 + y1) / 2, "t": unescape(m.group(5))})
    return words


def _lines(words: list[dict], page: int, tol: float = 2.5) -> list[list[dict]]:
    ws = sorted((w for w in words if w["p"] == page), key=lambda w: (w["y"], w["x0"]))
    lines: list[list[dict]] = []
    for w in ws:
        if lines and abs(lines[-1][0]["y"] - w["y"]) <= tol:
            lines[-1].append(w)
        else:
            lines.append([w])
    return [sorted(l, key=lambda w: w["x0"]) for l in lines]


SENTINEL_MARK = {"☆": "ARI", "○": "小児科", "△": "眼科", "◇": "基幹"}


def parse_nagoya_weekly(pdf: bytes) -> dict:
    """「患者報告数（疾病区別）」の表を、見出しの区名の x 座標に数字を割り当てて読む（空欄があっても列がずれない）"""
    words = _bbox_words(pdf)
    text_all = " ".join(w["t"] for w in words)
    m = re.search(r"(\d{4})\s*年第\s*(\d+)\s*週（(\d{4})年(\d+)月(\d+)日～(\d+)月(\d+)日）", text_all.replace(" ", ""))
    start = end = ""
    year = week = None
    if m:
        year, week = int(m.group(1)), int(m.group(2))
        y2, m1, d1, m2, d2 = map(int, m.groups()[2:])
        start = dt.date(y2, m1, d1).isoformat()
        end = dt.date(y2 if m2 >= m1 else y2 + 1, m2, d2).isoformat()
    for page in sorted({w["p"] for w in words}):
        lines = _lines(words, page)
        hi = next((i for i, l in enumerate(lines) if "疾病名/区" in "".join(w["t"] for w in l) and any(w["t"] == "千種" for w in l)), None)
        if hi is None:
            continue
        head = lines[hi]
        cols = {}
        for w in head:
            if w["t"] in NAGOYA_WARDS or w["t"] == "計":
                cols[w["t"]] = (w["x0"] + w["x1"]) / 2
        if len(cols) < 17:
            continue
        xs = sorted(cols.items(), key=lambda kv: kv[1])
        right = max(cols.values()) + 25
        diseases: dict[str, dict] = {}
        sentinels: dict[str, dict] = {}
        for l in lines[hi + 1: hi + 40]:
            label_words = [w for w in l if w["x1"] < xs[0][1] - 12]
            label = "".join(w["t"] for w in label_words).strip()
            if not label:
                continue
            vals = {}
            for w in l:
                if w in label_words or not re.fullmatch(r"\d+(\.\d+)?", w["t"]):
                    continue
                cx = (w["x0"] + w["x1"]) / 2
                if cx > right:
                    continue
                name, x = min(xs, key=lambda kv: abs(kv[1] - cx))
                if abs(x - cx) < 14:
                    vals[name] = float(w["t"])
            mark = label[0] if label[0] in SENTINEL_MARK else ""
            name = label[1:].strip() if mark else label
            if name.endswith("定点数"):
                sentinels[SENTINEL_MARK.get(mark, name.replace("定点数", ""))] = vals
                if mark == "◇":
                    break
            elif mark:
                diseases[name] = {"type": SENTINEL_MARK[mark], "counts": vals}
        return {"year": year, "week": week, "start": start, "end": end, "diseases": diseases, "sentinels": sentinels}
    raise ValueError("名古屋市の週報に「患者報告数（疾病区別）」の表が見つからない")


def fetch_nagoya_weekly(y: int, w: int) -> dict:
    url = NAGOYA_WEEKLY.format(y=y, w=w)
    d = parse_nagoya_weekly(get(url))
    d["url"] = url
    return d


# ---------------- 名古屋市（学級閉鎖 PDF） ----------------

def closure_pdf_url() -> str:
    html = get(NAGOYA_CLOSURE_PAGE).decode("utf-8", "replace")
    m = re.search(r'href="([^"]+\.pdf)"[^>]*>\s*今シーズン', html)
    if not m:
        m = re.search(r'href="([^"]+syuudankaze_soti_rireki[^"]+\.pdf)"', html)
    if not m:
        raise ValueError("学級閉鎖のPDFへのリンクが見つからない")
    return urllib.request.urljoin(NAGOYA_CLOSURE_PAGE, m.group(1))


ROW = re.compile(r"(\d{1,2})月(\d{1,2})日\s+(千種|東|北|西|中村|中|昭和|瑞穂|熱田|中川|港|南|守山|緑|名東|天白)\s+(.+?)\s{2,}(\S+(?:\s?\S+)*?)\s{2,}(\d+)\s+(\d+)\s+(\d+)\s+(学級閉鎖|学年閉鎖|休校|休園)\s+(.+?)\s*$")


def parse_closures(pdf: bytes, season_start_year: int) -> list[dict]:
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(pdf)
        f.flush()
        text = subprocess.run(["pdftotext", "-layout", f.name, "-"], capture_output=True, check=True).stdout.decode("utf-8", "replace")
    out = []
    for line in text.splitlines():
        line = re.sub(r"^\s*\d+\s+(?=\d{1,2}月)", "", line).strip()
        m = ROW.search(line)
        if not m:
            continue
        mo, d = int(m.group(1)), int(m.group(2))
        y = season_start_year if mo >= 8 else season_start_year + 1
        found = dt.date(y, mo, d).isoformat()
        rec = {"found": found, "ward": m.group(3) + "区", "facility": re.sub(r"\s+", " ", m.group(4)).strip(),
               "grade": m.group(5).strip(), "enrolled": int(m.group(6)), "patients": int(m.group(7)), "absent": int(m.group(8)),
               "action": m.group(9), "period": m.group(10).strip()}
        rec["id"] = hashlib.sha1("|".join(str(rec[k]) for k in ("found", "ward", "facility", "grade", "action")).encode()).hexdigest()[:16]
        out.append(rec)
    return out


WARDS = ("千種", "東", "北", "西", "中村", "中", "昭和", "瑞穂", "熱田", "中川", "港", "南", "守山", "緑", "名東", "天白")


def parse_closure_today(page: str) -> list[dict]:
    """市のページの「本日判明した集団発生施設（YYYY年M月D日）」の表。履歴PDFは「前日判明分まで」なので、
    当日の分はこの表にしか無い（翌日のPDFに同じ行が入る。区・施設名・学年の書き方はPDFと同じなので id も同じになる）"""
    import html as H
    m = re.search(r"本日判明した集団発生施設[（(](\d{4})年(\d{1,2})月(\d{1,2})日[）)]", page)
    if not m:
        return []
    found = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    t = page[m.end():page.find("</table>", m.end())]
    out = []
    for tr in re.findall(r"<tr.*?</tr>", t, re.S):
        c = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", H.unescape(x))).strip() for x in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", tr, re.S)]
        if len(c) < 8 or c[0] not in WARDS or not (c[3].isdigit() and c[4].isdigit() and c[5].isdigit()):
            continue
        rec = {"found": found, "ward": c[0] + "区", "facility": c[1], "grade": c[2], "enrolled": int(c[3]), "patients": int(c[4]),
               "absent": int(c[5]), "action": c[6], "period": c[7]}
        rec["id"] = hashlib.sha1("|".join(str(rec[k]) for k in ("found", "ward", "facility", "grade", "action")).encode()).hexdigest()[:16]
        out.append(rec)
    return out


def fetch_closures(today: dt.date | None = None) -> dict:
    today = today or dt.date.today()
    url = closure_pdf_url()
    m = re.search(r"rireki(\d{4})-\d{4}", url)
    season = int(m.group(1)) if m else (today.year if today.month >= 8 else today.year - 1)
    rows = parse_closures(get(url), season)
    try:   # 当日判明分（ページの表）も足す。表が読めなくても PDF の分は止めない
        seen = {r["id"] for r in rows}
        rows += [r for r in parse_closure_today(get(NAGOYA_CLOSURE_PAGE).decode("utf-8", "replace")) if r["id"] not in seen]
    except Exception:
        pass
    return {"url": url, "season": season, "rows": rows}
