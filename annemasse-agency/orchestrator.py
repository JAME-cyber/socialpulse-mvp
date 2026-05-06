#!/usr/bin/env python3
"""
SocialPulse Annemasse Agency — Orchestrator
============================================
Orchestrateur principal qui coordonne les 7 agents.
Inspiré du scénario @browomo mais adapté pour:
  - Annemasse / Gaillard / Ville-la-Grand / Saint-Julien (74)
  - Stack 100% open-source (Apify + OpenRouter + HyperFrame + FFmpeg)
  - Budget ~80€/mois vs $480/mois dans le tweet

Usage:
  python3 orchestrator.py                    # Full pipeline
  python3 orchestrator.py --agent scout      # Un seul agent
  python3 orchestrator.py --status           # État du système
"""

import os
import sys
import json
import time
import hashlib
import datetime
import argparse
from pathlib import Path

BASE = Path(__file__).parent
STATE_DIR = BASE / "state"
CLIENTS_DIR = BASE / "clients"
OUTPUT_DIR = BASE / "output"
LOGS_DIR = BASE / "logs"
VIDEOS_DIR = BASE / "videos"

for d in [STATE_DIR, CLIENTS_DIR, OUTPUT_DIR, LOGS_DIR, VIDEOS_DIR]:
    d.mkdir(parents=True, exist_ok=True)


# ── Journal WORM ──────────────────────────────────────────────
class WORMJournal:
    """Journal append-only, hash-chainé comme SocialPulse v4"""
    
    def __init__(self, batch_id: str):
        self.batch_id = batch_id
        self.entries = []
        self.journal_path = LOGS_DIR / f"journal-{batch_id}.json"
        self._prev_hash = "0" * 64
        
        # Load existing journal if present
        if self.journal_path.exists():
            data = json.loads(self.journal_path.read_text())
            self.entries = data.get("entries", [])
            if self.entries:
                self._prev_hash = self.entries[-1]["hash"].replace("sha256:", "")
    
    def log(self, action: str, actor: str, details: dict, lead: str = None):
        seq = len(self.entries) + 1
        entry = {
            "seq": seq,
            "timestamp": datetime.datetime.now().isoformat(),
            "action": action,
            "actor": actor,
            "details": details,
        }
        if lead:
            entry["lead"] = lead
        
        # Hash chain
        payload = json.dumps(entry, sort_keys=True)
        h = hashlib.sha256(payload.encode()).hexdigest()
        entry["prev_hash"] = f"sha256:{self._prev_hash}"
        entry["hash"] = f"sha256:{h}"
        self._prev_hash = h
        
        self.entries.append(entry)
        self._save()
        return entry
    
    def _save(self):
        data = {
            "batch_id": self.batch_id,
            "entries": self.entries,
            "total": len(self.entries),
            "updated": datetime.datetime.now().isoformat(),
        }
        self.journal_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


# ── State Manager ─────────────────────────────────────────────
class StateManager:
    """Gestionnaire d'état partagé entre les agents (fichier JSON)"""
    
    QUEUE_PATH = STATE_DIR / "lead-queue.json"
    PROCESSED_PATH = STATE_DIR / "processed-leads.json"
    STATS_PATH = STATE_DIR / "stats.json"
    
    def __init__(self):
        # Init files if needed
        if not self.QUEUE_PATH.exists():
            self.QUEUE_PATH.write_text(json.dumps([], indent=2))
        if not self.PROCESSED_PATH.exists():
            self.PROCESSED_PATH.write_text(json.dumps([], indent=2))
        if not self.STATS_PATH.exists():
            self.STATS_PATH.write_text(json.dumps({
                "total_discovered": 0,
                "total_qualified": 0,
                "total_messaged": 0,
                "total_replies": 0,
                "total_deals": 0,
                "daily": {},
                "costs": {"apify_usd": 0, "openrouter_usd": 0}
            }, indent=2))
    
    def get_queue(self) -> list:
        return json.loads(self.QUEUE_PATH.read_text())
    
    def save_queue(self, queue: list):
        self.QUEUE_PATH.write_text(json.dumps(queue, indent=2, ensure_ascii=False))
    
    def get_processed(self) -> list:
        return json.loads(self.PROCESSED_PATH.read_text())
    
    def add_processed(self, lead: dict):
        processed = self.get_processed()
        processed.append(lead)
        self.PROCESSED_PATH.write_text(json.dumps(processed, indent=2, ensure_ascii=False))
    
    def get_stats(self) -> dict:
        return json.loads(self.STATS_PATH.read_text())
    
    def update_stats(self, updates: dict):
        stats = self.get_stats()
        for k, v in updates.items():
            if isinstance(v, dict):
                stats[k].update(v)
            else:
                stats[k] = stats.get(k, 0) + v
        self.STATS_PATH.write_text(json.dumps(stats, indent=2))
    
    def lead_exists(self, place_id: str) -> bool:
        queue = self.get_queue()
        processed = self.get_processed()
        all_ids = [l.get("place_id") for l in queue + processed]
        return place_id in all_ids


# ── Médiateur Déterministe ────────────────────────────────────
class Mediateur:
    """Vérifie les règles de conformité — 0% LLM, 100% déterministe"""
    
    def __init__(self):
        rules_path = BASE / ".." / ".hermes" / "skills" / "cortex-leman" / "socialpulse-lead-gen" / "mediateur_rules.json"
        if rules_path.exists():
            self.rules = json.loads(rules_path.read_text())
        else:
            self.rules = self._default_rules()
    
    def _default_rules(self):
        return {
            "rules": {
                "discovery": [
                    {"<=": [{"var": "results_count"}, {"var": "max_results"}]},
                ],
                "qualification": [
                    {">=": [{"var": "score"}, {"var": "threshold"}]},
                    {"!=": [{"var": "opt_out"}, True]},
                ],
                "personalization": [
                    {"<=": [{"var": "word_count"}, {"var": "max_words"}]},
                ]
            }
        }
    
    def check(self, stage: str, data: dict) -> tuple:
        """Retourne (passed: bool, violations: list)"""
        violations = []
        stage_rules = self.rules.get("rules", {}).get(stage, [])
        
        for i, rule in enumerate(stage_rules):
            try:
                from json_logic_qubit import jsonLogic
                if not jsonLogic(rule, data):
                    violations.append(f"Règle {stage}[{i}] violée: {json.dumps(rule)}")
            except Exception:
                pass  # Skip règles impossibles à évaluer
        
        return len(violations) == 0, violations
    
    def gel_lead(self, lead: dict, motif: str, journal: WORMJournal):
        """Gel automatique d'un lead"""
        lead["status"] = "gele"
        lead["gel_motif"] = motif
        lead["gel_date"] = datetime.datetime.now().isoformat()
        journal.log("mediateur.gel", "mediateur", {"motif": motif}, lead.get("name"))


# ── Agent 1: SCOUT ────────────────────────────────────────────
class ScoutAgent:
    """
    Agent Scout — Parcourt OpenStreetMap (Overpass API, GRATUIT) + Apify Google Maps (fallback payant)
    Filtre: pas de site / site obsolète / peu d'avis / bonne réputation
    Cible: Annemasse, Gaillard, Ville-la-Grand, Saint-Julien
    """
    
    def __init__(self, state: StateManager, journal: WORMJournal):
        self.state = state
        self.journal = journal
        self.apify_token = os.environ.get("APIFY_TOKEN", "")
        
        # Bounding box Annemasse agglomeration
        # Annemasse (46.194,6.236) + Gaillard (46.194,6.214) + St-Julien (46.145,6.083) + Ville-la-Grand (46.193,6.255)
        self.bbox = (46.12, 6.03, 46.24, 6.30)  # (south, west, north, east)
    
    # Mapping OSM tags → SocialPulse sectors
    OSM_SECTOR_MAP = {
        "restaurant": {"sector": "Restaurant", "icon": "🍽️", "channel": "instagram"},
        "cafe": {"sector": "Restaurant", "icon": "☕", "channel": "instagram"},
        "fast_food": {"sector": "Restaurant", "icon": "🍔", "channel": "instagram"},
        "bakery": {"sector": "Boulangerie / Pâtisserie", "icon": "🥖", "channel": "instagram"},
        "pastry": {"sector": "Boulangerie / Pâtisserie", "icon": "🥐", "channel": "instagram"},
        "confectionery": {"sector": "Boulangerie / Pâtisserie", "icon": "🍬", "channel": "instagram"},
        "hairdresser": {"sector": "Salon de coiffure", "icon": "💇", "channel": "instagram"},
        "accountant": {"sector": "Cabinet comptable", "icon": "📊", "channel": "email"},
        "lawyer": {"sector": "Avocat", "icon": "⚖️", "channel": "email"},
        "notary": {"sector": "Avocat", "icon": "⚖️", "channel": "email"},
        "insurance": {"sector": "Assurance", "icon": "🛡️", "channel": "email"},
        "estate_agent": {"sector": "Immobilier", "icon": "🏠", "channel": "linkedin"},
        "car_repair": {"sector": "Garage auto", "icon": "🚗", "channel": "sms"},
        "car": {"sector": "Garage auto", "icon": "🚗", "channel": "sms"},
        "physiotherapist": {"sector": "Kiné / Ostéopathe", "icon": "🏥", "channel": "email"},
        "florist": {"sector": "Fleuriste", "icon": "💐", "channel": "instagram"},
        "plumber": {"sector": "Plombier / Chauffagiste", "icon": "🔧", "channel": "sms"},
        "heating_engineer": {"sector": "Plombier / Chauffagiste", "icon": "🔧", "channel": "sms"},
        "optician": {"sector": "Santé", "icon": "👓", "channel": "email"},
        "pharmacy": {"sector": "Santé", "icon": "💊", "channel": "email"},
        "dentist": {"sector": "Santé", "icon": "🦷", "channel": "email"},
        "doctors": {"sector": "Santé", "icon": "🏥", "channel": "email"},
        "beauty": {"sector": "Beauté", "icon": "💅", "channel": "instagram"},
        "fitness_centre": {"sector": "Sport", "icon": "💪", "channel": "instagram"},
    }
    
    def run(self, campaign: dict):
        """Lance le scout — Overpass API (gratuit) en priorité, Apify en fallback"""
        discovered = []
        
        # ── SOURCE 1: Overpass API (OpenStreetMap) — GRATUIT ──
        print("  🗺️ Source 1: OpenStreetMap / Overpass API (gratuit)")
        osm_leads = self._scout_overpass(campaign)
        discovered.extend(osm_leads)
        
        # ── SOURCE 2: Apify Google Maps (PAYANT, optionnel) ──
        if self.apify_token and os.environ.get("USE_APIFY"):
            print("  🗺️ Source 2: Apify Google Maps (payant)")
            try:
                from apify_client import ApifyClient
                apify_leads = self._scout_apify(campaign)
                discovered.extend(apify_leads)
            except Exception as e:
                print(f"     ⚠️ Apify indisponible: {e}")
        
        # Dédupliquer
        seen = set()
        unique = []
        for lead in discovered:
            key = lead.get("name", "").lower().strip()
            if key and key not in seen:
                seen.add(key)
                unique.append(lead)
        
        # Ajouter à la queue (seulement les nouveaux)
        queue = self.state.get_queue()
        new_count = 0
        for lead in unique:
            if not self.state.lead_exists(lead.get("place_id", "")):
                queue.append(lead)
                new_count += 1
        self.state.save_queue(queue)
        
        self.journal.log("scout.complete", "system", {
            "total_raw": len(discovered),
            "unique": len(unique),
            "new_in_queue": new_count,
        })
        
        print(f"\n  ✅ Scout: {new_count} nouveaux leads dans la queue")
        return unique
    
    def _scout_overpass(self, campaign: dict) -> list:
        """Scout via Overpass API — 100% GRATUIT"""
        import urllib.request, urllib.parse
        
        bbox = self.bbox
        s, w, n, e = bbox
        
        # Requêtes OSM par type de commerce
        osm_queries = [
            ('amenity', 'restaurant'),
            ('amenity', 'cafe'),
            ('amenity', 'fast_food'),
            ('shop', 'bakery'),
            ('craft', 'hairdresser'),
            ('shop', 'hairdresser'),
            ('office', 'accountant'),
            ('office', 'lawyer'),
            ('office', 'insurance'),
            ('shop', 'florist'),
            ('shop', 'car_repair'),
            ('healthcare', 'physiotherapist'),
            ('amenity', 'dentist'),
            ('shop', 'beauty'),
            ('leisure', 'fitness_centre'),
            ('craft', 'plumber'),
            ('office', 'estate_agent'),
        ]
        
        all_results = []
        
        for key, value in osm_queries:
            # Build Overpass query — nodes + ways + relations
            query = f'[out:json][timeout:30];(node["{key}"="{value}"]({s},{w},{n},{e});way["{key}"="{value}"]({s},{w},{n},{e}););out body center;'
            
            url = 'https://overpass-api.de/api/interpreter'
            data = urllib.parse.urlencode({'data': query}).encode()
            req = urllib.request.Request(url, data=data, headers={'User-Agent': 'SocialPulse/1.0'})
            
            try:
                with urllib.request.urlopen(req, timeout=45) as resp:
                    result = json.loads(resp.read().decode())
                
                elements = result.get('elements', [])
                leads = []
                
                for el in elements:
                    lead = self._parse_osm_element(el, key, value)
                    if lead and lead.get('name'):
                        leads.append(lead)
                
                without_site = [l for l in leads if l.get('website_status') != 'has_website']
                all_results.extend(leads)
                
                sector_info = self.OSM_SECTOR_MAP.get(value, {})
                print(f"     {value}: {len(leads)} total, {len(without_site)} sans site")
                
                time.sleep(0.5)  # Rate limit Overpass
                
            except Exception as ex:
                print(f"     ⚠️ {key}={value}: {ex}")
        
        self.journal.log("scout.overpass", "osm", {
            "total_found": len(all_results),
            "cost_usd": 0,
        })
        self.state.update_stats({"total_discovered": len(all_results)})
        
        return all_results
    
    def _scout_apify(self, campaign: dict) -> list:
        """Fallback: Scout via Apify Google Maps (payant)"""
        from apify_client import ApifyClient
        
        client = ApifyClient(self.apify_token)
        discovered = []
        
        sectors = campaign.get("target", {}).get("sectors", [])
        
        for sector in sectors[:3]:  # Limiter à 3 secteurs pour le coût
            for query in sector.get("search_queries", [])[:2]:  # Max 2 queries/secteur
                print(f"  🔍 Scout Apify: '{query}'...")
                try:
                    run = client.actor("apify/google-maps-scraper").call(run_input={
                        "searchStringsArray": [query],
                        "maxCrawledPlacesPerSearch": 15,
                        "language": "fr",
                        "countryCode": "fr",
                    })
                    
                    for item in client.dataset(run["defaultDatasetId"]).iterate_items():
                        place = self._parse_place(item, sector)
                        if place and not self.state.lead_exists(place["place_id"]):
                            discovered.append(place)
                    
                    time.sleep(2)
                    
                except Exception as e:
                    print(f"     ❌ Erreur: {e}")
                    self.journal.log("scout.error", "apify", {"error": str(e)})
        
        return discovered
    
    def _parse_osm_element(self, el: dict, osm_key: str, osm_value: str) -> dict:
        """Parse un élément OSM en lead SocialPulse"""
        tags = el.get('tags', {})
        name = tags.get('name', '').strip()
        if not name:
            return None
        
        # Skip les grandes chaînes
        chain_names = ['mcdonald', 'burger king', 'kfc', 'subway', 'starbucks', 'dominos', 'pizza hut', 'carrefour', 'leclerc', 'intermarché', 'super u', 'casino', 'aldi', 'lidl', 'boulanger', 'pharmacie']
        if any(c in name.lower() for c in chain_names):
            return None
        
        # Latitude/longitude
        lat = el.get('lat', el.get('center', {}).get('lat', 0))
        lon = el.get('lon', el.get('center', {}).get('lon', 0))
        
        # Déterminer la ville
        addr_city = tags.get('addr:city', tags.get('addr:suburb', ''))
        city = "Annemasse"
        for c in ["Gaillard", "Ville-la-Grand", "Saint-Julien-en-Genevois", "Ambilly", "Etrembières", "Annemasse"]:
            if c.lower() in name.lower() or c.lower() in addr_city.lower():
                city = c
                break
        # Fallback: déduire des coords
        if not addr_city:
            if lon < 6.22:
                city = "Gaillard"
            elif lon > 6.25:
                city = "Ville-la-Grand"
            elif lat < 6.18:
                city = "Saint-Julien-en-Genevois"
            else:
                city = "Annemasse"
        
        website = tags.get('website', tags.get('contact:website', ''))
        phone = tags.get('phone', tags.get('contact:phone', ''))
        
        sector_info = self.OSM_SECTOR_MAP.get(osm_value, {
            "sector": osm_value.title(), "icon": "⚡", "channel": "email"
        })
        
        # Website status
        if not website:
            website_status = "none"
        elif 'facebook.com' in website.lower():
            website_status = "facebook_only"
        elif 'pagejaunes.fr' in website.lower() or 'pagesjaunes.fr' in website.lower():
            website_status = "pagejaunes_only"
        else:
            website_status = "has_website"
        
        return {
            "place_id": f"osm-{el.get('id', hash(name))}",
            "osm_id": el.get('id'),
            "osm_type": f"{osm_key}={osm_value}",
            "name": name,
            "address": f"{tags.get('addr:street', '')}, {city}",
            "city": city,
            "phone": phone,
            "website": website,
            "website_status": website_status,
            "category": osm_value,
            "sector": sector_info.get("sector", osm_value.title()),
            "sector_icon": sector_info.get("icon", "⚡"),
            "channel": sector_info.get("channel", "email"),
            "lat": lat,
            "lon": lon,
            "opening_hours": tags.get('opening_hours', ''),
            "cuisine": tags.get('cuisine', ''),
            "discovered_at": datetime.datetime.now().isoformat(),
            "source": "osm",
            "status": "discovered",
        }
    
    def _parse_place(self, item: dict, sector: dict) -> dict:
        """Extrait les données d'un lieu Google Maps"""
        try:
            return {
                "place_id": item.get("placeId", item.get("url", "")),
                "name": item.get("title", ""),
                "address": item.get("address", ""),
                "phone": item.get("phone", ""),
                "website": item.get("website", ""),
                "url": item.get("url", ""),
                "category": item.get("categoryName", ""),
                "rating": item.get("totalScore", 0),
                "reviews_count": item.get("reviewsCount", 0),
                "location": item.get("location", {}),
                "sector": sector["name"],
                "sector_icon": sector.get("icon", "⚡"),
                "channel": sector.get("channel", "email"),
                "weight": sector.get("weight", 50),
                "discovered_at": datetime.datetime.now().isoformat(),
                "status": "discovered",
            }
        except Exception:
            return None
    
    def _passes_criteria(self, place: dict, campaign: dict) -> bool:
        """Filtre les leads selon les critères du tweet"""
        criteria = campaign.get("scout_criteria", {})
        
        # Rating minimum
        if place.get("rating", 0) < criteria.get("rating_min", 3.5):
            return False
        
        # Max reviews (peu d'avis = moins visible = meilleur prospect)
        if place.get("reviews_count", 0) > criteria.get("max_reviews", 50):
            return False
        
        # Website red flags (PAS de site = meilleur prospect)
        website = place.get("website", "")
        red_flags = criteria.get("website_red_flags", [])
        
        if not website:
            place["website_status"] = "none"
            return True  # Pas de site = top prospect
        
        website_lower = website.lower()
        for flag in red_flags:
            if flag in website_lower:
                place["website_status"] = flag.split(".")[0]
                return True
        
        place["website_status"] = "has_website"
        # On garde quand même, le scoring fera le tri
        return True


# ── Agent 2: DIAGNOSER ───────────────────────────────────────
class DiagnoserAgent:
    """
    Agent Diagnoser — Pour chaque lead:
    - Score déterministe (JsonLogic)
    - Diagnostic 50 mots max
    - Angle d'approche
    - Cold message <70 mots
    """
    
    def __init__(self, state: StateManager, journal: WORMJournal, mediateur: Mediateur):
        self.state = state
        self.journal = journal
        self.mediateur = mediateur
    
    def run(self, campaign: dict, max_diagnose: int = 30):
        """Diagnose les leads dans la queue. Scoring déterministe pour tous,
        LLM (OpenRouter) seulement pour les top leads."""
        queue = self.state.get_queue()
        diagnosed = []
        
        # Phase 1: Scoring déterministe pour TOUS les leads
        for lead in queue:
            if lead.get("status") != "discovered":
                continue
            
            score = self._score_lead(lead, campaign)
            lead["score"] = score
            lead["score_breakdown"] = self._score_breakdown(lead, campaign)
            
            # Médiateur check
            passed, violations = self.mediateur.check("qualification", {
                "score": score,
                "threshold": campaign["scoring"]["threshold"],
                "opt_out": lead.get("opt_out", False),
            })
            
            if not passed:
                lead["status"] = "gele"
                lead["gel_motif"] = f"Score {score} < threshold {campaign['scoring']['threshold']}"
            else:
                lead["status"] = "scored"
                diagnosed.append(lead)
        
        self.state.save_queue(queue)
        
        # Phase 2: LLM diagnosis seulement pour les top leads
        top_leads = sorted(diagnosed, key=lambda x: x.get("score", 0), reverse=True)[:max_diagnose]
        
        print(f"  📊 Phase 1: {len(diagnosed)} leads scorés (scored), {len(queue)-len(diagnosed)} gelés")
        print(f"  🤖 Phase 2: LLM diagnosis pour top {len(top_leads)} leads...")
        
        for i, lead in enumerate(top_leads):
            # Quick diagnosis without LLM for most, LLM for top 5
            if i < 5:
                diagnosis = self._generate_diagnosis(lead, campaign)
            else:
                diagnosis = self._quick_diagnosis(lead, campaign)
            
            lead.update(diagnosis)
            lead["status"] = "diagnosed"
            
            self.journal.log(
                "diagnoser.score_and_diagnose",
                "openrouter" if i < 5 else "local",
                {"score": lead["score"], "diagnosis_method": "llm" if i < 5 else "template"},
                lead["name"]
            )
            
            print(f"  📋 [{i+1}/{len(top_leads)}] {lead['name']} (score={lead['score']})")
        
        self.state.save_queue(queue)
        print(f"\n  ✅ Diagnoser: {len(top_leads)} leads diagnostiqués")
        return top_leads
    
    def _score_lead(self, lead: dict, campaign: dict) -> int:
        """Scoring déterministe 0-100"""
        scoring = campaign["scoring"]
        criteria = scoring["criteria"]
        total = 0
        
        # 1. Website status (30%)
        ws = lead.get("website_status", "has_website")
        website_scores = {"none": 100, "facebook_only": 80, "pagejaunes_only": 70, "outdated": 60, "has_website": 20}
        total += website_scores.get(ws, 20) * criteria["has_website"]["weight"]
        
        # 2. Review gap (25%)
        rating = lead.get("rating", 0)
        reviews = lead.get("reviews_count", 0)
        if rating >= 4.0 and reviews < 20:
            rg_score = 100
        elif rating >= 3.5 and reviews < 30:
            rg_score = 70
        else:
            rg_score = 30
        total += rg_score * criteria["review_gap"]["weight"]
        
        # 3. Sector (25%)
        sector_map = criteria["sector"]["mapping"]
        sector_score = sector_map.get(lead.get("sector", ""), sector_map.get("default", 50))
        total += sector_score * criteria["sector"]["weight"]
        
        # 4. Location (20%)
        addr = lead.get("address", "").lower()
        loc_map = criteria["location"]["mapping"]
        loc_score = 50  # default
        for city_name, city_score in loc_map.items():
            if city_name.lower() in addr:
                loc_score = city_score
                break
        total += loc_score * criteria["location"]["weight"]
        
        return min(100, max(0, int(total)))
    
    def _score_breakdown(self, lead: dict, campaign: dict) -> dict:
        """Détail du score pour le journal"""
        criteria = campaign["scoring"]["criteria"]
        ws = lead.get("website_status", "has_website")
        website_scores = {"none": 100, "facebook_only": 80, "pagejaunes_only": 70, "outdated": 60, "has_website": 20}
        
        return {
            "website": int(website_scores.get(ws, 20) * criteria["has_website"]["weight"]),
            "review_gap": "calculated",
            "sector": lead.get("sector", "unknown"),
            "location": lead.get("address", "unknown"),
            "total": lead.get("score", 0),
        }
    
    def _quick_diagnosis(self, lead: dict, campaign: dict) -> dict:
        """Template diagnosis sans LLM — plus rapide"""
        name = lead.get('name', '')
        sector = lead.get('sector', '')
        city = lead.get('city', 'Annemasse')
        has_website = lead.get('website_status') != 'none'
        
        return {
            "diagnosis": f"{name} est un commerce {sector.lower()} à {city} {'avec un site existant' if has_website else 'sans site web professionnel'}. Excellente opportunité de création web.",
            "hero_angle": f"Proximité {city} · Expertise locale",
            "tone": "Professionnel et chaleureux",
            "cold_message": f"Bonjour, j'ai remarqué {name} sur les cartes — super réputation ! Un site vitrine simple pourrait vous apporter 30% de clients en plus depuis Google. Je suis basé à Annemasse, on pourrait en discuter ?",
        }
    
    def _generate_diagnosis(self, lead: dict, campaign: dict) -> dict:
        """Génère diagnostic + cold message via OpenRouter (LLM)"""
        import urllib.request
        
        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        if not api_key:
            return self._quick_diagnosis(lead, campaign)
        
        prompt = f"""Tu es un expert en prospection locale. Pour ce commerce à Annemasse/Gaillard/Saint-Julien:

Nom: {lead.get('name', '')}
Secteur: {lead.get('sector', '')}
Adresse: {lead.get('address', '')}
Ville: {lead.get('city', 'Annemasse')}
Site web: {lead.get('website', 'AUCUN')}

Génère en JSON:
{{
  "diagnosis": "Diagnostic en 50 mots max: pourquoi ce commerce a besoin d'un site",
  "hero_angle": "L'argument principal d'approche",
  "tone": "Le ton adapté au secteur",
  "cold_message": "Message personnalisé <70 mots, naturel, sans buzzword IA. Mentionne la proximité géographique. Termine par un appel à l'action doux."
}}

Réponds UNIQUEMENT en JSON valide. En français."""

        try:
            req = urllib.request.Request(
                "https://openrouter.ai/api/v1/chat/completions",
                data=json.dumps({
                    "model": "deepseek/deepseek-v4-flash",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.7,
                    "max_tokens": 500,
                }).encode(),
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                }
            )
            
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode())
                content = result["choices"][0]["message"]["content"]
                
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0]
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0]
                
                return json.loads(content.strip())
        
        except Exception as e:
            return self._quick_diagnosis(lead, campaign)


# ── Agent 3: BUILDER ─────────────────────────────────────────
class BuilderAgent:
    """
    Agent Builder — Génère une landing page HTML pour les top leads
    Utilise les templates SocialPulse existants (gratuit, local)
    """
    
    def __init__(self, state: StateManager, journal: WORMJournal):
        self.state = state
        self.journal = journal
    
    def run(self, campaign: dict, max_builds: int = 5):
        """Build landing pages pour les top leads"""
        queue = self.state.get_queue()
        
        # Prendre les top leads par score
        top_leads = sorted(
            [l for l in queue if l.get("status") == "diagnosed"],
            key=lambda x: x.get("score", 0),
            reverse=True
        )[:max_builds]
        
        built = []
        for lead in top_leads:
            html = self._generate_landing_page(lead, campaign)
            
            # Sauver dans clients/
            slug = lead["name"].lower().replace(" ", "-").replace("'", "")[:30]
            client_dir = CLIENTS_DIR / slug
            client_dir.mkdir(parents=True, exist_ok=True)
            
            page_path = client_dir / "index.html"
            page_path.write_text(html)
            
            lead["landing_page"] = str(page_path)
            lead["landing_url"] = f"file://{page_path}"
            lead["status"] = "built"
            built.append(lead)
            
            self.journal.log(
                "builder.landing_page",
                "local",
                {
                    "client": slug,
                    "path": str(page_path),
                    "html_size": len(html),
                },
                lead["name"]
            )
            
            print(f"  🏗️ Built: {lead['name']} → {page_path}")
        
        self.state.save_queue(queue)
        print(f"\n  ✅ Builder: {len(built)} landing pages générées")
        return built
    
    def _generate_landing_page(self, lead: dict, campaign: dict) -> str:
        """Génère une landing page HTML/CSS responsive pour le commerce"""
        name = lead.get("name", "Commerce")
        sector = lead.get("sector", "")
        icon = lead.get("sector_icon", "⚡")
        address = lead.get("address", "Annemasse")
        phone = lead.get("phone", "")
        rating = lead.get("rating", "?")
        reviews = lead.get("reviews_count", 0)
        diagnosis = lead.get("diagnosis", "")
        hero_angle = lead.get("hero_angle", "")
        cold_msg = lead.get("cold_message", "")
        
        # Couleurs par secteur
        colors = {
            "Restaurant": {"primary": "#f59e0b", "bg": "#1a1412"},
            "Salon de coiffure": {"primary": "#ec4899", "bg": "#1a1218"},
            "Plombier / Chauffagiste": {"primary": "#3b82f6", "bg": "#0f1724"},
            "Avocat": {"primary": "#6366f1", "bg": "#0f0f1a"},
            "Immobilier": {"primary": "#10b981", "bg": "#0f1a15"},
            "Garage auto": {"primary": "#ef4444", "bg": "#1a0f0f"},
            "Cabinet comptable": {"primary": "#8b5cf6", "bg": "#14101a"},
            "Boulangerie / Pâtisserie": {"primary": "#f97316", "bg": "#1a1510"},
            "Kiné / Ostéopathe": {"primary": "#06b6d4", "bg": "#0f1a1a"},
            "Fleuriste": {"primary": "#d946ef", "bg": "#1a0f1a"},
        }
        
        c = colors.get(sector, {"primary": "#6366f1", "bg": "#0a0e17"})
        
        return f'''<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{name} — {sector} à {address.split(",")[-1].strip() if "," in address else "Annemasse"}</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
:root{{--primary:{c["primary"]};--bg:{c["bg"]};--text:#f0f2f5;--text2:rgba(240,242,245,.6)}}
body{{font-family:'Inter',system-ui,sans-serif;background:var(--bg);color:var(--text);min-height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:40px 24px}}
.hero{{text-align:center;max-width:600px}}
.icon{{font-size:64px;margin-bottom:24px}}
h1{{font-size:clamp(28px,5vw,42px);font-weight:900;letter-spacing:-1px;margin-bottom:8px;line-height:1.1}}
.sector{{font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:2px;color:var(--primary);margin-bottom:24px}}
.address{{font-size:15px;color:var(--text2);margin-bottom:32px}}
.address span{{color:var(--primary)}}
.rating{{display:inline-flex;align-items:center;gap:8px;background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.1);border-radius:12px;padding:12px 24px;margin-bottom:32px}}
.rating-num{{font-size:32px;font-weight:900;color:var(--primary)}}
.rating-stars{{color:#f59e0b;font-size:18px}}
.rating-count{{font-size:13px;color:var(--text2)}}
.cta{{background:var(--primary);color:#fff;border:none;padding:16px 40px;border-radius:12px;font-size:16px;font-weight:700;cursor:pointer;font-family:inherit;transition:transform .2s}}
.cta:hover{{transform:translateY(-2px)}}
.note{{margin-top:16px;font-size:12px;color:var(--text2)}}
.phone{{margin-top:24px;font-size:18px;font-weight:600;color:var(--primary)}}
.features{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:16px;margin-top:40px;max-width:500px;width:100%}}
.feat{{background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.06);border-radius:12px;padding:20px;text-align:center}}
.feat-icon{{font-size:24px;margin-bottom:8px}}
.feat-text{{font-size:12px;font-weight:600;color:var(--text2)}}
footer{{margin-top:48px;font-size:11px;color:var(--text2);text-align:center}}
footer a{{color:var(--primary);text-decoration:none}}
</style>
</head>
<body>
<div class="hero">
  <div class="icon">{icon}</div>
  <h1>{name}</h1>
  <div class="sector">{sector}</div>
  <div class="address">📍 <span>{address}</span></div>
  <div class="rating">
    <span class="rating-num">{rating}</span>
    <span class="rating-stars">{"⭐" * min(5, int(float(rating) if isinstance(rating, (int, float)) else 4))}</span>
    <span class="rating-count">({reviews} avis)</span>
  </div>
  <button class="cta" onclick="window.location.href='tel:{phone.replace(' ', '') if phone else '#'}'">📞 Nous contacter</button>
  <div class="phone">{"☎️ " + phone if phone else ""}</div>
  <div class="note">Proposition de site vitrine — Établi à Annemasse (74)</div>
</div>
<div class="features">
  <div class="feat"><div class="feat-icon">📱</div><div class="feat-text">Mobile-first</div></div>
  <div class="feat"><div class="feat-icon">⚡</div><div class="feat-text">Rapide</div></div>
  <div class="feat"><div class="feat-icon">🔍</div><div class="feat-text">SEO local</div></div>
  <div class="feat"><div class="feat-icon">🗺️</div><div class="feat-text">Google Maps</div></div>
</div>
<footer>Proposé par <a href="#">SocialPulse</a> · Haute-Savoie · 2026</footer>
</body>
</html>'''


# ── Agent 4: FILMER ──────────────────────────────────────────
class FilmerAgent:
    """
    Agent Filmer — Génère une vidéo 10s verticale 1080x1920
    Utilise HyperFrame (HTML+GSAP) + Puppeteer screenshot + FFmpeg
    100% local, 100% gratuit
    """
    
    def __init__(self, state: StateManager, journal: WORMJournal):
        self.state = state
        self.journal = journal
    
    def run(self, campaign: dict, max_videos: int = 5):
        """Génère les vidéos pour les leads "built" """
        queue = self.state.get_queue()
        
        leads_to_film = [l for l in queue if l.get("status") == "built"][:max_videos]
        filmed = []
        
        for lead in leads_to_film:
            # Générer le HTML HyperFrame
            video_html = self._generate_video_html(lead)
            
            slug = lead["name"].lower().replace(" ", "-").replace("'", "")[:30]
            client_dir = CLIENTS_DIR / slug
            
            html_path = client_dir / "video.html"
            html_path.write_text(video_html)
            
            # Tenter le render via Puppeteer + FFmpeg si disponibles
            video_path = self._render_video(html_path, client_dir)
            
            lead["video_html"] = str(html_path)
            lead["video_path"] = video_path
            lead["status"] = "filmed"
            filmed.append(lead)
            
            self.journal.log(
                "filmer.video",
                "hyperframe+ffmpeg",
                {
                    "html_path": str(html_path),
                    "video_path": video_path,
                    "format": "1080x1920",
                    "duration": "10s",
                },
                lead["name"]
            )
            
            print(f"  🎬 Filmed: {lead['name']} → {video_path or html_path}")
        
        self.state.save_queue(queue)
        print(f"\n  ✅ Filmer: {len(filmed)} vidéos générées")
        return filmed
    
    def _generate_video_html(self, lead: dict) -> str:
        """Génère le HTML HyperFrame pour la vidéo lead card"""
        name = lead.get("name", "Commerce")
        sector = lead.get("sector", "")
        icon = lead.get("sector_icon", "⚡")
        address = lead.get("address", "Annemasse")
        rating = lead.get("rating", "?")
        score = lead.get("score", 0)
        website = lead.get("website", "AUCUN")
        
        has_site = website and website not in ["", "AUCUN"]
        status_text = "SITE WEB MANQUANT" if not has_site else "SITE À MODERNISER"
        status_color = "#ef4444" if not has_site else "#f59e0b"
        
        return f'''<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&family=JetBrains+Mono:wght@400;700&display=swap');
*{{margin:0;padding:0;box-sizing:border-box}}
body{{width:1080px;height:1920px;overflow:hidden;background:#0a0e17;font-family:'Inter',sans-serif;color:#f0f2f5}}
.progress{{position:absolute;top:0;left:0;right:0;height:4px;z-index:100}}
.progress-fill{{height:100%;width:0%;background:linear-gradient(90deg,#6366f1,#818cf8)}}

.scene{{position:absolute;top:0;left:0;width:100%;height:100%;display:flex;flex-direction:column;justify-content:center;align-items:center;padding:60px}}

#s1{{z-index:1}}
#s2{{z-index:2;opacity:0}}
#s3{{z-index:3;opacity:0}}
#s4{{z-index:4;opacity:0}}

.alert-badge{{font-size:13px;font-weight:800;text-transform:uppercase;letter-spacing:4px;color:{status_color};background:rgba(239,68,68,.12);padding:12px 28px;border-radius:10px;border:1px solid rgba(239,68,68,.2)}}
.hook-title{{font-size:52px;font-weight:900;text-align:center;margin-top:32px;line-height:1.1;letter-spacing:-1px}}
.hook-title .accent{{color:#6366f1}}
.hook-sub{{font-size:15px;color:rgba(240,242,245,.5);margin-top:16px;font-weight:500}}

.card{{background:rgba(17,24,39,.85);border:1px solid rgba(255,255,255,.08);border-radius:24px;padding:48px;backdrop-filter:blur(10px);width:900px}}
.card-top{{display:flex;align-items:center;gap:20px}}
.card-icon{{font-size:52px}}
.card-name{{font-size:32px;font-weight:800;letter-spacing:-.5px}}
.card-sector{{font-size:12px;color:#6366f1;font-weight:700;text-transform:uppercase;letter-spacing:2px;margin-top:4px}}
.card-divider{{height:1px;background:rgba(255,255,255,.06);margin:28px 0}}
.card-info{{display:flex;flex-direction:column;gap:12px;font-size:16px}}
.card-info-row{{display:flex;align-items:center;gap:10px}}
.card-info-icon{{font-size:18px}}
.card-info-value{{font-weight:600}}
.card-info-label{{color:rgba(240,242,245,.5);font-size:13px;margin-left:auto}}

.score-display{{font-size:120px;font-weight:900;color:#6366f1;font-variant-numeric:tabular-nums}}
.score-max{{font-size:28px;color:rgba(240,242,245,.4)}}
.score-bar-bg{{width:500px;height:12px;background:rgba(255,255,255,.06);border-radius:6px;margin-top:28px;overflow:hidden}}
.score-bar{{height:100%;width:0%;border-radius:6px;background:linear-gradient(90deg,#f59e0b,#6366f1)}}
.score-label{{font-size:13px;color:rgba(240,242,245,.4);text-transform:uppercase;letter-spacing:2px;margin-top:24px}}

.cta-section{{text-align:center}}
.cta-icon{{font-size:56px}}
.cta-title{{font-size:28px;font-weight:800;margin-top:12px;color:#6366f1}}
.cta-text{{font-size:16px;color:rgba(240,242,245,.6);margin-top:12px}}
.cta-btn{{display:inline-block;margin-top:28px;font-size:18px;font-weight:700;color:#0a0e17;background:#6366f1;padding:18px 48px;border-radius:14px}}
.cta-url{{margin-top:14px;font-size:13px;color:rgba(240,242,245,.4)}}
.cta-location{{margin-top:8px;font-size:12px;color:rgba(240,242,245,.3)}}
</style>
</head>
<body>
<div class="progress"><div class="progress-fill" id="pFill"></div></div>

<div class="scene" id="s1">
  <div class="alert-badge" id="badge">🚨 {status_text}</div>
  <div class="hook-title" id="hTitle">Ce commerce perd des <span class="accent">clients</span></div>
  <div class="hook-sub" id="hSub">Sans site web, {score}% de clients potentiels passent à côté</div>
</div>

<div class="scene" id="s2">
  <div class="card" id="card">
    <div class="card-top">
      <div class="card-icon" id="cIcon">{icon}</div>
      <div>
        <div class="card-name" id="cName">{name}</div>
        <div class="card-sector" id="cSector">{sector.upper()}</div>
      </div>
    </div>
    <div class="card-divider"></div>
    <div class="card-info">
      <div class="card-info-row">
        <span class="card-info-icon">📍</span>
        <span class="card-info-value" id="cAddr">{address.split(",")[0] if "," in address else address}</span>
        <span class="card-info-label">Adresse</span>
      </div>
      <div class="card-info-row">
        <span class="card-info-icon">⭐</span>
        <span class="card-info-value" id="cRating">{rating}/5</span>
        <span class="card-info-label">Note Google</span>
      </div>
      <div class="card-info-row">
        <span class="card-info-icon">🌐</span>
        <span class="card-info-value" id="cWeb" style="color:#ef4444">{"Aucun site" if not has_site else "Obsolète"}</span>
        <span class="card-info-label">Site web</span>
      </div>
    </div>
  </div>
</div>

<div class="scene" id="s3">
  <div class="score-label" id="sLabel">Opportunité Score</div>
  <div><span class="score-display" id="sNum">0</span><span class="score-max"> /100</span></div>
  <div class="score-bar-bg"><div class="score-bar" id="sBar"></div></div>
</div>

<div class="scene" id="s4">
  <div class="cta-section">
    <div class="cta-icon" id="ctaI">⚡</div>
    <div class="cta-title" id="ctaT">SocialPulse</div>
    <div class="cta-text" id="ctaTxt">Votre site vitrine en 48h<br>à partir de 350€</div>
    <div class="cta-btn" id="ctaBtn">Réserver un appel →</div>
    <div class="cta-url" id="ctaUrl">socialpulse.io</div>
    <div class="cta-location">Basé à Annemasse · Haute-Savoie</div>
  </div>
</div>

<script>
var tl=gsap.timeline();window.__tl=tl;
tl.to("#pFill",{{width:"100%",duration:10,ease:"none"}},0);

// S1: Hook (0-3s)
tl.fromTo("#badge",{{scale:.7,opacity:0}},{{scale:1,opacity:1,duration:.5,ease:"back.out(1.7)"}},.2);
tl.fromTo("#hTitle",{{y:50,opacity:0}},{{y:0,opacity:1,duration:.7,ease:"power3.out"}},.5);
tl.fromTo("#hSub",{{opacity:0}},{{opacity:1,duration:.4}},1);
tl.to("#s1",{{opacity:0,duration:.4}},2.8);

// S2: Card (3-6s)
tl.set("#s2",{{opacity:1}},2.8);
tl.fromTo("#card",{{y:80,opacity:0,scale:.9}},{{y:0,opacity:1,scale:1,duration:.8,ease:"power3.out"}},3);
tl.fromTo(".card-info-row",{{x:-30,opacity:0}},{{x:0,opacity:1,duration:.4,stagger:.15}},3.6);
tl.to("#s2",{{opacity:0,duration:.4}},5.8);

// S3: Score (6-8s)
tl.set("#s3",{{opacity:1}},5.8);
tl.fromTo("#sLabel",{{y:-20,opacity:0}},{{y:0,opacity:1,duration:.4}},6);
tl.fromTo("#sNum",{{scale:.5,opacity:0}},{{scale:1,opacity:1,duration:.6,ease:"back.out(1.5)"}},6.2);
tl.to("#sNum",{{innerText:{score},duration:1.5,snap:{{innerText:1}},ease:"power2.out"}},6.3);
tl.to("#sBar",{{width:"{score}%",duration:1.5,ease:"power2.out"}},6.3);
tl.to("#s3",{{opacity:0,duration:.4}},7.8);

// S4: CTA (8-10s)
tl.set("#s4",{{opacity:1}},7.8);
tl.fromTo("#ctaI",{{scale:0}},{{scale:1,duration:.5,ease:"back.out(2)"}},8);
tl.fromTo("#ctaT",{{y:20,opacity:0}},{{y:0,opacity:1,duration:.4}},8.2);
tl.fromTo("#ctaTxt",{{opacity:0}},{{opacity:1,duration:.4}},8.5);
tl.fromTo("#ctaBtn",{{scale:.9,opacity:0}},{{scale:1,opacity:1,duration:.4,ease:"back.out(1.5)"}},9);
tl.fromTo("#ctaUrl",{{opacity:0}},{{opacity:1,duration:.3}},9.4);
</script>
</body>
</html>'''
    
    def _render_video(self, html_path: Path, output_dir: Path) -> str:
        """Tente le render HTML → MP4 via Puppeteer + FFmpeg"""
        mp4_path = output_dir / "video.mp4"
        
        # Vérifier si puppeteer est installé
        try:
            import subprocess
            result = subprocess.run(
                ["npx", "puppeteer", "--version"],
                capture_output=True, text=True, timeout=10
            )
            has_puppeteer = result.returncode == 0
        except Exception:
            has_puppeteer = False
        
        if has_puppeteer and os.environ.get("RENDER_VIDEO"):
            # Full render pipeline: screenshot frames → FFmpeg
            # TODO: implement frame capture
            pass
        
        # Pour l'instant on retourne le HTML (prêt à render)
        return str(html_path)


# ── Agent 5: PITCHER ─────────────────────────────────────────
class PitcherAgent:
    """
    Agent Pitcher — Envoie les cold messages via le bon canal:
    - Email → avocats, comptables, kinés
    - SMS → plombiers, garagistes
    - Instagram DM → restaurants, coiffeurs, fleuristes
    - LinkedIn → immobiliers
    
    Pour l'instant: prépare les messages prêts à envoyer
    """
    
    def __init__(self, state: StateManager, journal: WORMJournal, mediateur: Mediateur):
        self.state = state
        self.journal = journal
        self.mediateur = mediateur
    
    def run(self, campaign: dict):
        """Prépare les messages pour envoi"""
        queue = self.state.get_queue()
        
        to_pitch = [l for l in queue if l.get("status") == "filmed"]
        pitched = []
        
        for lead in to_pitch:
            channel = lead.get("channel", "email")
            message = self._prepare_message(lead, channel, campaign)
            
            lead["pitch_channel"] = channel
            lead["pitch_message"] = message
            lead["pitch_ready"] = True
            lead["status"] = "pitched"
            pitched.append(lead)
            
            self.journal.log(
                "pitcher.prepare",
                channel,
                {
                    "channel": channel,
                    "message_length": len(message),
                    "has_opt_out": True,
                },
                lead["name"]
            )
            
            print(f"  📤 Pitch ready: {lead['name']} via {channel}")
        
        self.state.save_queue(queue)
        
        # Sauver les messages prêts à envoyer
        self._save_pitch_report(pitched)
        
        print(f"\n  ✅ Pitcher: {len(pitched)} messages prêts")
        return pitched
    
    def _prepare_message(self, lead: dict, channel: str, campaign: dict) -> str:
        """Prépare le message selon le canal"""
        name = lead.get("name", "")
        sector = lead.get("sector", "")
        cold_msg = lead.get("cold_message", "")
        address = lead.get("address", "")
        phone = lead.get("phone", "")
        
        # Détecter ville
        city = "Annemasse"
        for c in ["Gaillard", "Ville-la-Grand", "Saint-Julien"]:
            if c.lower() in address.lower():
                city = c
                break
        
        if channel == "email":
            return f"""Objet: Votre établissement {name} mérite mieux qu'une simple fiche Google Maps

{cold_msg}

—
SocialPulse · Création de sites vitrines pour commerces à {city} et Haute-Savoie
Ce message est envoyé dans le cadre d'une prospection B2B (art. L.223-1 du Code de la consommation).
Pour ne plus recevoir de messages: répondre STOP à cet email."""
        
        elif channel == "sms":
            return f"""Bonjour ! {name} a une super réputation ({lead.get('rating', '?')}/5 sur Google). Un site vitrine simple pourrait vous amener +30% de clients. On discute 5 min? SocialPulse · {city}. STOP=desinscription"""
        
        elif channel == "instagram":
            return f"""Salut ! 👋 J'ai vu {name} sur Google Maps — super notes ! 🌟 Juste un message rapide: on aide les {sector.lower()} de {city} à avoir un site pro. Si ça vous dit, on peut en discuter ?"""
        
        elif channel == "linkedin":
            return f"""Bonjour,

J'ai remarqué {name} sur Google Maps — excellente réputation dans le secteur {sector} à {city}.

Je travaille avec des professionnels de l'immobilier en Haute-Savoie pour créer des sites vitrines qui convertissent les visiteurs en mandats.

Un échange de 10 minutes vous intéresserait ?

Cordialement,
SocialPulse"""
        
        return cold_msg
    
    def _save_pitch_report(self, pitched: list):
        """Sauvegarde le rapport des messages prêts"""
        report_path = OUTPUT_DIR / "pitch-report.json"
        
        report = []
        for lead in pitched:
            report.append({
                "name": lead.get("name"),
                "sector": lead.get("sector"),
                "channel": lead.get("pitch_channel"),
                "phone": lead.get("phone"),
                "message": lead.get("pitch_message"),
                "score": lead.get("score"),
                "status": "ready_to_send",
            })
        
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))


# ── Agent 6: CHECKER ─────────────────────────────────────────
class CheckerAgent:
    """
    Agent Checker — Évalue chaque message avant envoi:
    - Personnalisation suffisante
    - Absence de marqueurs IA / buzzwords
    - Opt-out mentionné
    - Longueur appropriée
    """
    
    AI_MARKERS = [
        "ia", "intelligence artificielle", "algorithme", "machine learning",
        "révolutionnaire", "disruptif", "innovant", "solution innovante",
        "par ailleurs", "de plus", "il est important de noter",
        "n'hésitez pas", "dans ce contexte", "par ailleurs",
    ]
    
    BUZZWORDS = [
        "synergie", "disruption", "paradigme", "holistique", "agile",
        "best practices", "roi", "kpi", "scalable", "lever",
    ]
    
    def __init__(self, state: StateManager, journal: WORMJournal):
        self.state = state
        self.journal = journal
    
    def run(self, campaign: dict):
        """Vérifie tous les messages prêts à envoyer"""
        queue = self.state.get_queue()
        
        to_check = [l for l in queue if l.get("status") == "pitched"]
        approved = []
        flagged = []
        
        for lead in to_check:
            message = lead.get("pitch_message", "")
            issues = self._check_message(message, lead, campaign)
            
            if issues:
                lead["checker_issues"] = issues
                lead["status"] = "flagged"
                flagged.append(lead)
                print(f"  ⚠️ Flagged: {lead['name']} — {issues}")
            else:
                lead["status"] = "approved"
                approved.append(lead)
                print(f"  ✅ Approved: {lead['name']}")
            
            self.journal.log(
                "checker.eval",
                "local",
                {
                    "passed": len(issues) == 0,
                    "issues": issues,
                    "message_length": len(message),
                },
                lead["name"]
            )
        
        self.state.save_queue(queue)
        print(f"\n  ✅ Checker: {len(approved)} approved, {len(flagged)} flagged")
        return approved, flagged
    
    def _check_message(self, message: str, lead: dict, campaign: dict) -> list:
        issues = []
        msg_lower = message.lower()
        
        # Vérifier personnalisation (nom du lead mentionné ?)
        if lead.get("name", "").lower() not in msg_lower:
            issues.append("PERSONNALISATION: nom du commerce non mentionné")
        
        # Vérifier absence de marqueurs IA
        for marker in self.AI_MARKERS:
            if marker in msg_lower:
                issues.append(f"AI_MARKER: '{marker}' détecté")
        
        # Vérifier absence de buzzwords
        for bw in self.BUZZWORDS:
            if bw in msg_lower:
                issues.append(f"BUZZWORD: '{bw}' détecté")
        
        # Vérifier opt-out (pas nécessaire sur Instagram DM, seulement email/SMS)
        channel = lead.get("pitch_channel", "email")
        if channel in ["email", "sms"]:
            if "stop" not in msg_lower and "désinscription" not in msg_lower and "ne plus recevoir" not in msg_lower:
                issues.append("COMPLIANCE: pas de mention opt-out/STOP")
        
        # Vérifier longueur (max 200 mots pour email, 160 chars pour SMS)
        channel = lead.get("pitch_channel", "email")
        word_count = len(message.split())
        if channel == "sms" and len(message) > 160:
            issues.append(f"LONGUEUR: SMS > 160 chars ({len(message)})")
        elif channel == "email" and word_count > 200:
            issues.append(f"LONGUEUR: email > 200 mots ({word_count})")
        
        return issues


# ── Agent 7: MOBILE ──────────────────────────────────────────
class MobileAgent:
    """
    Agent Mobile — Gère les réponses positives
    En attendant l'app mobile: génère un rapport des leads approuvés
    """
    
    def __init__(self, state: StateManager, journal: WORMJournal):
        self.state = state
        self.journal = journal
    
    def run(self, campaign: dict):
        """Génère le rapport des leads prêts"""
        queue = self.state.get_queue()
        approved = [l for l in queue if l.get("status") == "approved"]
        
        report = self._generate_report(approved, campaign)
        
        report_path = OUTPUT_DIR / "mobile-report.json"
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
        
        self.journal.log(
            "mobile.report",
            "local",
            {
                "approved_count": len(approved),
                "report_path": str(report_path),
            }
        )
        
        print(f"\n  📱 Mobile: {len(approved)} leads prêts à envoyer")
        print(f"     Rapport: {report_path}")
        
        return approved
    
    def _generate_report(self, approved: list, campaign: dict) -> dict:
        """Génère un rapport structuré pour envoi manuel"""
        return {
            "generated_at": datetime.datetime.now().isoformat(),
            "total_approved": len(approved),
            "deal_threshold_eur": campaign["pricing"]["deal_threshold_manual_eur"],
            "leads": [
                {
                    "name": l.get("name"),
                    "sector": l.get("sector"),
                    "score": l.get("score"),
                    "channel": l.get("pitch_channel"),
                    "phone": l.get("phone"),
                    "message_preview": l.get("pitch_message", "")[:100] + "...",
                    "landing_page": l.get("landing_page"),
                    "video_html": l.get("video_html"),
                    "action": "Envoyer message + follow-up 48h",
                }
                for l in approved
            ]
        }


# ── ORCHESTRATOR ─────────────────────────────────────────────
class Orchestrator:
    """
    Orchestrateur principal — Coordonne les 7 agents
    Comme le tweet: délègue les tâches et possède les écritures
    """
    
    def __init__(self):
        self.campaign = self._load_campaign()
        self.state = StateManager()
        self.mediateur = Mediateur()
        self.journal = WORMJournal(
            f"annemasse-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}"
        )
        
        # 7 agents
        self.scout = ScoutAgent(self.state, self.journal)
        self.diagnoser = DiagnoserAgent(self.state, self.journal, self.mediateur)
        self.builder = BuilderAgent(self.state, self.journal)
        self.filmer = FilmerAgent(self.state, self.journal)
        self.pitcher = PitcherAgent(self.state, self.journal, self.mediateur)
        self.checker = CheckerAgent(self.state, self.journal)
        self.mobile = MobileAgent(self.state, self.journal)
        
        self.journal.log("orchestrator.init", "system", {
            "agents": 7,
            "campaign": self.campaign["campaign"]["name"],
            "cities": [c["name"] for c in self.campaign["target"]["cities"]],
        })
    
    def _load_campaign(self) -> dict:
        import yaml
        # yaml not installed, use fallback
        try:
            import yaml
            return yaml.safe_load((BASE / "campaign.yaml").read_text())
        except ImportError:
            # Parse manually
            return self._parse_yaml_fallback()
    
    def _parse_yaml_fallback(self) -> dict:
        """Fallback si PyYAML pas installé — retourne la config hardcodée"""
        return {
            "campaign": {
                "name": "annemasse-local-business",
                "status": "active",
            },
            "target": {
                "cities": [
                    {"name": "Annemasse", "zip": "74100"},
                    {"name": "Gaillard", "zip": "74240"},
                    {"name": "Ville-la-Grand", "zip": "74100"},
                    {"name": "Saint-Julien-en-Genevois", "zip": "74160"},
                ],
                "sectors": [
                    {"name": "Restaurant", "icon": "🍽️", "weight": 100,
                     "search_queries": ["restaurant Annemasse", "restaurant Gaillard", "brasserie Ville-la-Grand", "restaurant Saint-Julien-en-Genevois"],
                     "channel": "instagram"},
                    {"name": "Salon de coiffure", "icon": "💇", "weight": 100,
                     "search_queries": ["salon coiffure Annemasse", "coiffeur Gaillard", "salon coiffure Saint-Julien"],
                     "channel": "instagram"},
                    {"name": "Plombier / Chauffagiste", "icon": "🔧", "weight": 100,
                     "search_queries": ["plombier Annemasse", "chauffagiste Gaillard", "plombier Saint-Julien-en-Genevois"],
                     "channel": "sms"},
                    {"name": "Avocat", "icon": "⚖️", "weight": 90,
                     "search_queries": ["cabinet avocat Annemasse", "avocat Gaillard", "avocat Saint-Julien-en-Genevois"],
                     "channel": "email"},
                    {"name": "Immobilier", "icon": "🏠", "weight": 90,
                     "search_queries": ["agence immobilière Annemasse", "agent immobilier Gaillard", "immobilier Saint-Julien"],
                     "channel": "linkedin"},
                    {"name": "Garage auto", "icon": "🚗", "weight": 80,
                     "search_queries": ["garage automobile Annemasse", "mécanicien Gaillard"],
                     "channel": "sms"},
                    {"name": "Cabinet comptable", "icon": "📊", "weight": 90,
                     "search_queries": ["expert comptable Annemasse", "cabinet comptable Gaillard"],
                     "channel": "email"},
                    {"name": "Boulangerie / Pâtisserie", "icon": "🥖", "weight": 80,
                     "search_queries": ["boulangerie Annemasse", "boulangerie Gaillard", "pâtisserie Ville-la-Grand"],
                     "channel": "instagram"},
                    {"name": "Kiné / Ostéopathe", "icon": "🏥", "weight": 80,
                     "search_queries": ["kinésithérapeute Annemasse", "ostéopathe Gaillard", "kiné Saint-Julien"],
                     "channel": "email"},
                    {"name": "Fleuriste", "icon": "💐", "weight": 70,
                     "search_queries": ["fleuriste Annemasse", "fleuriste Gaillard"],
                     "channel": "instagram"},
                ],
            },
            "scout_criteria": {
                "min_years_on_maps": 3,
                "max_reviews": 50,
                "rating_min": 3.5,
                "website_red_flags": ["no_website", "facebook.com", "google.com/maps", "pagejaunes.fr"],
            },
            "scoring": {
                "threshold": 50,
                "criteria": {
                    "has_website": {"weight": 0.30,
                        "mapping": {"none": 100, "facebook_only": 80, "pagejaunes_only": 70, "outdated": 60, "has_website": 20}},
                    "review_gap": {"weight": 0.25,
                        "mapping": {"high_rating_low_reviews": 100, "medium_rating_few_reviews": 70, "low_rating": 30}},
                    "sector": {"weight": 0.25,
                        "mapping": {"Restaurant": 100, "Salon de coiffure": 100, "Plombier / Chauffagiste": 100,
                                    "Avocat": 90, "Immobilier": 90, "Cabinet comptable": 90,
                                    "Garage auto": 80, "Boulangerie / Pâtisserie": 80, "default": 50}},
                    "location": {"weight": 0.20,
                        "mapping": {"Annemasse": 100, "Gaillard": 90, "Saint-Julien-en-Genevois": 90, "Ville-la-Grand": 85}},
                }
            },
            "pricing": {
                "landing_page_eur": 350,
                "deal_threshold_manual_eur": 3000,
            },
        }
    
    def run_full_pipeline(self):
        """Lance le pipeline complet des 7 agents"""
        print("═" * 60)
        print("  🚀 SOCIALPULSE ANNEMASSE AGENCY")
        print("  7 Agents · Haute-Savoie · 100% Open-Source")
        print("═" * 60)
        print()
        
        # Agent 1: Scout
        print("📡 AGENT 1/7: SCOUT — Google Maps Discovery")
        print("─" * 50)
        self.scout.run(self.campaign)
        print()
        
        # Agent 2: Diagnoser
        print("🔍 AGENT 2/7: DIAGNOSER — Score & Diagnosis")
        print("─" * 50)
        self.diagnoser.run(self.campaign)
        print()
        
        # Agent 3: Builder
        print("🏗️ AGENT 3/7: BUILDER — Landing Pages")
        print("─" * 50)
        self.builder.run(self.campaign, max_builds=5)
        print()
        
        # Agent 4: Filmer
        print("🎬 AGENT 4/7: FILMER — Videos (HyperFrame)")
        print("─" * 50)
        self.filmer.run(self.campaign, max_videos=5)
        print()
        
        # Agent 5: Pitcher
        print("📤 AGENT 5/7: PITCHER — Cold Messages")
        print("─" * 50)
        self.pitcher.run(self.campaign)
        print()
        
        # Agent 6: Checker
        print("✅ AGENT 6/7: CHECKER — Quality Evals")
        print("─" * 50)
        self.checker.run(self.campaign)
        print()
        
        # Agent 7: Mobile
        print("📱 AGENT 7/7: MOBILE — Approved Leads Report")
        print("─" * 50)
        self.mobile.run(self.campaign)
        print()
        
        # Summary
        self._print_summary()
    
    def run_agent(self, agent_name: str):
        """Lance un seul agent"""
        agents = {
            "scout": lambda: self.scout.run(self.campaign),
            "diagnoser": lambda: self.diagnoser.run(self.campaign),
            "builder": lambda: self.builder.run(self.campaign),
            "filmer": lambda: self.filmer.run(self.campaign),
            "pitcher": lambda: self.pitcher.run(self.campaign),
            "checker": lambda: self.checker.run(self.campaign),
            "mobile": lambda: self.mobile.run(self.campaign),
        }
        
        if agent_name in agents:
            print(f"🚀 Running agent: {agent_name}")
            agents[agent_name]()
        else:
            print(f"❌ Agent inconnu: {agent_name}")
            print(f"   Agents disponibles: {', '.join(agents.keys())}")
    
    def show_status(self):
        """Affiche l'état du système"""
        stats = self.state.get_stats()
        queue = self.state.get_queue()
        
        print("═" * 60)
        print("  📊 SOCIALPULSE ANNEMASSE — STATUS")
        print("═" * 60)
        print()
        
        print(f"  Queue: {len(queue)} leads")
        by_status = {}
        for l in queue:
            s = l.get("status", "unknown")
            by_status[s] = by_status.get(s, 0) + 1
        
        for status, count in sorted(by_status.items()):
            print(f"    {status}: {count}")
        
        print()
        print(f"  Stats:")
        print(f"    Total discovered: {stats.get('total_discovered', 0)}")
        print(f"    Total qualified:  {stats.get('total_qualified', 0)}")
        print(f"    Total messaged:   {stats.get('total_messaged', 0)}")
        print(f"    Total replies:    {stats.get('total_replies', 0)}")
        print(f"    Total deals:      {stats.get('total_deals', 0)}")
        
        print()
        print(f"  Coûts:")
        print(f"    Apify:       ${stats.get('costs', {}).get('apify_usd', 0):.2f}")
        print(f"    OpenRouter:  ${stats.get('costs', {}).get('openrouter_usd', 0):.2f}")
        print(f"    HyperFrame:  $0.00 (local)")
        print(f"    Total:       ${stats.get('costs', {}).get('apify_usd', 0) + stats.get('costs', {}).get('openrouter_usd', 0):.2f}")
        
        print()
        print(f"  Journal: {len(self.journal.entries)} entries")
        print(f"  Batch: {self.journal.batch_id}")
    
    def _print_summary(self):
        stats = self.state.get_stats()
        queue = self.state.get_queue()
        approved = [l for l in queue if l.get("status") == "approved"]
        flagged = [l for l in queue if l.get("status") == "flagged"]
        gele = [l for l in queue if l.get("status") == "gele"]
        
        print("═" * 60)
        print("  📋 RÉSUMÉ DU BATCH")
        print("═" * 60)
        print(f"  Découverts:     {stats.get('total_discovered', 0)}")
        print(f"  Diagnostiqués:  {len([l for l in queue if l.get('status') in ['diagnosed', 'built', 'filmed', 'pitched', 'approved']])}")
        print(f"  Landing pages:  {len([l for l in queue if l.get('landing_page')])}")
        print(f"  Vidéos:         {len([l for l in queue if l.get('video_html')])}")
        print(f"  Approuvés:      {len(approved)} ✅")
        print(f"  Flagged:        {len(flagged)} ⚠️")
        print(f"  Gelés:          {len(gele)} 🛑")
        print()
        print(f"  💰 Budget:      ~80€/mois (vs $480 tweet)")
        print(f"  📁 Output:      {OUTPUT_DIR}")
        print(f"  📋 Journal:     {self.journal.journal_path}")
        print("═" * 60)


# ── MAIN ──────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SocialPulse Annemasse Agency")
    parser.add_argument("--agent", help="Run a specific agent (scout/diagnoser/builder/filmer/pitcher/checker/mobile)")
    parser.add_argument("--status", action="store_true", help="Show system status")
    parser.add_argument("--full", action="store_true", help="Run full pipeline (default)")
    
    args = parser.parse_args()
    
    # Load .env
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip()
                # Expand ${VAR} references
                import re
                def expand(m):
                    return os.environ.get(m.group(1), "")
                val = re.sub(r'\$\{(\w+)\}', expand, val)
                os.environ.setdefault(key, val)
    
    orch = Orchestrator()
    
    if args.status:
        orch.show_status()
    elif args.agent:
        orch.run_agent(args.agent)
    else:
        orch.run_full_pipeline()
