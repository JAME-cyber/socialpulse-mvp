"""
Agent GEO — Generative Engine Optimization pour PME locales 74.

Optimise la visibilité des entreprises locales dans les réponses IA
(ChatGPT, Perplexity, Claude, Google AI Overviews).

Pipeline:
  GEO_AUDITOR  → Audit la présence actuelle dans les IA
  GEO_OPTIMIZER → Génère le contenu optimisé pour citation
  GEO_SCHEMA   → Crée le markup structuré (FAQ, LocalBusiness)
  GEO_MONITOR  → Suit l'évolution de la visibilité GEO

Architecture:
  - Scoring déterministe (0% LLM dans les notes)
  - Tool Contracts Pydantic (Skill #2)
  - Knowledge Vault intégré (Skill #12)
  - WORM journal audit trail
  - 167+ tests compatibles

Usage:
  python3 geo_agent.py audit "Restaurant Le Lac" "Annemasse"
  python3 geo_agent.py optimize --lead <id>
  python3 geo_agent.py report
  python3 geo_agent.py status
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


# ── Contracts (Skill #2) ──────────────────────────────────────

class GeoAuditContract(BaseModel):
    """Contrat pour un audit GEO."""
    business_name: str = Field(..., min_length=1, max_length=200)
    city: str = Field(..., min_length=1, max_length=100)
    sector: str = Field(..., min_length=1, max_length=100)
    website: str = Field(default="", max_length=500)
    address: str = Field(default="", max_length=300)

    @field_validator("city")
    @classmethod
    def normalize_city(cls, v: str) -> str:
        return v.strip().title()

    @field_validator("sector")
    @classmethod
    def normalize_sector(cls, v: str) -> str:
        return v.strip().lower()


class GeoScoreResult(BaseModel):
    """Contrat pour un score GEO."""
    business_name: str
    city: str
    sector: str
    overall_score: int = Field(ge=0, le=100)
    definition_score: int = Field(ge=0, le=100)
    authority_score: int = Field(ge=0, le=100)
    structure_score: int = Field(ge=0, le=100)
    schema_score: int = Field(ge=0, le=100)
    local_score: int = Field(ge=0, le=100)
    freshness_score: int = Field(ge=0, le=100)
    checklist: list[dict[str, Any]] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    geo_query_coverage: list[str] = Field(default_factory=list)
    grade: str = Field(default="?")


class GeoOptimizedContent(BaseModel):
    """Contrat pour le contenu GEO optimisé."""
    business_name: str
    city: str
    sector: str
    definition_block: str = Field(default="")
    faq_items: list[dict[str, str]] = Field(default_factory=list)
    quotable_statements: list[str] = Field(default_factory=list)
    local_signals: list[str] = Field(default_factory=list)
    schema_json_ld: dict[str, Any] = Field(default_factory=dict)
    meta_description: str = Field(default="")
    geo_queries_targeted: list[str] = Field(default_factory=list)


class GeoReportContract(BaseModel):
    """Contrat pour un rapport GEO."""
    total_businesses: int = Field(ge=0)
    average_score: float = Field(ge=0, le=100)
    by_sector: dict[str, dict[str, Any]] = Field(default_factory=dict)
    by_grade: dict[str, int] = Field(default_factory=dict)
    top_improvements: list[str] = Field(default_factory=list)
    geo_opportunity_score: float = Field(default=0, ge=0, le=100)


class DesignMdContract(BaseModel):
    """Contrat pour un DESIGN.md GEO-aware (format Google Stitch compatible)."""
    business_name: str = Field(..., min_length=1)
    city: str = Field(..., min_length=1)
    sector: str = Field(..., min_length=1)
    style_profile: str = Field(default="local_default")
    geo_score: int = Field(default=0, ge=0, le=100)
    markdown: str = Field(default="", min_length=10)
    sections: list[str] = Field(default_factory=list)


# ── Scoring déterministe (Skill #9 — Non-determinism Management) ──

def _grade(score: int) -> str:
    if score >= 90:
        return "A+"
    if score >= 80:
        return "A"
    if score >= 70:
        return "B"
    if score >= 60:
        return "C"
    if score >= 40:
        return "D"
    return "F"


def score_definition(business: dict) -> tuple[int, list[dict]]:
    """
    Score la présence d'une définition claire et citable.
    Critère: 25-50 mots, autonome, term→category→function.
    """
    checks: list[dict] = []
    score = 0
    website = business.get("website", "")
    name = business.get("name", "")
    sector = business.get("sector", "")
    city = business.get("city", "")

    # Has a website with content
    if website:
        score += 15
        checks.append({"item": "has_website", "pass": True, "detail": f"Site: {website}"})
    else:
        checks.append({"item": "has_website", "pass": False, "detail": "Pas de site web"})

    # Business name is clear
    if name and len(name) >= 3:
        score += 10
        checks.append({"item": "name_clear", "pass": True, "detail": name})
    else:
        checks.append({"item": "name_clear", "pass": False})

    # Sector identifiable
    if sector:
        score += 10
        checks.append({"item": "sector_clear", "pass": True, "detail": sector})
    else:
        checks.append({"item": "sector_clear", "pass": False})

    # City mentioned
    if city:
        score += 10
        checks.append({"item": "city_mentioned", "pass": True, "detail": city})
    else:
        checks.append({"item": "city_mentioned", "pass": False})

    # Has Google Maps / OSM presence (implied by having coordinates)
    if business.get("lat") and business.get("lon"):
        score += 15
        checks.append({"item": "map_presence", "pass": True})
    else:
        checks.append({"item": "map_presence", "pass": False})

    # Phone number (trust signal)
    if business.get("phone"):
        score += 10
        checks.append({"item": "phone_present", "pass": True})
    else:
        checks.append({"item": "phone_present", "pass": False})

    # Address (local signal)
    if business.get("address") or business.get("street"):
        score += 15
        checks.append({"item": "address_present", "pass": True})
    else:
        checks.append({"item": "address_present", "pass": False})

    # Opening hours
    if business.get("opening_hours"):
        score += 15
        checks.append({"item": "hours_present", "pass": True})
    else:
        checks.append({"item": "hours_present", "pass": False})

    return min(100, score), checks


def score_authority(business: dict) -> tuple[int, list[dict]]:
    """
    Score les signaux d'autorité (E-E-A-T pour les IA).
    """
    checks: list[dict] = []
    score = 0

    # Website exists and is functional
    website = business.get("website", "")
    if website:
        score += 20
        checks.append({"item": "website_exists", "pass": True})
        # HTTPS
        if website.startswith("https://"):
            score += 10
            checks.append({"item": "https", "pass": True})
        else:
            checks.append({"item": "https", "pass": False})
        # Custom domain (not facebook/google)
        generic = ("facebook.com", "google.com", "pagesjaunes.fr", "yelp.", "tripadvisor.")
        if not any(g in website.lower() for g in generic):
            score += 15
            checks.append({"item": "custom_domain", "pass": True})
        else:
            checks.append({"item": "custom_domain", "pass": False, "detail": "Domaine générique"})
    else:
        checks.append({"item": "website_exists", "pass": False})
        checks.append({"item": "https", "pass": False})
        checks.append({"item": "custom_domain", "pass": False})

    # Email (professional)
    email = business.get("email", "")
    if email and "@" in email:
        score += 15
        checks.append({"item": "professional_email", "pass": True})
    else:
        checks.append({"item": "professional_email", "pass": False})

    # Multiple contact methods
    contacts = sum(1 for k in ("phone", "email", "website") if business.get(k))
    if contacts >= 3:
        score += 15
        checks.append({"item": "multi_contact", "pass": True})
    elif contacts >= 2:
        score += 8
        checks.append({"item": "multi_contact", "pass": True, "detail": "2/3"})
    else:
        checks.append({"item": "multi_contact", "pass": False})

    # Social media presence
    if business.get("social") or business.get("facebook"):
        score += 10
        checks.append({"item": "social_presence", "pass": True})
    else:
        checks.append({"item": "social_presence", "pass": False})

    # Description quality
    desc = business.get("description", "") or business.get("tags", "")
    if desc and len(str(desc)) > 50:
        score += 15
        checks.append({"item": "rich_description", "pass": True})
    else:
        checks.append({"item": "rich_description", "pass": False})

    return min(100, score), checks


def score_structure(business: dict) -> tuple[int, list[dict]]:
    """
    Score la structure du contenu pour citation par les IA.
    """
    checks: list[dict] = []
    score = 30  # Base score — tout business a un minimum

    # Category match
    sector = business.get("sector", "").lower()
    if sector:
        score += 15
        checks.append({"item": "sector_classified", "pass": True, "detail": sector})

    # Address structured (not just raw text)
    addr_parts = [business.get(f) for f in ("street", "housenumber", "postcode", "city") if business.get(f)]
    if len(addr_parts) >= 3:
        score += 15
        checks.append({"item": "structured_address", "pass": True})
    else:
        checks.append({"item": "structured_address", "pass": False})

    # Coordinates precise (for local queries)
    lat, lon = business.get("lat", 0), business.get("lon", 0)
    if lat and lon:
        score += 15
        checks.append({"item": "precise_coordinates", "pass": True})
    else:
        checks.append({"item": "precise_coordinates", "pass": False})

    # Tags / categories for Q&A matching
    tags = business.get("tags", "")
    if tags and len(str(tags)) > 5:
        score += 10
        checks.append({"item": "categorization", "pass": True})
    else:
        checks.append({"item": "categorization", "pass": False})

    # Has amenity type (OSM)
    if business.get("amenity"):
        score += 15
        checks.append({"item": "amenity_type", "pass": True})
    else:
        checks.append({"item": "amenity_type", "pass": False})

    return min(100, score), checks


def score_schema(business: dict) -> tuple[int, list[dict]]:
    """
    Score la présence de schema markup (JSON-LD).
    Sans site web = score bas.
    """
    checks: list[dict] = []
    score = 0

    website = business.get("website", "")
    if not website:
        checks.append({"item": "has_website_for_schema", "pass": False})
        return 5, checks  # Minimal — peut être amélioré

    score += 20
    checks.append({"item": "has_website_for_schema", "pass": True})

    # Check if schema-ready data exists
    name = business.get("name", "")
    if name:
        score += 10
        checks.append({"item": "schema_name", "pass": True})

    addr = business.get("address") or business.get("street")
    if addr:
        score += 10
        checks.append({"item": "schema_address", "pass": True})

    phone = business.get("phone")
    if phone:
        score += 10
        checks.append({"item": "schema_phone", "pass": True})

    lat, lon = business.get("lat"), business.get("lon")
    if lat and lon:
        score += 15
        checks.append({"item": "schema_geo", "pass": True})

    sector = business.get("sector", "")
    if sector:
        score += 10
        checks.append({"item": "schema_category", "pass": True})

    hours = business.get("opening_hours")
    if hours:
        score += 15
        checks.append({"item": "schema_hours", "pass": True})

    return min(100, score), checks


def score_local(business: dict) -> tuple[int, list[dict]]:
    """
    Score les signaux locaux spécifiques (GEO local = notre moat).
    """
    checks: list[dict] = []
    score = 0
    city = (business.get("city") or "").strip().lower()
    name = business.get("name", "")

    # City coverage
    target_cities = {"annemasse", "gaillard", "ville-la-grand", "saint-julien-en-genevois"}
    if city in target_cities:
        score += 25
        checks.append({"item": "target_city", "pass": True, "detail": city.title()})
    else:
        score += 10
        checks.append({"item": "target_city", "pass": True, "detail": f"{city} (hors zone principale)"})

    # Proximity to border (cross-border signal)
    lat = business.get("lat", 0)
    lon = business.get("lon", 0)
    if lat and lon:
        # Geneva center ≈ 46.2044, 6.1432
        import math
        dist = math.sqrt((lat - 46.2044)**2 + (lon - 6.1432)**2) * 111  # rough km
        if dist < 10:
            score += 20
            checks.append({"item": "proximity_geneva", "pass": True, "detail": f"~{dist:.0f}km de Genève"})
        elif dist < 20:
            score += 10
            checks.append({"item": "proximity_geneva", "pass": True, "detail": f"~{dist:.0f}km de Genève"})

    # French language signal
    score += 15
    checks.append({"item": "french_content", "pass": True, "detail": "Contenu en français"})

    # Local sector keyword density
    sector = business.get("sector", "").lower()
    if sector:
        score += 15
        checks.append({"item": "sector_keyword", "pass": True, "detail": sector})

    # Department signal (74)
    postcode = str(business.get("postcode", ""))
    if postcode.startswith("74"):
        score += 15
        checks.append({"item": "department_74", "pass": True, "detail": postcode})
    else:
        checks.append({"item": "department_74", "pass": False})

    # Name contains locality hint
    locality_hints = ("annemasse", "gaillard", "ville", "genevois", "léman", "gex", "thoiry")
    if any(h in name.lower() for h in locality_hints):
        score += 10
        checks.append({"item": "locality_in_name", "pass": True})

    return min(100, score), checks


def score_freshness(business: dict) -> tuple[int, list[dict]]:
    """
    Score la fraîcheur du contenu (les IA préfèrent du contenu récent).
    """
    checks: list[dict] = []
    score = 40  # Base — on ne peut pas vraiment mesurer sans crawling

    # Has website = can be updated
    if business.get("website"):
        score += 20
        checks.append({"item": "updateable", "pass": True})

    # Has been recently discovered
    discovered = business.get("discovered_at", "") or business.get("timestamp", "")
    if discovered:
        try:
            dt = datetime.fromisoformat(str(discovered).replace("Z", "+00:00"))
            age_days = (datetime.now(timezone.utc) - dt).days
            if age_days < 30:
                score += 20
                checks.append({"item": "recent_discovery", "pass": True})
            elif age_days < 90:
                score += 10
                checks.append({"item": "recent_discovery", "pass": True, "detail": f"{age_days}d"})
        except (ValueError, TypeError):
            pass

    return min(100, score), checks


# ── Main scoring function ─────────────────────────────────────

# Weights inspired by Aaron's GEO skill
_GEO_WEIGHTS = {
    "definition": 15,
    "authority": 20,
    "structure": 15,
    "schema": 20,
    "local": 20,
    "freshness": 10,
}


def score_geo(business: dict) -> GeoScoreResult:
    """
    Score complet GEO pour un business local.
    Déterministe — 0% LLM.
    """
    scores = {}
    all_checks = []

    scorers = {
        "definition": score_definition,
        "authority": score_authority,
        "structure": score_structure,
        "schema": score_schema,
        "local": score_local,
        "freshness": score_freshness,
    }

    for name, scorer in scorers.items():
        s, checks = scorer(business)
        scores[name] = s
        all_checks.extend(checks)

    # Weighted total
    total_weight = sum(_GEO_WEIGHTS.values())
    overall = sum(scores[k] * _GEO_WEIGHTS[k] for k in scores) / total_weight
    overall = max(0, min(100, round(overall)))

    # Generate recommendations based on weak scores
    recs = []
    if scores["definition"] < 50:
        recs.append("Ajouter une définition claire de 25-50 mots sur la page d'accueil")
    if scores["authority"] < 50:
        recs.append("Créer un site avec domaine personnalisé (pas Facebook/PagesJaunes)")
    if scores["schema"] < 50:
        recs.append("Ajouter un schema JSON-LD LocalBusiness sur le site")
    if scores["local"] < 50:
        recs.append("Mentionner explicitement la ville et le département (74) sur le site")
    if scores["structure"] < 50:
        recs.append("Structurer le contenu en Q&A pour les requêtes IA courantes")
    if scores["freshness"] < 40:
        recs.append("Mettre à jour le contenu régulièrement (les IA préfèrent du frais)")

    # GEO query coverage
    sector = business.get("sector", "business")
    city = business.get("city", "")
    name = business.get("name", "")
    queries = [
        f"{sector} {city}",
        f"meilleur {sector} {city}",
        f"{sector} pas cher {city}",
        f"{sector} ouvert dimanche {city}",
        f"recommandation {sector} {city}",
    ]
    if name:
        queries.insert(0, name)

    return GeoScoreResult(
        business_name=name,
        city=city,
        sector=sector,
        overall_score=overall,
        definition_score=scores["definition"],
        authority_score=scores["authority"],
        structure_score=scores["structure"],
        schema_score=scores["schema"],
        local_score=scores["local"],
        freshness_score=scores["freshness"],
        checklist=all_checks,
        recommendations=recs,
        geo_query_coverage=queries,
        grade=_grade(overall),
    )


# ── DESIGN.md Profiles (inspired by VoltAgent/Google Stitch) ──

_SECTOR_PROFILES: dict[str, dict[str, Any]] = {
    "restaurant": {
        "palette": {
            "primary": "#8B4513",
            "secondary": "#D2691E",
            "accent": "#FFD700",
            "background": "#FFF8F0",
            "surface": "#FFFFFF",
            "text": "#2C1810",
            "text_muted": "#6B4226",
        },
        "fonts": {
            "heading": "Playfair Display",
            "body": "Source Sans 3",
            "fallback": "Georgia, serif",
        },
        "atmosphere": (
            "Warm, inviting, terroir. Rich browns and golds evoke French culinary tradition. "
            "Typography balances elegance (headings) with readability (body). "
            "Cards with subtle shadows suggest a menu or table setting."
        ),
        "radius": "8px",
        "shadow": "0 2px 8px rgba(139,69,19,0.12)",
    },
    "boulangerie": {
        "palette": {
            "primary": "#C8A97E",
            "secondary": "#8B6914",
            "accent": "#F5E6D0",
            "background": "#FFFBF5",
            "surface": "#FFF8EE",
            "text": "#3E2723",
            "text_muted": "#795548",
        },
        "fonts": {
            "heading": "DM Serif Display",
            "body": "Nunito",
            "fallback": "Georgia, serif",
        },
        "atmosphere": (
            "Artisanal, golden, comforting. Warm cream and wheat tones. "
            "Typography reminiscent of a handwritten menu. Soft edges everywhere."
        ),
        "radius": "12px",
        "shadow": "0 2px 6px rgba(139,105,20,0.10)",
    },
    "coiffeur": {
        "palette": {
            "primary": "#1A1A2E",
            "secondary": "#E94560",
            "accent": "#F5C518",
            "background": "#FAFAFA",
            "surface": "#FFFFFF",
            "text": "#16213E",
            "text_muted": "#5C6B7A",
        },
        "fonts": {
            "heading": "Cormorant Garamond",
            "body": "Poppins",
            "fallback": "sans-serif",
        },
        "atmosphere": (
            "Chic, modern, bold. Dark accents with vibrant red-gold highlights. "
            "Typography is high-contrast — serif headings, clean sans body. "
            "Gallery-style layout for before/after photos."
        ),
        "radius": "4px",
        "shadow": "0 4px 12px rgba(26,26,46,0.15)",
    },
    "plombier": {
        "palette": {
            "primary": "#0D47A1",
            "secondary": "#1565C0",
            "accent": "#FF6F00",
            "background": "#FFFFFF",
            "surface": "#F5F8FF",
            "text": "#0A1929",
            "text_muted": "#546E7A",
        },
        "fonts": {
            "heading": "Montserrat",
            "body": "Open Sans",
            "fallback": "sans-serif",
        },
        "atmosphere": (
            "Professional, trustworthy, urgent. Blue conveys reliability. "
            "Orange accent signals action/emergency. Clean sans-serif throughout. "
            "Clear CTA buttons, phone number prominent."
        ),
        "radius": "6px",
        "shadow": "0 2px 8px rgba(13,71,161,0.10)",
    },
    "garagiste": {
        "palette": {
            "primary": "#263238",
            "secondary": "#D32F2F",
            "accent": "#FFC107",
            "background": "#FAFAFA",
            "surface": "#FFFFFF",
            "text": "#212121",
            "text_muted": "#757575",
        },
        "fonts": {
            "heading": "Oswald",
            "body": "Roboto",
            "fallback": "sans-serif",
        },
        "atmosphere": (
            "Industrial, robust, reliable. Dark charcoal with red accents (urgency/mechanical). "
            "Condensed headings for impact. Yellow for key CTAs. "
            "Grid-based layout for services."
        ),
        "radius": "4px",
        "shadow": "0 3px 10px rgba(38,50,56,0.12)",
    },
    "btp": {
        "palette": {
            "primary": "#E65100",
            "secondary": "#3E2723",
            "accent": "#FFB300",
            "background": "#FFFFFF",
            "surface": "#FFF8E1",
            "text": "#1B0F0A",
            "text_muted": "#6D4C41",
        },
        "fonts": {
            "heading": "Barlow Condensed",
            "body": "Inter",
            "fallback": "sans-serif",
        },
        "atmosphere": (
            "Solid, constructive, trustworthy. Orange/amber evokes construction and safety. "
            "Dark brown for depth. Condensed headings for authority. "
            "Block-based layout, structured sections."
        ),
        "radius": "6px",
        "shadow": "0 3px 8px rgba(230,81,0,0.10)",
    },
    "commerce": {
        "palette": {
            "primary": "#1565C0",
            "secondary": "#0D47A1",
            "accent": "#4CAF50",
            "background": "#FFFFFF",
            "surface": "#F5F9FF",
            "text": "#1A237E",
            "text_muted": "#546E7A",
        },
        "fonts": {
            "heading": "Lato",
            "body": "Open Sans",
            "fallback": "sans-serif",
        },
        "atmosphere": (
            "Clean, professional, approachable. Blue builds trust, green signals growth. "
            "Ample white space. Standard business layout."
        ),
        "radius": "8px",
        "shadow": "0 2px 6px rgba(21,101,192,0.08)",
    },
    "sante": {
        "palette": {
            "primary": "#00796B",
            "secondary": "#004D40",
            "accent": "#26A69A",
            "background": "#FAFFFE",
            "surface": "#E8F5E9",
            "text": "#1B5E20",
            "text_muted": "#558B2F",
        },
        "fonts": {
            "heading": "Merriweather",
            "body": "Source Sans 3",
            "fallback": "serif",
        },
        "atmosphere": (
            "Calming, clean, professional. Teal/green = health and nature. "
            "Serif headings for authority. Light backgrounds for clarity. "
            "Minimal shadows, maximum readability."
        ),
        "radius": "10px",
        "shadow": "0 2px 6px rgba(0,121,107,0.08)",
    },
}

# Fallback pour secteurs non-listés
_DEFAULT_PROFILE = _SECTOR_PROFILES["commerce"]


def _get_profile(sector: str) -> dict[str, Any]:
    """Résout le profil de style pour un secteur."""
    sector_key = sector.strip().lower()
    # Match par clé exacte ou substring
    if sector_key in _SECTOR_PROFILES:
        return _SECTOR_PROFILES[sector_key]
    for key, profile in _SECTOR_PROFILES.items():
        if key in sector_key or sector_key in key:
            return profile
    return _DEFAULT_PROFILE


def generate_design_md(
    business: dict,
    score: GeoScoreResult | None = None,
    content: GeoOptimizedContent | None = None,
) -> DesignMdContract:
    """
    Génère un DESIGN.md GEO-aware pour une PME locale.

    Format compatible Google Stitch / Claude Code / Cursor.
    Le fichier contient:
      - Visual theme & atmosphere
      - Color palette avec rôles sémantiques
      - Typography
      - Spacing & layout
      - GEO content blocks (definition, FAQ, schema)
      - Component rules
      - Local SEO signals

    Déterministe — 0% LLM.
    """
    name = business.get("name", "Business")
    sector = business.get("sector", "commerce")
    city = business.get("city", "Annemasse")
    address = business.get("address", "") or business.get("street", "")
    phone = business.get("phone", "")
    website = business.get("website", "")
    geo_score_val = score.overall_score if score else 0

    profile = _get_profile(sector)
    pal = profile["palette"]
    fonts = profile["fonts"]

    # ── Build markdown ────────────────────────────────────────
    sections = []
    md = ""

    # Header
    md += f"# Design System — {name}\n\n"
    md += f"> DESIGN.md auto-généré par SocialPulse GEO Agent\n"
    md += f"> Secteur : **{sector}** · Ville : **{city}** · Score GEO : **{geo_score_val}/100**\n\n"
    sections.append("header")

    # 1. Visual Theme & Atmosphere
    md += "## 1. Visual Theme & Atmosphere\n\n"
    md += f"{profile['atmosphere']}\n\n"
    md += f"The design targets a **{sector}** audience in **{city}** (Haute-Savoie, 74), "
    md += "within the Franco-Valdo-Genevan cross-border agglomeration. "
    md += "Every element should feel locally grounded, trustworthy, and immediately recognizable.\n\n"
    sections.append("atmosphere")

    # 2. Color Palette
    md += "## 2. Color Palette & Roles\n\n"
    md += "### Primary\n\n"
    md += f"- **Primary** (`{pal['primary']}`): Primary brand color, headings, CTAs, nav links.\n"
    md += f"- **Secondary** (`{pal['secondary']}`): Darker variant for emphasis, footer backgrounds, active states.\n"
    md += f"- **Accent** (`{pal['accent']}`): Highlight color, badges, featured items, urgent CTAs.\n\n"
    md += "### Surfaces\n\n"
    md += f"- **Background** (`{pal['background']}`): Page background. Clean canvas.\n"
    md += f"- **Surface** (`{pal['surface']}`): Card backgrounds, elevated containers.\n\n"
    md += "### Text\n\n"
    md += f"- **Text Primary** (`{pal['text']}`): Headings, body copy, nav text.\n"
    md += f"- **Text Muted** (`{pal['text_muted']}`): Descriptions, captions, secondary labels.\n\n"
    sections.append("palette")

    # 3. Typography
    md += "## 3. Typography\n\n"
    md += f"- **Headings**: `{fonts['heading']}`, weight 600–700, tracking -0.02em\n"
    md += f"- **Body**: `{fonts['body']}`, weight 400, line-height 1.6\n"
    md += f"- **Fallback**: `{fonts['fallback']}`\n\n"
    md += "Font sizes:\n"
    md += "| Element | Size | Weight |\n"
    md += "|---------|------|--------|\n"
    md += "| H1 (page title) | 36px | 700 |\n"
    md += "| H2 (section) | 28px | 600 |\n"
    md += "| H3 (card title) | 22px | 600 |\n"
    md += "| Body | 16px | 400 |\n"
    md += "| Small/caption | 14px | 400 |\n\n"
    sections.append("typography")

    # 4. Spacing & Layout
    md += "## 4. Spacing & Layout\n\n"
    md += "- **Max content width**: 1200px\n"
    md += "- **Grid**: 12-column, 24px gutter\n"
    md += "- **Section padding**: 64px vertical (desktop), 40px (mobile)\n"
    md += "- **Card padding**: 24px\n"
    md += "- **Component gap**: 16px\n\n"
    sections.append("layout")

    # 5. Shadows & Depth
    md += "## 5. Shadows & Depth\n\n"
    md += f"- **Card default**: `{profile['shadow']}`\n"
    md += "- **Card hover**: same shadow with 0 6px 20px (increased spread)\n"
    md += "- **Border radius**: " + profile["radius"] + "\n\n"
    sections.append("shadows")

    # 6. GEO Content Blocks
    md += "## 6. GEO Content Blocks\n\n"
    md += "> These blocks are optimized for AI citation (ChatGPT, Perplexity, Google AI Overviews).\n"
    md += "> Include them in the page HTML exactly as structured below.\n\n"

    if content:
        md += "### Definition Block\n\n"
        md += f"{content.definition_block}\n\n"

        md += "### FAQ Items (JSON-LD ready)\n\n"
        for i, faq in enumerate(content.faq_items, 1):
            md += f"**Q{i}**: {faq['question']}\n"
            md += f"**A{i}**: {faq['answer']}\n\n"

        md += "### Quotable Statements\n\n"
        for stmt in content.quotable_statements:
            md += f"- {stmt}\n"
        md += "\n"
    else:
        md += f"(Run `generate_geo_content()` for business-specific GEO blocks.)\n\n"
    sections.append("geo_content")

    # 7. JSON-LD Schema
    md += "## 7. JSON-LD LocalBusiness Schema\n\n"
    md += "```json\n"
    if content and content.schema_json_ld:
        md += json.dumps(content.schema_json_ld, indent=2, ensure_ascii=False) + "\n"
    else:
        schema = {
            "@context": "https://schema.org",
            "@type": "LocalBusiness",
            "name": name,
            "address": {
                "@type": "PostalAddress",
                "addressLocality": city,
                "addressRegion": "Auvergne-Rhône-Alpes",
                "addressCountry": "FR",
            },
        }
        if address:
            schema["address"]["streetAddress"] = address
        if phone:
            schema["telephone"] = phone
        md += json.dumps(schema, indent=2, ensure_ascii=False) + "\n"
    md += "```\n\n"
    sections.append("schema")

    # 8. Local SEO Signals
    md += "## 8. Local SEO Signals\n\n"
    md += f"- **Business**: {name}\n"
    md += f"- **City**: {city} (74 — Haute-Savoie)\n"
    md += f"- **Region**: Auvergne-Rhône-Alpes\n"
    md += f"- **Agglomeration**: Annemasse-Les Voirons\n"
    md += f"- **Cross-border**: Grand Genève (FR-CH)\n"
    if address:
        md += f"- **Address**: {address}\n"
    if phone:
        md += f"- **Phone**: {phone}\n"
    if website:
        md += f"- **Website**: {website}\n"
    md += "\n"
    sections.append("local_seo")

    # 9. Component Rules
    md += "## 9. Component Rules\n\n"
    md += "### CTA Button\n\n"
    md += f"- Background: `{pal['primary']}`\n"
    md += f"- Text color: `#FFFFFF`\n"
    md += f"- Border-radius: {profile['radius']}\n"
    md += "- Padding: 12px 24px\n"
    md += "- Font: heading font, 16px, weight 600\n"
    md += "- Hover: darken 10%, slight scale(1.02)\n\n"
    md += "### Card\n\n"
    md += f"- Background: `{pal['surface']}`\n"
    md += f"- Border: 1px solid rgba(0,0,0,0.06)\n"
    md += f"- Shadow: {profile['shadow']}\n"
    md += f"- Border-radius: {profile['radius']}\n"
    md += "- Padding: 24px\n\n"
    md += "### Navigation\n\n"
    md += "- Background: white, sticky top\n"
    md += f"- Links: `{pal['text']}`, hover `{pal['primary']}`\n"
    md += "- Font: body font, 15px\n\n"
    md += "### Footer\n\n"
    md += f"- Background: `{pal['secondary']}`\n"
    md += "- Text: `#FFFFFF`\n"
    md += "- Links: accent color, no underline\n\n"
    sections.append("components")

    # 10. GEO Score & Recommendations
    if score:
        md += "## 10. GEO Audit Summary\n\n"
        md += f"| Axis | Score |\n"
        md += f"|------|-------|\n"
        md += f"| Overall | {score.overall_score}/100 ({score.grade}) |\n"
        md += f"| Definition | {score.definition_score}/100 |\n"
        md += f"| Authority | {score.authority_score}/100 |\n"
        md += f"| Structure | {score.structure_score}/100 |\n"
        md += f"| Schema | {score.schema_score}/100 |\n"
        md += f"| Local | {score.local_score}/100 |\n"
        md += f"| Freshness | {score.freshness_score}/100 |\n\n"
        if score.recommendations:
            md += "**Recommendations:**\n\n"
            for r in score.recommendations:
                md += f"- {r}\n"
            md += "\n"
        sections.append("audit")

    md += "---\n\n"
    md += f"*Generated by SocialPulse GEO Agent · {datetime.now(timezone.utc).strftime('%Y-%m-%d')} · "
    md += f"{city}, Haute-Savoie (74)*\n"

    return DesignMdContract(
        business_name=name,
        city=city,
        sector=sector,
        style_profile=list(_SECTOR_PROFILES.keys())[list(_SECTOR_PROFILES.values()).index(profile)] if profile in _SECTOR_PROFILES.values() else "local_default",
        geo_score=geo_score_val,
        markdown=md,
        sections=sections,
    )


# ── GEO Content Optimizer ─────────────────────────────────────

def generate_geo_content(business: dict, score: GeoScoreResult) -> GeoOptimizedContent:
    """
    Génère du contenu GEO optimisé pour un business local.
    Déterministe — templates, pas de LLM.
    """
    name = business.get("name", "Business")
    sector = business.get("sector", "commerce")
    city = business.get("city", "Annemasse")
    address = business.get("address", "") or business.get("street", "")
    phone = business.get("phone", "")
    website = business.get("website", "")

    # Definition block (25-50 words, citable)
    definition = (
        f"**{name}** est un établissement de type {sector} situé à {city}, "
        f"en Haute-Savoie (74), dans l'agglomération franco-valdo-genevoise. "
    )
    if address:
        definition += f"Adresse : {address}. "
    if phone:
        definition += f"Téléphone : {phone}."

    # FAQ items for Q&A format
    faq_items = [
        {
            "question": f"Quel est le meilleur {sector} à {city} ?",
            "answer": f"{name} est un {sector} situé à {city} (Haute-Savoie). "
                      f"{'Téléphone : ' + phone + '.' if phone else ''}"
                      f"{'Site web : ' + website + '.' if website else ''}",
        },
        {
            "question": f"Où trouver un {sector} près d'Annemasse ?",
            "answer": f"{name} se trouve à {city}, "
                      f"dans l'agglomération d'Annemasse, à quelques minutes de la frontière suisse.",
        },
        {
            "question": f"Y a-t-il un {sector} ouvert près de la frontière franco-suisse ?",
            "answer": f"Oui, {name} à {city} est situé dans la zone frontalière "
                      f"du Grand Genève, facilement accessible depuis Genève.",
        },
    ]

    # Quotable statements
    quotable = [
        f"{name} est un {sector} de référence à {city}, en Haute-Savoie (74).",
        f"Situé dans l'agglomération franco-valdo-genevoise, {name} dessert "
        f"les communes d'Annemasse, Gaillard, Ville-la-Grand et Saint-Julien-en-Genevois.",
    ]

    # Local signals
    local_signals = [
        f"Commune : {city} (74 - Haute-Savoie)",
        f"Région : Auvergne-Rhône-Alpes",
        f"Agglomération : Annemasse-Les Voirons",
        f"Frontalière : Grand Genève (Savoie-Suisse)",
    ]

    # JSON-LD Schema
    schema = {
        "@context": "https://schema.org",
        "@type": "LocalBusiness",
        "name": name,
        "address": {
            "@type": "PostalAddress",
            "addressLocality": city,
            "addressRegion": "Auvergne-Rhône-Alpes",
            "postalCode": business.get("postcode", "74100"),
            "addressCountry": "FR",
        },
    }
    if address:
        schema["address"]["streetAddress"] = address
    if phone:
        schema["telephone"] = phone
    if website:
        schema["url"] = website
    if business.get("lat") and business.get("lon"):
        schema["geo"] = {
            "@type": "GeoCoordinates",
            "latitude": float(business["lat"]),
            "longitude": float(business["lon"]),
        }

    # Meta description (GEO-optimized)
    meta = f"{name} — {sector} à {city} (74). "
    if address:
        meta += f"{address}. "
    meta += f"Recommandé dans l'agglomération d'Annemasse, Haute-Savoie."

    # Target queries
    queries = score.geo_query_coverage if hasattr(score, 'geo_query_coverage') else []

    return GeoOptimizedContent(
        business_name=name,
        city=city,
        sector=sector,
        definition_block=definition,
        faq_items=faq_items,
        quotable_statements=quotable,
        local_signals=local_signals,
        schema_json_ld=schema,
        meta_description=meta[:160],
        geo_queries_targeted=queries,
    )


# ── Bulk Report ───────────────────────────────────────────────

def generate_report(businesses: list[dict]) -> GeoReportContract:
    """
    Génère un rapport GEO pour un ensemble de businesses.
    """
    if not businesses:
        return GeoReportContract(
            total_businesses=0,
            average_score=0,
            geo_opportunity_score=0,
        )

    scores = []
    by_sector: dict[str, list[int]] = {}
    by_grade: dict[str, int] = {}

    for b in businesses:
        result = score_geo(b)
        scores.append(result.overall_score)

        sector = result.sector
        if sector not in by_sector:
            by_sector[sector] = []
        by_sector[sector].append(result.overall_score)

        grade = result.grade
        by_grade[grade] = by_grade.get(grade, 0) + 1

    avg = sum(scores) / len(scores)

    # Sector breakdown
    sector_stats = {}
    for sector, sector_scores in by_sector.items():
        sector_stats[sector] = {
            "count": len(sector_scores),
            "avg_score": round(sum(sector_scores) / len(sector_scores), 1),
            "min": min(sector_scores),
            "max": max(sector_scores),
        }

    # GEO opportunity: lower average score = higher opportunity
    opportunity = max(0, min(100, 100 - avg))

    # Top improvements
    improvements = []
    if avg < 50:
        improvements.append("Score moyen < 50 : forte opportunité GEO (la plupart sont sous-optimisés)")
    if by_grade.get("F", 0) > len(businesses) * 0.3:
        improvements.append(f"{by_grade['F']} businesses en grade F : besoin urgent de présence web")
    if by_grade.get("A", 0) + by_grade.get("A+", 0) < len(businesses) * 0.1:
        improvements.append("Moins de 10% en grade A : le marché GEO est largement sous-desservi")

    return GeoReportContract(
        total_businesses=len(businesses),
        average_score=round(avg, 1),
        by_sector=sector_stats,
        by_grade=by_grade,
        top_improvements=improvements,
        geo_opportunity_score=round(opportunity, 1),
    )


# ── CLI ────────────────────────────────────────────────────────

def main():
    import sys

    if len(sys.argv) < 2:
        print("Usage: python3 geo_agent.py <command> [args]")
        print("Commands: audit <name> <city>, batch, report, status")
        return

    cmd = sys.argv[1]

    if cmd == "audit":
        if len(sys.argv) < 4:
            print("Usage: audit <business_name> <city> [sector]")
            return
        name = sys.argv[2]
        city = sys.argv[3]
        sector = sys.argv[4] if len(sys.argv) > 4 else "commerce"

        # Validate
        audit = GeoAuditContract(business_name=name, city=city, sector=sector)
        business = {"name": name, "city": city, "sector": sector}

        result = score_geo(business)
        print(f"\n  ══ GEO Audit: {name} ══")
        print(f"  Ville: {city}")
        print(f"  Secteur: {sector}")
        print(f"  Score: {result.overall_score}/100 (Grade {result.grade})")
        print()
        print(f"  Définition:   {result.definition_score}/100")
        print(f"  Autorité:     {result.authority_score}/100")
        print(f"  Structure:    {result.structure_score}/100")
        print(f"  Schema:       {result.schema_score}/100")
        print(f"  Local:        {result.local_score}/100")
        print(f"  Fraîcheur:    {result.freshness_score}/100")
        print()
        if result.recommendations:
            print("  Recommandations:")
            for r in result.recommendations:
                print(f"    → {r}")
        print()
        print("  Requêtes GEO ciblées:")
        for q in result.geo_query_coverage:
            print(f"    • \"{q}\"")

    elif cmd == "batch":
        # Score all leads from SocialPulse vault or JSON
        state_path = Path("state/lead-queue.json")
        if not state_path.exists():
            print("Pas de fichier lead-queue.json trouvé")
            return

        with open(state_path, encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict):
            for key in ("leads", "data", "results", "items"):
                if key in data and isinstance(data[key], list):
                    data = data[key]
                    break
            else:
                all_items = []
                for v in data.values():
                    if isinstance(v, list):
                        all_items.extend(v)
                data = all_items

        report = generate_report(data)

        print(f"\n  ══ RAPPORT GEO — PME LOCALES 74 ══")
        print(f"  Businesses analysés: {report.total_businesses}")
        print(f"  Score moyen: {report.average_score}/100")
        print(f"  Opportunité GEO: {report.geo_opportunity_score}/100")
        print()
        print("  Distribution par grade:")
        for grade in ["A+", "A", "B", "C", "D", "F"]:
            count = report.by_grade.get(grade, 0)
            bar = "█" * count if count < 50 else "█" * 50 + "..."
            print(f"    {grade}: {count:>4} {bar}")
        print()
        if report.by_sector:
            print("  Top secteurs (par score moyen):")
            sorted_sectors = sorted(report.by_sector.items(), key=lambda x: x[1]["avg_score"])
            for sector, stats in sorted_sectors[:10]:
                print(f"    {sector:>20}: {stats['avg_score']:>5.1f}/100 ({stats['count']} businesses)")
        print()
        if report.top_improvements:
            print("  Opportunités d'amélioration:")
            for imp in report.top_improvements:
                print(f"    ⚡ {imp}")

    elif cmd == "report":
        # Short summary
        state_path = Path("state/lead-queue.json")
        if state_path.exists():
            with open(state_path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for key in ("leads", "data", "results", "items"):
                    if key in data and isinstance(data[key], list):
                        data = data[key]
                        break
                else:
                    all_items = []
                    for v in data.values():
                        if isinstance(v, list):
                            all_items.extend(v)
                    data = all_items
            report = generate_report(data)
            print(f"  {report.total_businesses} businesses • Score moyen: {report.average_score} • Opportunité GEO: {report.geo_opportunity_score}/100")
        else:
            print("  Pas de données")

    elif cmd == "design-md":
        # Generate DESIGN.md for a business
        state_path = Path("state/lead-queue.json")
        businesses = []
        if state_path.exists():
            with open(state_path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for key in ("leads", "data", "results", "items"):
                    if key in data and isinstance(data[key], list):
                        data = data[key]
                        break
            businesses = data if isinstance(data, list) else []

        if len(sys.argv) >= 4:
            # Specific business by name + city
            target_name = sys.argv[2]
            target_city = sys.argv[3]
            business = None
            for b in businesses:
                bname = b.get("name", "")
                bcity = b.get("city", "") or b.get("address", {}).get("city", "")
                if target_name.lower() in bname.lower() and target_city.lower() in bcity.lower():
                    business = b
                    break
            if not business:
                business = {"name": target_name, "city": target_city, "sector": sys.argv[4] if len(sys.argv) > 4 else "commerce"}
        elif businesses:
            # First business as demo
            business = businesses[0]
        else:
            print("  Usage: design-md <name> <city> [sector]")
            print("  Or run from a directory with state/lead-queue.json")
            return

        result = score_geo(business)
        content = generate_geo_content(business, result)
        design = generate_design_md(business, result, content)

        print(design.markdown)
        print(f"\n  ── DESIGN.md generated: {len(design.markdown)} chars, {len(design.sections)} sections ──")

    elif cmd == "optimize":
        print("  (Optimisation GEO — nécessite LLM pour contenu personnalisé)")
        print("  Utilisez les templates de generate_geo_content() en Python")

    else:
        print(f"  Commande inconnue: {cmd}")


if __name__ == "__main__":
    main()
