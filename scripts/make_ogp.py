#!/usr/bin/env python3
"""OGP（1200×630）とファビコン。都道府県の形を薄く敷く。  /usr/bin/python3 scripts/make_ogp.py"""
import json, os
from PIL import Image, ImageDraw, ImageFont
R = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); S = os.path.join(R, 'app', 'static')
B = '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc'; N = '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'
im = Image.new('RGB', (1200, 630), (246, 249, 249)); d = ImageDraw.Draw(im)
gj = json.load(open(os.path.join(S, 'pref.geojson')))
COL = [(253, 233, 184), (251, 200, 122), (245, 158, 91), (227, 104, 63), (183, 49, 31)]
def proj(lon, lat): return 640 + (lon - 128) * 26, 600 - (lat - 26) * 30
for i, f in enumerate(gj['features']):
    g = f['geometry']; polys = g['coordinates'] if g['type'] == 'MultiPolygon' else [g['coordinates']]
    for p in polys:
        pts = [proj(x, y) for x, y in p[0]]
        if len(pts) > 2: d.polygon(pts, fill=COL[(i * 7) % 5], outline=(255, 255, 255))
d.rectangle((0, 0, 640, 630), fill=(246, 249, 249))
d.rectangle((0, 0, 1200, 12), fill=(10, 143, 133))
d.text((60, 60), 'Kurage 感染症マップ', font=ImageFont.truetype(B, 34), fill=(7, 117, 109))
d.text((60, 140), 'いま流行っている', font=ImageFont.truetype(B, 60), fill=(18, 32, 47))
d.text((60, 214), '感染症を、地図で', font=ImageFont.truetype(B, 60), fill=(18, 32, 47))
f = ImageFont.truetype(N, 26)
for k, t in enumerate(('インフルエンザ・新型コロナなど19疾患', '全国の都道府県＋名古屋市の区', '名古屋市の学級閉鎖を毎日')):
    d.text((60, 320 + k * 44), '・' + t, font=f, fill=(60, 75, 90))
m = Image.open('/home/kojima/work/kurage_web/images/kurage-mascot-cutout.png').convert('RGBA'); m = m.resize((110, int(110 * m.height / m.width)))
im.paste(m, (60, 630 - m.height - 16), m)
d.text((190, 575), '株式会社エクスブリッジ', font=ImageFont.truetype(N, 22), fill=(93, 107, 122))
im.save(os.path.join(S, 'ogp.png'), optimize=True)
fv = Image.new('RGBA', (64, 64), (0, 0, 0, 0)); fd = ImageDraw.Draw(fv)
fd.rounded_rectangle((0, 0, 63, 63), radius=14, fill=(10, 143, 133)); fd.text((10, 6), '感', font=ImageFont.truetype(B, 42), fill=(255, 255, 255))
fv.save(os.path.join(S, 'favicon.png')); print('ok')
