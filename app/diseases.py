"""感染症の一覧（定点把握）と、警報・注意報レベルの基準値。

基準値（定点当たり報告数）は、国の感染症発生動向調査で使われている値
（平成28年度 厚生労働科学研究「疫学的・統計学的なサーベイランスの評価と改善」の基準値）。
警報は「開始基準値以上で始まり、終息基準値未満で終わる」、注意報は「基準値以上」。
保健所の管内ごとに判定するもので、都道府県・区の値に当てはめるのは目安として示す。
COVID-19・RSウイルス・マイコプラズマ肺炎などには基準値が無い。
"""
from __future__ import annotations

D = [
    # slug, 正式名（国のCSVの表記）, 画面での呼び名, 別名（検索語）, 警報開始, 警報終息, 注意報, 名古屋週報での表記
    ("influenza", "インフルエンザ", "インフルエンザ", ["インフル"], 30.0, 10.0, 10.0, "インフルエンザ"),
    ("covid19", "COVID-19", "新型コロナ（COVID-19）", ["コロナ", "新型コロナウイルス感染症"], None, None, None, "新型コロナウイルス感染症（COVID-19）"),
    ("rsv", "ＲＳウイルス感染症", "RSウイルス感染症", ["RSウイルス"], None, None, None, "ＲＳウイルス感染症"),
    ("gas", "Ａ群溶血性レンサ球菌咽頭炎", "溶連菌（A群溶血性レンサ球菌咽頭炎）", ["溶連菌"], 8.0, 4.0, None, "Ａ群溶血性レンサ球菌咽頭炎"),
    ("gastro", "感染性胃腸炎", "感染性胃腸炎（ノロウイルスなど）", ["胃腸炎", "ノロウイルス"], 20.0, 12.0, None, "感染性胃腸炎"),
    ("mycoplasma", "マイコプラズマ肺炎", "マイコプラズマ肺炎", ["マイコプラズマ"], None, None, None, "マイコプラズマ肺炎"),
    ("varicella", "水痘", "水ぼうそう（水痘）", ["水疱瘡", "水ぼうそう"], 2.0, 1.0, 1.0, "水痘"),
    ("hfmd", "手足口病", "手足口病", [], 5.0, 2.0, None, "手足口病"),
    ("erythema", "伝染性紅斑", "りんご病（伝染性紅斑）", ["りんご病"], 2.0, 1.0, None, "伝染性紅斑"),
    ("pcf", "咽頭結膜熱", "プール熱（咽頭結膜熱）", ["プール熱"], 3.0, 1.0, None, "咽頭結膜熱"),
    ("herpangina", "ヘルパンギーナ", "ヘルパンギーナ", [], 6.0, 2.0, None, "ヘルパンギーナ"),
    ("mumps", "流行性耳下腺炎", "おたふくかぜ（流行性耳下腺炎）", ["おたふく"], 6.0, 2.0, 3.0, "流行性耳下腺炎"),
    ("exanthem", "突発性発しん", "突発性発しん", ["突発性発疹"], None, None, None, "突発性発しん"),
    ("ekc", "流行性角結膜炎", "はやり目（流行性角結膜炎）", ["はやり目"], 8.0, 4.0, None, "流行性角結膜炎"),
    ("ahc", "急性出血性結膜炎", "急性出血性結膜炎", [], 1.0, 0.1, None, "急性出血性結膜炎"),
    ("rota", "感染性胃腸炎（ロタウイルス）", "ロタウイルス胃腸炎", ["ロタウイルス"], None, None, None, "感染性胃腸炎（ロタウイルスに限る）"),
    ("chlamydia", "クラミジア肺炎", "クラミジア肺炎", [], None, None, None, "クラミジア肺炎"),
    ("bm", "細菌性髄膜炎", "細菌性髄膜炎", [], None, None, None, "細菌性髄膜炎"),
    ("am", "無菌性髄膜炎", "無菌性髄膜炎", [], None, None, None, "無菌性髄膜炎"),
    ("ari", "急性呼吸器感染症", "急性呼吸器感染症（ARI）", ["ARI"], None, None, None, "急性呼吸器感染症（ARI）"),
]

BY_SLUG = {d[0]: {"slug": d[0], "official": d[1], "name": d[2], "aliases": d[3], "warn_on": d[4], "warn_off": d[5], "advisory": d[6], "nagoya": d[7]} for d in D}
BY_OFFICIAL = {v["official"]: v for v in BY_SLUG.values()}
BY_NAGOYA = {v["nagoya"]: v for v in BY_SLUG.values()}
ORDER = [d[0] for d in D]

PREFS = ["北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県", "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県",
         "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県", "岐阜県", "静岡県", "愛知県", "三重県", "滋賀県", "京都府", "大阪府", "兵庫県",
         "奈良県", "和歌山県", "鳥取県", "島根県", "岡山県", "広島県", "山口県", "徳島県", "香川県", "愛媛県", "高知県", "福岡県", "佐賀県", "長崎県",
         "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県"]
PREF_SLUG = {p: f"{i + 1:02d}" for i, p in enumerate(PREFS)}

NAGOYA_WARDS = ["千種", "東", "北", "西", "中村", "中", "昭和", "瑞穂", "熱田", "中川", "港", "南", "守山", "緑", "名東", "天白"]
WARD_SLUG = {"千種": "chikusa", "東": "higashi", "北": "kita", "西": "nishi", "中村": "nakamura", "中": "naka", "昭和": "showa", "瑞穂": "mizuho",
             "熱田": "atsuta", "中川": "nakagawa", "港": "minato", "南": "minami", "守山": "moriyama", "緑": "midori", "名東": "meito", "天白": "tempaku"}
SLUG_WARD = {v: k for k, v in WARD_SLUG.items()}


def level(slug: str, per: float | None, prev_warn: bool = False) -> str:
    """'warn'（警報レベル）/'advisory'（注意報レベル）/'' 。警報は前週が警報なら終息基準値まで続く"""
    d = BY_SLUG.get(slug)
    if not d or per is None:
        return ""
    if d["warn_on"] is not None:
        if per >= d["warn_on"] or (prev_warn and d["warn_off"] is not None and per >= d["warn_off"]):
            return "warn"
    if d["advisory"] is not None and per >= d["advisory"]:
        return "advisory"
    return ""


def level_label(lv: str) -> str:
    return {"warn": "警報レベル", "advisory": "注意報レベル"}.get(lv, "")
