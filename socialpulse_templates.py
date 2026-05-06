"""
SocialPulse HyperFrame Templates — Lead Gen Agnostique

Templates HTML/GSAP pour contenu vidéo lead gen.
Aucune référence compliance, RGPD, Cortex.
"""
import uuid

BRAND = {
    "primary": "#6366f1",   # indigo
    "accent": "#818cf8",    # indigo light
    "dark": "#0a0e17",      # dark bg
    "text": "#f0f2f5",
    "text2": "#94a3b8",
    "green": "#10b981",
    "amber": "#f59e0b",
    "red": "#ef4444",
}

GSAP_CDN = "https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"

ICONS = {
    "comptable": "📊", "avocat": "⚖️", "sante": "🏥",
    "immobilier": "🏠", "tech": "🚀", "rh": "👥",
    "btp": "🏗️", "marketing": "📣", "restaurant": "🍽️", "formation": "🎓",
}

SIGNALS = {
    "comptable": ["Hiring", "Migration", "Fusion", "Expansion"],
    "avocat": ["Recrutement", "Nouveau bureau", "Spécialisation", "Croissance"],
    "sante": ["Extension", "IRM", "Recrutement", "Déménagement"],
    "immobilier": ["Ouverture", "Négociateur", "Mandats", "Zone"],
    "tech": ["Seed Round", "CTO", "Lancement", "Scale-up"],
    "rh": ["Consultant", "Antenne", "Digitalisation", "Corporate"],
    "btp": ["Grand projet", "Chef projet", "Zone", "ISO"],
    "marketing": ["Client corporate", "Chef projet", "Spécialisation", "Vidéo"],
    "restaurant": ["Ouverture", "Michelin", "Terrasse", "Chef étoilé"],
    "formation": ["Accréditation", "Formateur", "E-learning", "Catalogue"],
}


def _comp_id():
    return f"sp-{uuid.uuid4().hex[:8]}"


def lead_card_html(args: dict) -> str:
    """Lead card vidéo — hook → signal → company → CTA"""
    company = args.get("company_name", "Entreprise")
    vertical = args.get("vertical", "tech")
    signal = args.get("signal_type", "Signal d'achat détecté")
    duration = args.get("duration", 10)
    fmt = args.get("format", "9:16")
    brand = args.get("brand_color", BRAND["primary"])
    icon = ICONS.get(vertical, "⚡")
    score = args.get("score", 87)

    w, h = ("1080", "1920") if fmt == "9:16" else ("1920", "1080")
    sig = SIGNALS.get(vertical, ["Growth", "Hiring", "Expansion", "Funding"])

    return f'''<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<script src="{GSAP_CDN}"></script>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@400;700&display=swap');
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ width: {w}px; height: {h}px; overflow: hidden; background: {BRAND["dark"]};
    font-family: 'Inter', sans-serif; color: {BRAND["text"]}; }}

  .progress {{ position: absolute; top: 0; left: 0; right: 0; height: 4px; z-index: 100; }}
  .progress-fill {{ height: 100%; width: 0%; background: linear-gradient(90deg, {brand}, {BRAND["accent"]}); }}

  .scene {{ position: absolute; top: 120px; left: 40px; right: 80px; bottom: 200px; }}
  #s1 {{ z-index: 1; display: flex; flex-direction: column; justify-content: center; align-items: center; }}
  #s2 {{ z-index: 2; opacity: 0; display: flex; flex-direction: column; justify-content: center; padding: 40px; }}
  #s3 {{ z-index: 3; opacity: 0; display: flex; flex-direction: column; justify-content: center; align-items: center; }}

  .hook-badge {{ font-size: 13px; font-weight: 800; text-transform: uppercase; letter-spacing: 4px;
    color: {BRAND["green"]}; background: rgba(16,185,129,.12); padding: 10px 24px;
    border-radius: 8px; border: 1px solid rgba(16,185,129,.2); }}
  .hook-title {{ font-size: 48px; font-weight: 900; text-align: center; margin-top: 28px; line-height: 1.1; letter-spacing: -1px; }}
  .hook-title .accent {{ color: {brand}; }}
  .hook-sub {{ font-size: 15px; color: {BRAND["text2"]}; margin-top: 16px; font-weight: 500; }}

  .card {{ background: rgba(17,24,39,.85); border: 1px solid rgba(255,255,255,.08);
    border-radius: 20px; padding: 36px 40px; backdrop-filter: blur(10px); }}
  .card-top {{ display: flex; align-items: center; gap: 16px; }}
  .card-icon {{ font-size: 44px; }}
  .card-name {{ font-size: 30px; font-weight: 800; letter-spacing: -.5px; }}
  .card-vertical {{ font-size: 12px; color: {brand}; font-weight: 700; text-transform: uppercase; letter-spacing: 2px; margin-top: 4px; }}
  .card-divider {{ height: 1px; background: rgba(255,255,255,.06); margin: 24px 0; }}
  .card-signal {{ display: flex; align-items: center; gap: 8px; font-size: 16px; font-weight: 700; }}
  .card-signal .icon {{ font-size: 20px; }}

  .terminal {{ background: rgba(17,24,39,.9); border: 1px solid rgba(255,255,255,.1);
    border-radius: 14px; padding: 16px 20px; margin-top: 20px; }}
  .terminal-dots {{ display: flex; gap: 6px; margin-bottom: 10px; }}
  .terminal-dot {{ width: 10px; height: 10px; border-radius: 50%; }}
  .terminal-content {{ font-family: 'JetBrains Mono', monospace; font-size: 12px; color: {BRAND["text2"]}; line-height: 1.8; }}
  .terminal-content .hl {{ color: {brand}; font-weight: 700; }}
  .terminal-content .green {{ color: {BRAND["green"]}; }}

  .keywords {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 20px; }}
  .keyword {{ font-size: 13px; font-weight: 700; padding: 8px 16px; border-radius: 10px;
    background: rgba(99,102,241,.1); color: {brand}; border: 1px solid rgba(99,102,241,.2); }}

  .score {{ font-size: 100px; font-weight: 900; color: {brand}; font-variant-numeric: tabular-nums; }}
  .score-max {{ font-size: 24px; color: {BRAND["text2"]}; font-weight: 400; }}
  .score-bar-bg {{ width: 70%; height: 10px; background: rgba(255,255,255,.06); border-radius: 5px; margin-top: 24px; overflow: hidden; }}
  .score-bar {{ height: 100%; width: 0%; border-radius: 5px; background: linear-gradient(90deg, {BRAND["amber"]}, {brand}); }}
  .score-label {{ font-size: 12px; color: {BRAND["text2"]}; text-transform: uppercase; letter-spacing: 2px; margin-top: 20px; }}

  .cta-logo {{ font-size: 48px; font-weight: 900; color: {brand}; }}
  .cta-name {{ font-size: 26px; font-weight: 800; margin-top: 8px; }}
  .cta-tag {{ font-size: 16px; color: {BRAND["text2"]}; margin-top: 12px; text-align: center; }}
  .cta-btn {{ margin-top: 24px; font-size: 17px; font-weight: 700; color: {BRAND["dark"]};
    background: {brand}; padding: 16px 40px; border-radius: 14px; }}
  .cta-url {{ margin-top: 12px; font-size: 13px; color: {BRAND["text2"]}; }}
</style>
</head>
<body>
  <div class="progress"><div class="progress-fill" id="pFill"></div></div>

  <div class="scene" id="s1">
    <div class="hook-badge" id="hookBadge">⚡ SIGNAL DÉTECTÉ</div>
    <div class="hook-title" id="hookTitle">Ce prospect est <span class="accent">prêt à acheter</span></div>
    <div class="hook-sub" id="hookSub">SocialPulse — Pipeline lead gen automatisé</div>
  </div>

  <div class="scene" id="s2">
    <div class="card" id="card">
      <div class="card-top">
        <div class="card-icon" id="cardIcon">{icon}</div>
        <div>
          <div class="card-name" id="cardName">{company}</div>
          <div class="card-vertical" id="cardVert">{vertical.upper()}</div>
        </div>
      </div>
      <div class="card-divider"></div>
      <div class="card-signal" id="cardSignal">
        <span class="icon">🟢</span> {signal}
      </div>
      <div class="terminal" id="terminal">
        <div class="terminal-dots">
          <div class="terminal-dot" style="background:#ff5f57"></div>
          <div class="terminal-dot" style="background:#febc2e"></div>
          <div class="terminal-dot" style="background:#28c840"></div>
        </div>
        <div class="terminal-content">
          > <span class="hl">socialpulse score</span> --vertical {vertical} --company "{company}"<br>
          > signal detected: <span class="green">{signal}</span><br>
          > lead score: <span class="hl">{score}/100</span> — QUALIFIED
        </div>
      </div>
      <div class="keywords" id="keywords">
        {"".join(f'<div class="keyword" id="kw{i}">{s}</div>' for i, s in enumerate(sig))}
      </div>
    </div>
  </div>

  <div class="scene" id="s3">
    <div class="score-label" id="scoreLabel">Lead Score</div>
    <div><span class="score" id="scoreNum">0</span><span class="score-max"> /100</span></div>
    <div class="score-bar-bg"><div class="score-bar" id="scoreBar"></div></div>
    <div class="cta-logo" id="ctaLogo" style="margin-top:32px">⚡</div>
    <div class="cta-name" id="ctaName">SocialPulse</div>
    <div class="cta-tag" id="ctaTag">De la donnée publique au lead qualifié</div>
    <div class="cta-btn" id="ctaBtn">Essai gratuit →</div>
    <div class="cta-url" id="ctaUrl">socialpulse.io</div>
  </div>

  <script>
    var tl = gsap.timeline();
    window.__tl = tl;
    var dur = {duration};

    tl.to("#pFill", {{ width: "100%", duration: dur, ease: "none" }}, 0);

    // Scene 1: Hook (0→3s)
    tl.fromTo("#hookBadge", {{ scale: .8, opacity: 0 }}, {{ scale: 1, opacity: 1, duration: .5, ease: "back.out(1.7)" }}, .2);
    tl.fromTo("#hookTitle", {{ y: 40, opacity: 0 }}, {{ y: 0, opacity: 1, duration: .7, ease: "power3.out" }}, .5);
    tl.fromTo("#hookSub", {{ opacity: 0 }}, {{ opacity: 1, duration: .4 }}, 1);
    tl.to("#s1", {{ opacity: 0, duration: .4 }}, 2.8);

    // Scene 2: Card (3→7s)
    tl.set("#s2", {{ opacity: 1 }}, 2.8);
    tl.fromTo("#card", {{ y: 60, opacity: 0, scale: .95 }}, {{ y: 0, opacity: 1, scale: 1, duration: .8, ease: "power3.out" }}, 3);
    tl.fromTo("#terminal", {{ y: 20, opacity: 0 }}, {{ y: 0, opacity: 1, duration: .5 }}, 3.6);
    tl.fromTo(".keyword", {{ y: 15, opacity: 0 }}, {{ y: 0, opacity: 1, duration: .3, stagger: .1 }}, 4.2);
    tl.to("#s2", {{ opacity: 0, duration: .4 }}, 6.8);

    // Scene 3: Score + CTA (7→end)
    tl.set("#s3", {{ opacity: 1 }}, 6.8);
    tl.fromTo("#scoreLabel", {{ y: -20, opacity: 0 }}, {{ y: 0, opacity: 1, duration: .4 }}, 7);
    tl.fromTo("#scoreNum", {{ scale: .5, opacity: 0 }}, {{ scale: 1, opacity: 1, duration: .6, ease: "back.out(1.5)" }}, 7.2);
    tl.to("#scoreNum", {{ innerText: {score}, duration: 1.5, snap: {{ innerText: 1 }}, ease: "power2.out" }}, 7.3);
    tl.to("#scoreBar", {{ width: "{score}%", duration: 1.5, ease: "power2.out" }}, 7.3);
    tl.fromTo("#ctaLogo", {{ scale: 0 }}, {{ scale: 1, duration: .5, ease: "back.out(2)" }}, 8.5);
    tl.fromTo("#ctaName", {{ y: 20, opacity: 0 }}, {{ y: 0, opacity: 1, duration: .4 }}, 8.7);
    tl.fromTo("#ctaTag", {{ opacity: 0 }}, {{ opacity: 1, duration: .4 }}, 9);
    tl.fromTo("#ctaBtn", {{ scale: .9, opacity: 0 }}, {{ scale: 1, opacity: 1, duration: .4, ease: "back.out(1.5)" }}, 9.3);
    tl.fromTo("#ctaUrl", {{ opacity: 0 }}, {{ opacity: 1, duration: .3 }}, 9.6);
  </script>
</body>
</html>'''


def listicle_html(args: dict) -> str:
    """Listicle N signaux d'achat"""
    items = args.get("items", ["Signal #1", "Signal #2", "Signal #3"])
    truncated = items[:5]
    vertical = args.get("vertical", "tech")
    duration = args.get("duration", 12)
    fmt = args.get("format", "9:16")
    brand = args.get("brand_color", BRAND["primary"])
    icon = ICONS.get(vertical, "⚡")

    w, h = ("1080", "1920") if fmt == "9:16" else ("1920", "1080")
    scene_dur = (duration - 3) / len(truncated)
    cta_start = duration - 3.0

    scenes_html = ""
    scenes_css = ""
    scenes_anim = ""

    for i, item in enumerate(truncated):
        s_start = i * scene_dur
        s_end = (i + 1) * scene_dur

        scenes_css += f'''
    #s_item{i} {{ z-index: {i+2}; opacity: 0; }}
    .item-outer{i} {{ position: absolute; top: 120px; left: 40px; right: 80px; bottom: 200px;
      display: flex; flex-direction: column; justify-content: center; }}
    .item-card{i} {{ background: rgba(17,24,39,.85); border: 1px solid rgba(255,255,255,.08);
      border-radius: 20px; padding: 40px; backdrop-filter: blur(10px); }}
    .item-num{i} {{ font-size: 14px; font-weight: 800; color: {brand};
      background: rgba(99,102,241,.15); padding: 8px 16px; border-radius: 10px;
      display: inline-block; margin-bottom: 20px; }}
    .item-text{i} {{ font-size: 26px; font-weight: 700; line-height: 1.3; }}
    .item-icon{i} {{ font-size: 32px; margin-bottom: 16px; }}
'''
        scenes_html += f'''
    <div class="scene" id="s_item{i}">
      <div class="item-outer{i}">
        <div class="item-card{i}">
          <div class="item-icon{i}" id="iIcon{i}">{icon}</div>
          <div class="item-num{i}" id="iNum{i}">{i+1} / {len(truncated)}</div>
          <div class="item-text{i}" id="iText{i}">{item}</div>
        </div>
      </div>
    </div>'''

        scenes_anim += f'''
    tl.set("#s_item{i}", {{ opacity: 1 }}, {s_start});
    tl.fromTo("#iIcon{i}", {{ scale: 0, opacity: 0 }}, {{ scale: 1, opacity: 1, duration: .4, ease: "back.out(2)" }}, {s_start}+.1);
    tl.fromTo("#iNum{i}", {{ x: -30, opacity: 0 }}, {{ x: 0, opacity: 1, duration: .4, ease: "power3.out" }}, {s_start}+.3);
    tl.fromTo("#iText{i}", {{ y: 30, opacity: 0 }}, {{ y: 0, opacity: 1, duration: .5, ease: "power3.out" }}, {s_start}+.5);
    tl.to("#s_item{i}", {{ opacity: 0, duration: .35, ease: "power2.inOut" }}, {s_end}-.35);
'''

    return f'''<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<script src="{GSAP_CDN}"></script>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ width: {w}px; height: {h}px; overflow: hidden; background: {BRAND["dark"]};
    font-family: 'Inter', sans-serif; color: {BRAND["text"]}; }}
  .progress {{ position: absolute; top: 0; left: 0; right: 0; height: 4px; z-index: 100; }}
  .progress-fill {{ height: 100%; width: 0%; background: linear-gradient(90deg, {brand}, {BRAND["accent"]}); }}
  .scene {{ position: absolute; top: 0; left: 0; width: 100%; height: 100%; }}
  #s_header {{ z-index: 1; }}
  #s_cta {{ z-index: {len(truncated)+2}; opacity: 0; }}
  {scenes_css}
  .header-section {{ position: absolute; top: 120px; left: 40px; right: 80px; bottom: 200px;
    display: flex; flex-direction: column; justify-content: center; }}
  .header-icon {{ font-size: 40px; }}
  .header-title {{ font-size: 36px; font-weight: 900; margin-top: 16px; letter-spacing: -.5px; }}
  .header-sub {{ font-size: 14px; color: {BRAND["text2"]}; margin-top: 8px; font-weight: 500; }}
  .cta-section {{ position: absolute; top: 120px; left: 40px; right: 80px; bottom: 200px;
    display: flex; flex-direction: column; justify-content: center; align-items: center; }}
  .cta-logo {{ font-size: 48px; font-weight: 900; color: {brand}; }}
  .cta-btn {{ margin-top: 24px; font-size: 17px; font-weight: 700; color: {BRAND["dark"]};
    background: {brand}; padding: 16px 40px; border-radius: 14px; }}
  .cta-url {{ margin-top: 12px; font-size: 13px; color: {BRAND["text2"]}; }}
</style>
</head>
<body>
  <div class="progress"><div class="progress-fill" id="pFill"></div></div>
  <div class="scene" id="s_header">
    <div class="header-section">
      <div class="header-icon" id="hIcon">{icon}</div>
      <div class="header-title" id="hTitle">{len(truncated)} signaux pour {vertical}</div>
      <div class="header-sub" id="hSub">SocialPulse — Lead Scoring Automatisé</div>
    </div>
  </div>
  {scenes_html}
  <div class="scene" id="s_cta">
    <div class="cta-section">
      <div class="cta-logo" id="ctaLogo">⚡</div>
      <div style="font-size:24px;font-weight:800;margin-top:8px" id="ctaTitle">SocialPulse</div>
      <div class="cta-btn" id="ctaBtn">Essai gratuit →</div>
      <div class="cta-url" id="ctaUrl">socialpulse.io</div>
    </div>
  </div>
  <script>
    var tl = gsap.timeline(); window.__tl = tl;
    tl.to("#pFill", {{ width: "100%", duration: {duration}, ease: "none" }}, 0);
    tl.fromTo("#hIcon", {{ scale: 0, opacity: 0 }}, {{ scale: 1, opacity: 1, duration: .5, ease: "back.out(2)" }}, .2);
    tl.fromTo("#hTitle", {{ y: 30, opacity: 0 }}, {{ y: 0, opacity: 1, duration: .6, ease: "power3.out" }}, .4);
    tl.fromTo("#hSub", {{ opacity: 0 }}, {{ opacity: 1, duration: .4 }}, .8);
    tl.to("#s_header", {{ opacity: 0, duration: .35 }}, 1.8);
    {scenes_anim}
    tl.set("#s_cta", {{ opacity: 1 }}, {cta_start});
    tl.fromTo("#ctaLogo", {{ scale: 0 }}, {{ scale: 1, duration: .5, ease: "back.out(2)" }}, {cta_start}+.1);
    tl.fromTo("#ctaTitle", {{ y: 15, opacity: 0 }}, {{ y: 0, opacity: 1, duration: .4 }}, {cta_start}+.3);
    tl.fromTo("#ctaBtn", {{ scale: .9, opacity: 0 }}, {{ scale: 1, opacity: 1, duration: .4, ease: "back.out(1.5)" }}, {cta_start}+.6);
    tl.fromTo("#ctaUrl", {{ opacity: 0 }}, {{ opacity: 1, duration: .3 }}, {cta_start}+.9);
  </script>
</body>
</html>'''


def compose(args: dict) -> dict:
    """Compose a SocialPulse video template"""
    template = args.get("template", "lead_card")
    comp_id = _comp_id()

    template_map = {
        "lead_card": lead_card_html,
        "listicle": listicle_html,
    }

    generator = template_map.get(template, lead_card_html)
    html_content = generator(args)

    return {
        "composition_id": comp_id,
        "template": template,
        "status": "composed",
        "format": args.get("format", "9:16"),
        "duration": args.get("duration", 10),
        "html_length": len(html_content),
        "html_preview": html_content[:500] + "..." if len(html_content) > 500 else html_content,
        "html_full": html_content,
        "render_hint": "Render via Puppeteer + FFmpeg ou hyperframe_render",
        "brand": "SocialPulse",
        "vertical": args.get("vertical", "unknown"),
    }
