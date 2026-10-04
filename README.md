# Kurage 感染症マップ（kkansen）

いま流行っている感染症を、全国の都道府県と名古屋市の区ごとに地図で見るサイトです。
国（国立健康危機管理研究機構）の感染症発生動向調査の速報と、名古屋市の週報・学級閉鎖の発表を取り込みます。

- 公開: https://kurage.exbridge.jp/kkansen.php/

## できること

- 定点把握の19疾患（インフルエンザ・新型コロナ・RSウイルス・溶連菌・感染性胃腸炎・マイコプラズマ肺炎ほか）と急性呼吸器感染症（ARI）を、都道府県ごとに色分けした地図（MapLibre GL ＋ OpenFreeMap）
- 「いま流行っている順」：警報・注意報の基準値の目安を超えた都道府県の数、基準値に対する近さ、基準値の無い病気は今年の山に対する割合
- 名古屋市16区の患者報告数・定点当たり報告数（市の週報 PDF を座標で読み取る）
- 名古屋市の学級閉鎖・学年閉鎖・休校の一覧（学校名・区・期間）
- 全数把握の感染症（麻しん・百日咳・梅毒など）の届け出数
- 住所・現在地から都道府県と名古屋市の区を引く（国土地理院の住所検索・逆ジオコーダ）
- 病名・都道府県・区ごとのページ、JSON API、llms.txt、sitemap.xml
- AI エージェント向けの MCP（`POST /mcp`、読み取り専用・8つの道具）

## AIから使う（MCP）

`/mcp` が MCP（Model Context Protocol）の入口です（Streamable HTTP・セッションなし・JSON で返す）。道具は8つで、どれも読み取り専用です。答えには対象の週・出典 URL・注意書きが付きます。

| 道具 | 内容 |
|---|---|
| `get_trending` | いま流行っている感染症（全国） |
| `get_prefecture_status` | 都道府県の流行状況 |
| `get_disease_by_prefecture` | 感染症ごとの47都道府県一覧 |
| `get_nagoya_wards` | 名古屋市の区ごとの流行状況 |
| `get_nagoya_class_closures` | 名古屋市の学級閉鎖 |
| `get_trend` | 今年の週ごとの推移（全国・都道府県・名古屋市の区） |
| `get_notifiable_diseases` | 全数把握の感染症 |
| `get_status_by_address` | 住所から地域の流行状況（住所は保存しない） |

```
claude mcp add --transport http kkansen https://kurage.exbridge.jp/kkansen.php/mcp
```

自分のサーバーで動かした場合は `https://<あなたのサーバー>/mcp` が同じように使えます。

## しないこと

体調の判断や、受診すべきかどうかの助言はしません。数字は公式の値をそのまま出し、出典へリンクします。
都道府県・区に警報・注意報の基準値を当てはめたのは目安で、正式な発令は自治体が保健所の管内ごとに行います。

## 動かし方

```
python3 -m venv .venv && .venv/bin/pip install fastapi uvicorn jinja2
.venv/bin/python -c "from app import store; print(store.refresh(backfill_nagoya=True))"   # 初回の取り込み
.venv/bin/uvicorn app.main:app --port 8000
```

`pdftotext`（poppler-utils）が必要です。定期の取り込みは `store.refresh()` を1日に数回呼んでください（新しい週が無ければ何もしません）。

## データと出典

- 国立健康危機管理研究機構「IDWR速報データ」（定点把握・全数把握・推移）
- 名古屋市感染症発生動向調査 週報、名古屋市「集団かぜ（インフルエンザ様疾患）による学級閉鎖等の状況」
- 境界：「国土数値情報（行政区域データ）」（国土交通省）を加工して作成（CC BY 4.0）
- 背景地図：OpenFreeMap（© OpenMapTiles・Data from OpenStreetMap）

## ライセンス

MIT License — 株式会社エクスブリッジ
