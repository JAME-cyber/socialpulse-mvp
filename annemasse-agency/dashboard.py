#!/usr/bin/env python3
"""
SocialPulse Annemasse — Dashboard Proof of Concept
Génère un rapport HTML interactif du pipeline.
"""

import json
from pathlib import Path
from collections import Counter
from datetime import datetime

BASE = Path(__file__).parent
STATE_DIR = BASE / "state"

def generate_dashboard():
    queue = json.loads((STATE_DIR / "lead-queue.json").read_text())
    stats = json.loads((STATE_DIR / "stats.json").read_text())
    
    total = len(queue)
    no_site = [l for l in queue if l.get('website_status') == 'none']
    hot = [l for l in no_site if l.get('score', 0) >= 80]
    warm = [l for l in no_site if 60 <= l.get('score', 0) < 80]
    
    # Sector data
    sector_data = {}
    for l in queue:
        s = l.get('sector', '?')
        if s not in sector_data:
            sector_data[s] = {'total': 0, 'no_site': 0, 'hot': 0, 'icon': l.get('sector_icon', '⚡'), 'channel': l.get('channel', 'email')}
        sector_data[s]['total'] += 1
        if l.get('website_status') == 'none':
            sector_data[s]['no_site'] += 1
        if l.get('score', 0) >= 80 and l.get('website_status') == 'none':
            sector_data[s]['hot'] += 1
    
    # City data
    city_data = {}
    for l in queue:
        c = l.get('city', 'Annemasse')
        if c not in city_data:
            city_data[c] = {'total': 0, 'no_site': 0}
        city_data[c]['total'] += 1
        if l.get('website_status') != 'has_website':
            city_data[c]['no_site'] += 1
    
    # Channel breakdown
    channels = {'instagram': 0, 'email': 0, 'sms': 0, 'linkedin': 0}
    for l in hot:
        ch = l.get('channel', 'email')
        if ch in channels:
            channels[ch] += 1
    
    # Build HTML
    sector_rows = ""
    for s in sorted(sector_data.keys(), key=lambda x: sector_data[x]['hot'], reverse=True):
        d = sector_data[s]
        if d['total'] < 3: continue
        pct = d['no_site'] * 100 // max(d['total'], 1)
        hot_pct = d['hot'] * 100 // max(d['total'], 1)
        channel_icons = {'instagram': '📸', 'email': '📧', 'sms': '📱', 'linkedin': '💼'}
        ch_icon = channel_icons.get(d['channel'], '📧')
        sector_rows += f"""
        <tr>
            <td>{d['icon']} {s}</td>
            <td>{d['total']}</td>
            <td>{d['no_site']} <span class="pct">({pct}%)</span></td>
            <td><span class="hot">{d['hot']}</span> <span class="pct">({hot_pct}%)</span></td>
            <td>{ch_icon} {d['channel']}</td>
        </tr>"""
    
    city_rows = ""
    for c in sorted(city_data.keys(), key=lambda x: city_data[x]['total'], reverse=True):
        d = city_data[c]
        pct = d['no_site'] * 100 // max(d['total'], 1)
        city_rows += f"""
        <tr>
            <td>📍 {c}</td>
            <td>{d['total']}</td>
            <td>{d['no_site']}</td>
            <td>{pct}%</td>
        </tr>"""
    
    # Top hot leads
    lead_rows = ""
    for i, l in enumerate(sorted(hot, key=lambda x: x.get('score', 0), reverse=True)[:30]):
        channel_icons = {'instagram': '📸', 'email': '📧', 'sms': '📱', 'linkedin': '💼'}
        ch = channel_icons.get(l.get('channel', 'email'), '📧')
        status_class = 'approved' if l.get('status') == 'approved' else 'flagged' if l.get('status') == 'flagged' else l.get('status', 'discovered')
        lead_rows += f"""
        <tr>
            <td>{i+1}</td>
            <td class="name">{l.get('sector_icon', '⚡')} {l.get('name', '?')}</td>
            <td>{l.get('sector', '?')}</td>
            <td>{l.get('city', '?')}</td>
            <td><span class="score">{l.get('score', 0)}</span></td>
            <td>{ch} {l.get('channel', '?')}</td>
            <td><span class="status {status_class}">{status_class}</span></td>
        </tr>"""
    
    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SocialPulse Annemasse — Dashboard</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
:root{{--bg:#0a0e17;--bg2:#111827;--bg3:#1a2332;--border:rgba(255,255,255,.06);--text:#f0f2f5;--text2:rgba(240,242,245,.6);--pulse:#6366f1;--pulse2:#818cf8;--green:#10b981;--amber:#f59e0b;--red:#ef4444}}
body{{font-family:'Inter',system-ui,sans-serif;background:var(--bg);color:var(--text);padding:40px 24px;max-width:1400px;margin:0 auto}}
h1{{font-size:32px;font-weight:900;letter-spacing:-1px;margin-bottom:8px}}
h1 .accent{{color:var(--pulse2)}}
.subtitle{{font-size:14px;color:var(--text2);margin-bottom:40px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;margin-bottom:40px}}
.card{{background:var(--bg2);border:1px solid var(--border);border-radius:16px;padding:24px}}
.card-label{{font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:1px;color:var(--text2);margin-bottom:8px}}
.card-value{{font-size:36px;font-weight:900;letter-spacing:-1px}}
.card-value.green{{color:var(--green)}}
.card-value.amber{{color:var(--amber)}}
.card-value.pulse{{color:var(--pulse2)}}
.card-sub{{font-size:11px;color:var(--text2);margin-top:4px}}
section{{margin-bottom:40px}}
h2{{font-size:20px;font-weight:800;margin-bottom:16px;display:flex;align-items:center;gap:8px}}
table{{width:100%;border-collapse:collapse;background:var(--bg2);border:1px solid var(--border);border-radius:12px;overflow:hidden}}
th{{text-align:left;padding:12px 16px;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:var(--text2);background:rgba(255,255,255,.03);border-bottom:1px solid var(--border)}}
td{{padding:10px 16px;font-size:13px;border-bottom:1px solid var(--border)}}
tr:last-child td{{border-bottom:none}}
tr:hover{{background:rgba(99,102,241,.05)}}
.pct{{font-size:11px;color:var(--text2)}}
.hot{{color:var(--green);font-weight:800}}
.score{{color:var(--pulse2);font-weight:800;font-size:15px}}
.status{{display:inline-block;padding:3px 10px;border-radius:6px;font-size:11px;font-weight:700}}
.status.discovered{{background:rgba(99,102,241,.1);color:var(--pulse2)}}
.status.scored{{background:rgba(245,158,11,.1);color:var(--amber)}}
.status.diagnosed{{background:rgba(16,185,129,.1);color:var(--green)}}
.status.approved{{background:rgba(16,185,129,.2);color:var(--green)}}
.status.flagged{{background:rgba(239,68,68,.1);color:var(--red)}}
.status.gele{{background:rgba(239,68,68,.15);color:var(--red)}}
.name{{font-weight:700}}
.two-col{{display:grid;grid-template-columns:1fr 1fr;gap:24px}}
@media(max-width:768px){{.two-col{{grid-template-columns:1fr}}.grid{{grid-template-columns:repeat(2,1fr)}}}}
.channel-bar{{display:flex;gap:8px;margin-top:16px}}
.channel-pill{{padding:6px 14px;border-radius:8px;font-size:12px;font-weight:700;background:rgba(255,255,255,.05);border:1px solid var(--border)}}
.channel-pill .num{{margin-left:4px;color:var(--pulse2)}}
.cost{{margin-top:8px;font-size:12px;color:var(--green)}}
footer{{margin-top:40px;padding-top:20px;border-top:1px solid var(--border);font-size:11px;color:var(--text2)}}
</style>
</head>
<body>

<h1>SocialPulse <span class="accent">Annemasse</span></h1>
<div class="subtitle">🗺️ Agglomération Annemasse · Gaillard · Ville-la-Grand · Saint-Julien | Haute-Savoie (74)</div>

<div class="grid">
  <div class="card">
    <div class="card-label">Leads découverts</div>
    <div class="card-value">{total:,}</div>
    <div class="card-sub">OpenStreetMap · Overpass API</div>
  </div>
  <div class="card">
    <div class="card-label">Sans site web</div>
    <div class="card-value amber">{len(no_site):,}</div>
    <div class="card-sub">{len(no_site)*100//max(total,1)}% des PME · Top prospects</div>
  </div>
  <div class="card">
    <div class="card-label">HOT leads (80+)</div>
    <div class="card-value green">{len(hot):,}</div>
    <div class="card-sub">Prêts à prospector</div>
  </div>
  <div class="card">
    <div class="card-label">Coût pipeline</div>
    <div class="card-value pulse">$0</div>
    <div class="card-sub">100% open-source · vs $480/mois tweet</div>
  </div>
</div>

<div class="channel-bar">
  <div class="channel-pill">📸 Instagram <span class="num">{channels.get('instagram',0)}</span></div>
  <div class="channel-pill">📧 Email <span class="num">{channels.get('email',0)}</span></div>
  <div class="channel-pill">📱 SMS <span class="num">{channels.get('sms',0)}</span></div>
  <div class="channel-pill">💼 LinkedIn <span class="num">{channels.get('linkedin',0)}</span></div>
</div>

<section>
<h2>📊 Matrice Secteur × Opportunité</h2>
<table>
  <tr><th>Secteur</th><th>Total PME</th><th>Sans site</th><th>HOT</th><th>Canal</th></tr>
  {sector_rows}
</table>
</section>

<section>
<h2>📍 Répartition géographique</h2>
<table>
  <tr><th>Ville</th><th>Total</th><th>Sans site</th><th>% sans site</th></tr>
  {city_rows}
</table>
</section>

<section>
<h2>🎯 Top 30 HOT Leads</h2>
<table>
  <tr><th>#</th><th>Commerce</th><th>Secteur</th><th>Ville</th><th>Score</th><th>Canal</th><th>Status</th></tr>
  {lead_rows}
</table>
</section>

<section>
<h2>💰 Unit Economics</h2>
<div class="two-col">
  <div class="card">
    <div class="card-label">Scénario Modéré (3% conversion)</div>
    <div class="card-value green">{int(len(hot)*0.03)} deals</div>
    <div class="cost">CA estimé: {int(len(hot)*0.03)*400:,}€/mois · Coût: 30€/mois · Marge: 99.8%</div>
  </div>
  <div class="card">
    <div class="card-label">Scénario Optimiste (5% conversion)</div>
    <div class="card-value green">{int(len(hot)*0.05)} deals</div>
    <div class="cost">CA estimé: {int(len(hot)*0.05)*400:,}€/mois · Coût: 30€/mois · Marge: 99.9%</div>
  </div>
</div>
</section>

<footer>
  SocialPulse Annemasse Agency v5.0 · 7 agents IA · Haute-Savoie · {datetime.now().strftime('%d/%m/%Y %H:%M')}<br>
  Inspiré de <a href="https://x.com/browomo/status/2051747188787523825" style="color:var(--pulse2)">@browomo</a> — Adapté 100% open-source · Overpass API + OpenRouter + HyperFrame
</footer>

</body>
</html>"""
    
    output = BASE / "output" / "dashboard.html"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html)
    print(f"  ✅ Dashboard: {output}")
    print(f"     Ouvrir: file://{output}")

if __name__ == "__main__":
    generate_dashboard()
