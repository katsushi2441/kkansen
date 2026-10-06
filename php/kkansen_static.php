<?php
// Kurage 感染症マップ (kkansen) — レンタルサーバーだけで動く公開入口（heteml では kkansen.php の名前で置く）。
//
// 画面とデータは app/export.py が前もって書き出したファイル（同じ場所の kkansen_static/）から返す。
// 閲覧のたびに当社のサーバーへ問い合わせない。当社のサーバーが止まっていても、ページは表示される。
//   - /api/lookup（住所→都道府県・区）は国土地理院を呼ぶだけなので、ここで動かす
//   - /mcp（AI 向け）だけは当社のサーバーへ中継する。つながらなければすぐに「使えません」と返す
// 中継先は同じ場所の kkansen_config.php で定義する（リポジトリには含めない）
//   <?php define('KKANSEN_BACKEND', 'http://あなたのサーバー:18382');
$__cfg = __DIR__ . '/kkansen_config.php';
if (is_file($__cfg)) { require_once $__cfg; }
$BACKEND = defined('KKANSEN_BACKEND') ? KKANSEN_BACKEND : '';
$DIR = __DIR__ . '/kkansen_static';

if (!isset($_SERVER['PATH_INFO']) || $_SERVER['PATH_INFO'] === '') {
    if (substr($_SERVER['REQUEST_URI'], -1) !== '/' && strpos($_SERVER['REQUEST_URI'], '?') === false) {
        header('Location: /kkansen.php/', true, 302); exit;
    }
}
$path = isset($_SERVER['PATH_INFO']) && $_SERVER['PATH_INFO'] !== '' ? $_SERVER['PATH_INFO'] : '/';

function kk_json($code, $data) {
    http_response_code($code);
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    echo json_encode($data, JSON_UNESCAPED_UNICODE);
    exit;
}

function kk_get_json($url) {
    $ch = curl_init($url);
    curl_setopt_array($ch, array(CURLOPT_RETURNTRANSFER => true, CURLOPT_TIMEOUT => 12, CURLOPT_CONNECTTIMEOUT => 6,
        CURLOPT_HTTPHEADER => array('User-Agent: kkansen/1.0')));
    $r = curl_exec($ch);
    $code = curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
    curl_close($ch);
    return ($r === false || $code >= 400) ? null : json_decode($r, true);
}


/** 点（経度・緯度）が入る区域の名前。geojson は書き出したファイル（manifest の /static/<name>.geojson）を読む */
function kk_where($dir, $name, $lon, $lat) {
    $man = json_decode((string)@file_get_contents($dir . '/manifest.json'), true);
    $f = $man['files']['/static/' . $name . '.geojson']['f'] ?? null;
    if (!$f) { return null; }
    $g = json_decode((string)@file_get_contents($dir . '/' . $f), true);
    foreach (($g['features'] ?? array()) as $ft) {
        $geom = $ft['geometry'];
        $polys = $geom['type'] === 'Polygon' ? array($geom['coordinates']) : $geom['coordinates'];
        foreach ($polys as $poly) {
            if (kk_in_ring($lon, $lat, $poly[0])) {
                $hole = false;
                for ($i = 1; $i < count($poly); $i++) { if (kk_in_ring($lon, $lat, $poly[$i])) { $hole = true; break; } }
                if (!$hole) { return $ft['properties']['name'] ?? null; }
            }
        }
    }
    return null;
}

function kk_in_ring($x, $y, $ring) {
    $in = false; $n = count($ring);
    for ($i = 0, $j = $n - 1; $i < $n; $j = $i++) {
        $xi = $ring[$i][0]; $yi = $ring[$i][1]; $xj = $ring[$j][0]; $yj = $ring[$j][1];
        if ((($yi > $y) !== ($yj > $y)) && ($x < ($xj - $xi) * ($y - $yi) / (($yj - $yi) ?: 1e-12) + $xi)) { $in = !$in; }
    }
    return $in;
}

// ---- 住所か現在地 → 都道府県（名古屋市なら区）。app/main.py の api_lookup と同じ答え方 ----
if ($path === '/api/lookup') {
    $prefs = array('北海道','青森県','岩手県','宮城県','秋田県','山形県','福島県','茨城県','栃木県','群馬県','埼玉県','千葉県','東京都','神奈川県',
        '新潟県','富山県','石川県','福井県','山梨県','長野県','岐阜県','静岡県','愛知県','三重県','滋賀県','京都府','大阪府','兵庫県','奈良県',
        '和歌山県','鳥取県','島根県','岡山県','広島県','山口県','徳島県','香川県','愛媛県','高知県','福岡県','佐賀県','長崎県','熊本県','大分県',
        '宮崎県','鹿児島県','沖縄県');
    $wards = array('千種','東','北','西','中村','中','昭和','瑞穂','熱田','中川','港','南','守山','緑','名東','天白');
    $q = trim((string)($_GET['q'] ?? ''));
    $lat = isset($_GET['lat']) && $_GET['lat'] !== '' ? (float)$_GET['lat'] : null;
    $lon = isset($_GET['lon']) && $_GET['lon'] !== '' ? (float)$_GET['lon'] : null;
    $pref = null; $ward = null;
    if ($q !== '') {
        $res = kk_get_json('https://msearch.gsi.go.jp/address-search/AddressSearch?q=' . rawurlencode($q));
        if ($res === null) { kk_json(502, array('error' => '住所の検索に失敗しました。少し待ってからもう一度お試しください')); }
        if (!$res) { kk_json(404, array('error' => 'その住所が見つかりませんでした。市区町村名から入れてください')); }
        list($lon, $lat) = $res[0]['geometry']['coordinates'];
        // 住所検索の結果の文字列（愛知県名古屋市南区…）から読む。逆ジオコーダは止まることがあるので頼らない
        $title = (string)($res[0]['properties']['title'] ?? '');
        foreach ($prefs as $p) { if (strpos($title, $p) === 0) { $pref = $p; break; } }
        if (preg_match('/名古屋市(千種|東|北|西|中村|中|昭和|瑞穂|熱田|中川|港|南|守山|緑|名東|天白)区/u', $title, $m)) { $ward = $m[1]; }
    }
    if ($lat === null || $lon === null) { kk_json(400, array('error' => '住所か現在地を入れてください')); }
    if ($pref === null) {
        // 現在地、または文字列で読めなかったとき：都道府県・名古屋市の区の境界（kkansen_static の geojson）で、点がどこに入るかを見る
        $pref = kk_where(__DIR__ . '/kkansen_static', 'pref', $lon, $lat);
        if ($pref === '愛知県' && $ward === null) {
            $w = kk_where(__DIR__ . '/kkansen_static', 'nagoya_wards', $lon, $lat);
            if ($w) { $ward = preg_replace('/区$/u', '', $w); }
        }
    }
    if (!$pref) { kk_json(404, array('error' => '日本国内の場所を入れてください')); }
    $pi = array_search($pref, $prefs, true);
    $out = array('lat' => $lat, 'lon' => $lon, 'pref' => $pref, 'pref_code' => str_pad((string)($pi + 1), 2, '0', STR_PAD_LEFT), 'ward' => null);
    if ($ward !== null && $pref === '愛知県') {
        $man = json_decode((string)@file_get_contents(__DIR__ . '/kkansen_static/manifest.json'), true);
        $out['ward'] = $ward;
        $out['ward_slug'] = $man['ward_slug'][$ward] ?? null;
    }
    kk_json(200, $out);
}

// ---- MCP だけは当社のサーバーへ中継する（止まっていれば、待たせずに返す） ----
if ($path === '/mcp') {
    if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
        header('Allow: POST');
        kk_json(405, array('error' => 'POST で JSON-RPC を送ってください。使い方: https://kurage.exbridge.jp/kkansen.php/about#mcp'));
    }
    $down = array('jsonrpc' => '2.0', 'id' => null, 'error' => array('code' => -32000, 'message' => 'MCP はいま使えません。少し時間をおいてお試しください（画面とデータは https://kurage.exbridge.jp/kkansen.php/ で見られます）'));
    if ($BACKEND === '') { kk_json(503, $down); }
    $ch = curl_init($BACKEND . '/mcp');
    curl_setopt_array($ch, array(CURLOPT_POST => true, CURLOPT_POSTFIELDS => file_get_contents('php://input'), CURLOPT_RETURNTRANSFER => true,
        CURLOPT_CONNECTTIMEOUT => 4, CURLOPT_TIMEOUT => 25, CURLOPT_HTTPHEADER => array('Content-Type: application/json')));
    $r = curl_exec($ch);
    $code = curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
    curl_close($ch);
    if ($r === false || $code >= 500 || $code === 0) { kk_json(503, $down); }
    http_response_code($code);
    header('Content-Type: application/json; charset=utf-8');
    echo $r;
    exit;
}

// ---- それ以外は、書き出したファイルを返す ----
$man = json_decode((string)@file_get_contents($DIR . '/manifest.json'), true);
if (!$man) { http_response_code(503); header('Content-Type: text/plain; charset=utf-8'); echo '感染症マップを準備しています。少し時間をおいてお試しください'; exit; }
$keep = $man['params'][$path] ?? array();
$parts = array();
foreach ($keep as $k) {
    if (isset($_GET[$k]) && $_GET[$k] !== '') { $parts[] = $k . '=' . $_GET[$k]; }
}
$key = $path . ($parts ? '?' . implode('&', $parts) : '');
$hit = $man['files'][$key] ?? ($man['files'][$path] ?? null);
$status = 200;
if (!$hit) { $hit = $man['files']['__404__']; $status = 404; }
$body = (string)@file_get_contents($DIR . '/' . $hit['f']);
http_response_code($status);
header('Content-Type: ' . $hit['t']);
header('Cache-Control: public, max-age=300');
if (stripos($hit['t'], 'text/html') !== false) {
    // 計測（kurage 版 simpletrack）と再販パートナー募集の枠を、HTML にだけ差し込む（中継していたときと同じ）
    $tag = '<script>(function(){var s=document.createElement("script");s.src="https://kurage.exbridge.jp/simpletrack.php?url="+encodeURIComponent(location.href)+"&ref="+encodeURIComponent(document.referrer);s.async=true;document.head.appendChild(s)})();</script>'
         . '<script src="https://kurage.exbridge.jp/partner-bar.js" defer></script>';
    $body = str_replace('</head>', $tag . '</head>', $body);
}
if ($_SERVER['REQUEST_METHOD'] !== 'HEAD') { echo $body; }
