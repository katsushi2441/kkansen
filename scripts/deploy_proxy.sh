#!/bin/bash
# 公開入口 php/kkansen.php を heteml (kurage.exbridge.jp) へ置く（FTPS 1接続）。
# バックエンドの場所 kkansen_config.php は同じ場所に置く（リポジトリには含めない）。
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . /home/kojima/work/aixec/.env; set +a
BACKEND="${KKANSEN_BACKEND_URL:-http://exbridge.ddns.net:18382}"
T=$(mktemp -d)
cp php/kkansen.php "$T/"
printf '<?php define("KKANSEN_BACKEND", "%s");\n' "$BACKEND" > "$T/kkansen_config.php"
/usr/bin/python3 /home/kojima/work/kpayload/scripts/ftps_put.py "$T" /web/kurage_exbridge_jp kkansen.php kkansen_config.php
rm -rf "$T"
curl -s -o /dev/null -w "public: %{http_code}\n" "https://kurage.exbridge.jp/kkansen.php/"
