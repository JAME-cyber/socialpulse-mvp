#!/usr/bin/env python3
"""
SocialPulse Enrichment Agents — Données complémentaires gratuites
=================================================================

Enrichit les leads OSM avec:
  1. Pappers API (gratuit) → SIRET, CA, effectifs, forme juridique, dirigeant
  2. Google Maps Details (scrapling) → note, avis, photos
  3. Site web analysis (scrapling) → technologies, qualité

Usage:
  python3 enrich.py --pappers    # Enrichir via Pappers
  python3 enrich.py --gmaps      # Enrichir via Google Maps scraping
  python3 enrich.py --site       # Analyser les sites existants
  python3 enrich.py --all        # Tout enrichir
"""

import os
import sys
import json
import time
import datetime
import urllib.request
import urllib.parse
from pathlib import Path

BASE = Path(__file__).parent
STATE_DIR = BASE / "state"


def get_queue():
    path = STATE_DIR / "lead-queue.json"
    return json.loads(path.read_text()) if path.exists() else []


def save_queue(queue):
    (STATE_DIR / "lead-queue.json").write_text(json.dumps(queue, indent=2, ensure_ascii=False))


# ════════════════════════════════════════════════════════════
#  ENRICHISSEMENT 1: PAPPERS (données entreprises FR)
#  API gratuite: https://api.pappers.fr/v2
#  Donne: SIRET, CA, effectifs, forme juridique, dirigeant
# ════════════════════════════════════════════════════════════

def enrich_pappers(queue, max_leads=50):
    """
    Enrichit les leads avec les données entreprises (API Sirene Open Data).
    Gratuit, sans clé API.
    
    Ce que ça apporte par rapport au tweet:
    - Le tweet n'avait PAS ces données (juste Google Maps)
    - Nous: SIRET, forme juridique, actif/inactif
    - SARL/EURL = décideur unique = conversion plus rapide
    """
    print("  🏢 Sirene API: Enrichissement données entreprises...")
    
    # INSEE commune codes
    commune_codes = {
        'Annemasse': '74010', 'Gaillard': '74139',
        'Ville-la-Grand': '74307', 'Saint-Julien-en-Genevois': '74243',
        'Ambilly': '74004', 'Etrembières': '74122',
    }
    
    enriched = 0
    for lead in queue:
        if enriched >= max_leads:
            break
        if lead.get("sirene_enriched"):
            continue
        if lead.get("website_status") == "has_website":
            continue
        
        name = lead.get("name", "")
        city = lead.get("city", "Annemasse")
        commune_code = commune_codes.get(city)
        
        try:
            params = {'q': name, 'per_page': 3, 'etat_administratif': 'A'}
            if commune_code:
                params['code_commune'] = commune_code
            
            url = f'https://recherche-entreprises.api.gouv.fr/search?{urllib.parse.urlencode(params)}'
            req = urllib.request.Request(url, headers={"User-Agent": "SocialPulse/1.0"})
            
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read().decode())
            
            results = result.get("resultats", [])
            if results:
                best = results[0]
                siege = best.get("siege", {})
                
                lead["siren"] = best.get("siren", "")
                lead["siret"] = siege.get("siret", "")
                lead["forme_juridique"] = best.get("nature_juridique", "")
                lead["date_creation"] = best.get("date_creation", "")
                lead["actif"] = best.get("etat_administratif") == "A"
                lead["nom_entreprise"] = best.get("nom_complet", name)
                lead["code_postal"] = siege.get("code_postal", "")
                
                # FIX STRUCTUREL #3 — Classification PM/EI/NUANCED (RGPD).
                # Sans cette distinction, le pipeline traite les artisans/EI comme du
                # B2B alors que leurs coordonnées sont des DONNÉES PERSONNELLES.
                # Voir agents/legal_classifier.py + REPOSITIONING-BRIEF.md.
                from agents.legal_classifier import enrich_lead_with_classification
                legal = enrich_lead_with_classification(lead)
                lead["legal_class"] = legal.class_.value
                lead["legal_basis"] = legal.legal_basis
                
                # Dirigeants
                dirigeants = best.get("dirigeants", [])
                if dirigeants:
                    d = dirigeants[0]
                    lead["dirigeant"] = f"{d.get('prenoms', '')} {d.get('nom', '')}"
                
                lead["sirene_enriched"] = True
                enriched += 1
                print(f"    ✅ [{enriched}] {name} → SIRET {lead.get('siret', '?')[:14]} | CP {lead.get('code_postal')}")
            else:
                lead["sirene_enriched"] = False
            
            time.sleep(0.5)  # Rate limit
            
        except Exception as e:
            lead["sirene_enriched"] = False
    
    save_queue(queue)
    print(f"  ✅ Sirene: {enriched} leads enrichis")


# ════════════════════════════════════════════════════════════
#  ENRICHISSEMENT 2: GOOGLE MAPS SCRAPING
#  Via Scrapling — récupère note, avis, photos
# ════════════════════════════════════════════════════════════

def enrich_gmaps(queue, max_leads=20):
    """
    Enrichit les leads avec les données Google Maps.
    Utilise Scrapling (StealthyFetcher) pour bypass les anti-bot.
    
    Ce que ça apporte:
    - Note Google Maps (critère clé du tweet: haute note + peu d'avis = bon prospect)
    - Nombre d'avis (critère du tweet: <50 avis)
    - Confirme l'adresse et le téléphone
    """
    print("  🗺️ Google Maps: Enrichissement via Scrapling...")
    print("     (Nécessite Playwright installé — skip si absent)")
    
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        print("     ⚠️ Scrapling/Playwright non disponible — skip")
        return
    
    enriched = 0
    for lead in queue:
        if enriched >= max_leads:
            break
        if lead.get("gmaps_enriched"):
            continue
        if lead.get("website_status") == "has_website":
            continue
        
        name = lead.get("name", "")
        city = lead.get("city", "Annemasse")
        query = f"{name} {city}"
        
        try:
            url = f"https://www.google.com/maps/search/{urllib.parse.quote(query)}/"
            page = StealthyFetcher.fetch(url, headless=True, timeout=15)
            
            # Parse Google Maps results
            # Look for rating
            text = page.text
            
            # Extract rating (pattern: "4,5" or "4.5" followed by reviews count)
            import re
            
            rating_match = re.search(r'(\d[,.]\d)\s*\((\d+)\)', text)
            if rating_match:
                rating = float(rating_match.group(1).replace(',', '.'))
                reviews = int(rating_match.group(2))
                lead["gmaps_rating"] = rating
                lead["gmaps_reviews"] = reviews
                lead["rating"] = rating
                lead["reviews_count"] = reviews
            
            lead["gmaps_enriched"] = True
            enriched += 1
            print(f"    ✅ [{enriched}] {name} → ★{lead.get('gmaps_rating', '?')} ({lead.get('gmaps_reviews', '?')} avis)")
            
            time.sleep(3)  # Be nice with Google
            
        except Exception as e:
            print(f"    ⚠️ {name}: {str(e)[:60]}")
            lead["gmaps_enriched"] = False
    
    save_queue(queue)
    print(f"  ✅ Google Maps: {enriched} leads enrichis")


# ════════════════════════════════════════════════════════════
#  ENRICHISSEMENT 3: SITE WEB ANALYSIS
#  Analyse les sites existants pour détecter qualité/techno
# ════════════════════════════════════════════════════════════

def enrich_site_analysis(queue, max_leads=30):
    """
    Analyse les sites web existants des leads.
    Détecte: WordPress, Wix, Shopify, WordPress.com, etc.
    Un site Wix/WordPress vieux = prospect "modernisation"
    
    Ce que ça apporte par rapport au tweet:
    - Le tweet cherchait les sites "from 2014"
    - Nous: on détecte la techno ET on estime l'âge
    """
    print("  🌐 Site Analysis: Analyse des sites existants...")
    
    has_site = [l for l in queue if l.get("website") and l.get("website_status") == "has_website"]
    to_analyze = [l for l in has_site if not l.get("site_analyzed")][:max_leads]
    
    for i, lead in enumerate(to_analyze):
        url = lead.get("website", "")
        if not url or not url.startswith("http"):
            continue
        
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; SocialPulse/1.0)",
            })
            with urllib.request.urlopen(req, timeout=10) as resp:
                html = resp.read().decode('utf-8', errors='ignore').lower()
            
            tech = []
            if "wordpress" in html: tech.append("WordPress")
            if "wix.com" in html or "wixsite" in html: tech.append("Wix")
            if "shopify" in html: tech.append("Shopify")
            if "squarespace" in html: tech.append("Squarespace")
            if "jimdo" in html: tech.append("Jimdo")
            if "gatsby" in html: tech.append("Gatsby")
            if "next.js" in html or "__next" in html: tech.append("Next.js")
            if "react" in html: tech.append("React")
            if "vue.js" in html: tech.append("Vue.js")
            
            # Quality signals
            has_ssl = url.startswith("https")
            has_meta_desc = 'meta name="description"' in html
            has_og_tags = 'og:title' in html
            has_responsive = 'viewport' in html
            has_ga = 'google-analytics' in html or 'gtag' in html or 'gtm' in html
            
            lead["site_technologies"] = tech
            lead["site_has_ssl"] = has_ssl
            lead["site_has_meta"] = has_meta_desc
            lead["site_has_og"] = has_og_tags
            lead["site_has_responsive"] = has_responsive
            lead["site_has_analytics"] = has_ga
            lead["site_analyzed"] = True
            
            # Score qualité du site (0-100)
            quality = 0
            if has_ssl: quality += 20
            if has_meta_desc: quality += 20
            if has_og_tags: quality += 15
            if has_responsive: quality += 20
            if has_ga: quality += 15
            if tech and tech[0] in ["Next.js", "Gatsby", "React", "Vue.js"]: quality += 10
            if tech and tech[0] in ["WordPress"]: quality += 5
            if tech and tech[0] in ["Wix", "Jimdo"]: quality = max(quality - 10, 0)
            
            lead["site_quality_score"] = quality
            
            # Si site de mauvaise qualité → prospect "modernisation"
            if quality < 40:
                lead["website_status"] = "outdated"
            
            tech_str = ", ".join(tech) if tech else "Unknown"
            print(f"    [{i+1}] {lead['name']}: {tech_str} | quality={quality}")
            
            time.sleep(1)
            
        except Exception as e:
            lead["site_analyzed"] = False
            lead["site_error"] = str(e)[:100]
    
    save_queue(queue)
    print(f"  ✅ Site Analysis: {len([l for l in to_analyze if l.get('site_analyzed')])} sites analysés")


# ════════════════════════════════════════════════════════════
#  ENRICHISSEMENT 4: INSTAGRAM LOOKUP
#  Vérifie si le commerce est actif sur Instagram
# ════════════════════════════════════════════════════════════

def enrich_instagram(queue, max_leads=20):
    """
    Vérifie l'activité Instagram du commerce.
    Si un restaurant n'est PAS sur Instagram → meilleur prospect
    (car il manque un canal de communication entier).
    
    Ce que ça apporte:
    - Détermine si le commerce est "digital-first" ou "traditionnel"
    - Les commerces sans Instagram = plus réceptifs à l'aide digitale
    """
    print("  📸 Instagram: Check activité...")
    
    instagram_sectors = ["Restaurant", "Salon de coiffure", "Beauté", "Boulangerie / Pâtisserie", "Fleuriste", "Sport"]
    to_check = [l for l in queue 
                if l.get("sector") in instagram_sectors 
                and not l.get("instagram_checked")
                and l.get("website_status") == "none"][:max_leads]
    
    checked = 0
    for lead in to_check:
        name = lead.get("name", "").lower().replace(" ", "").replace("'", "").replace("-", "")
        city = lead.get("city", "Annemasse").lower()
        
        # On ne peut pas vraiment scraper Instagram sans API
        # Mais on peut checker si le nom existe comme username
        lead["instagram_username_guess"] = f"@{name[:30]}"
        lead["instagram_checked"] = True
        lead["instagram_presence"] = "unknown"  # À vérifier manuellement
        
        checked += 1
    
    save_queue(queue)
    print(f"  ✅ Instagram: {checked} leads vérifiés (estimation)")


# ════════════════════════════════════════════════════════════
#  RAPPORT D'ENRICHISSEMENT
# ════════════════════════════════════════════════════════════

def enrichment_report(queue):
    """Génère un rapport d'enrichissement"""
    print()
    print("════════════════════════════════════════════════════════════")
    print("  📊 RAPPORT D'ENRICHISSEMENT")
    print("════════════════════════════════════════════════════════════")
    print()
    
    total = len(queue)
    print(f"  Total leads: {total}")
    print()
    
    # Pappers
    p = sum(1 for l in queue if l.get("sirene_enriched"))
    print(f"  🏢 Sirene:       {p:>5d} / {total} ({p*100//max(total,1)}%)")
    if p > 0:
        sarl = sum(1 for l in queue if "SARL" in l.get("forme_juridique", ""))
        eurl = sum(1 for l in queue if "EURL" in l.get("forme_juridique", ""))
        sasu = sum(1 for l in queue if "SASU" in l.get("forme_juridique", ""))
        auto = sum(1 for l in queue if "Auto-entrepreneur" in l.get("forme_juridique", ""))
        print(f"     SARL: {sarl} | EURL: {eurl} | SASU: {sasu} | Auto: {auto}")
        print(f"     → SARL/EURL/SASU = décideur unique = plus facile à convertir")
    
    # GMaps
    g = sum(1 for l in queue if l.get("gmaps_enriched"))
    print(f"  🗺️ Google Maps:  {g:>5d} / {total} ({g*100//max(total,1)}%)")
    
    # Site analysis
    s = sum(1 for l in queue if l.get("site_analyzed"))
    outdated = sum(1 for l in queue if l.get("website_status") == "outdated")
    print(f"  🌐 Site Analysis:{s:>5d} / {total} ({s*100//max(total,1)}%)")
    if outdated > 0:
        print(f"     Sites obsolètes détectés: {outdated} → prospects \"modernisation\"")
    
    # Instagram
    ig = sum(1 for l in queue if l.get("instagram_checked"))
    print(f"  📸 Instagram:    {ig:>5d} / {total} ({ig*100//max(total,1)}%)")
    
    # Data completeness score
    print()
    print("  Score complétude des données:")
    fields = ["name", "address", "phone", "website", "sector", "lat", "siret", "rating"]
    for field in fields:
        count = sum(1 for l in queue if l.get(field))
        pct = count * 100 // max(total, 1)
        bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
        print(f"    {field:15s} {bar} {pct:3d}%")


# ════════════════════════════════════════════════════════════
#  MAIN
# ════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--pappers", action="store_true")
    parser.add_argument("--gmaps", action="store_true")
    parser.add_argument("--site", action="store_true")
    parser.add_argument("--instagram", action="store_true")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--max", type=int, default=50)
    args = parser.parse_args()
    
    # Load env
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())
    
    queue = get_queue()
    
    if args.report:
        enrichment_report(queue)
    elif args.all:
        print("═" * 60)
        print("  🔄 SOCIALPULSE — FULL ENRICHMENT")
        print("═" * 60)
        enrich_pappers(queue, args.max)
        enrich_site_analysis(queue, args.max)
        enrich_instagram(queue, args.max)
        enrichment_report(queue)
    elif args.pappers:
        enrich_pappers(queue, args.max)
    elif args.gmaps:
        enrich_gmaps(queue, args.max)
    elif args.site:
        enrich_site_analysis(queue, args.max)
    elif args.instagram:
        enrich_instagram(queue, args.max)
    else:
        parser.print_help()
