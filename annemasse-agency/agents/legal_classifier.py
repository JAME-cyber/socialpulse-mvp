#!/usr/bin/env python3
"""
SocialPulse — Legal Classifier (PM / EI / NUANCED)
==================================================
Classifie un lead en Personne Morale / Entrepreneur Individuel / Nuancé à partir
de sa `forme_juridique` (champ `nature_juridique` de l'API Sirene).

C'est le FIX STRUCTUREL #3 du brief REPOSITIONING-BRIEF.md : sans cette distinction,
tout le pipeline traite les artisans/EI comme du B2B alors que leurs coordonnées
sont des DONNÉES PERSONNELLES au sens RGPD (confiance 0.97 — contre-analyse).

Sortie: classe + base légale + canaux autorisés. Consommé par ENRICH, PITCHER, CHECKER.

Références juridiques:
  - CPCE art. L.34-5 (prospection B2B opt-out pour PM)
  - RGPD art. 6(1)(f) intérêt légitime, art. 13/14 (info), art. 21 (opposition)
  - ePrivacy 2002/58/CE art. 13 (opt-in pour personnes physiques)
  - CNIL délib. 2013-367 + fiches prospection B2B
  - Code civil art. 1842, Code commerce L.210-6, L.526-22

Usage:
    from agents.legal_classifier import classify_lead, LegalClass
    result = classify_lead({"forme_juridique": "SARL", "name": "Garage Dupont"})
    # → LegalClassification(class="PM", legal_basis="opt-out B2B CPCE L.34-5 + RGPD 6(1)(f)", ...)
    if result.can_email_opt_out:  # PM → email B2B autorisé
        ...
    if result.class_ == LegalClass.EI:  # → opt-in requis
        ...
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class LegalClass(str, Enum):
    """Classification juridique d'un lead."""
    PM = "PM"             # Personne morale → B2B opt-out (CPCE L.34-5)
    EI = "EI"             # Entrepreneur individuel / personne physique → opt-in ePrivacy
    NUANCED = "NUANCED"   # Société de personnes / civile / ambigu → LIA documenté requis
    UNKNOWN = "UNKNOWN"   # Sirene n'a pas trouvé → défaut prudent NUANCED


@dataclass(frozen=True)
class LegalClassification:
    """Résultat de la classification d'un lead."""
    class_: LegalClass
    forme_juridique: str
    matched_pattern: str = ""           # le pattern regex qui a matché (audit)
    rationale: str = ""
    legal_basis: str = ""               # base légale RGPD pour le traitement prospection
    # Canaux autorisés (décision pré-pitcher):
    can_email_opt_out: bool = False     # email B2B opt-out autorisé (PM + NUANCED avec LIA)
    can_email_opt_in_only: bool = False # email uniquement si consentement prouvé (EI)
    can_sms: bool = False               # SMS jamais sans consentement (quel que soit le statut)
    needs_lia: bool = False             # LIA documenté obligatoire avant envoi
    sirene_source: bool = False         # classification basée sur Sirene (fiable) vs heuristique


# ─────────────────────────────────────────────────────────────────────────────
# Tables de classification
# Source: table générée par GPT-5.5 (OpenRouter) + codes INSEE catégorie juridique
# ─────────────────────────────────────────────────────────────────────────────

# Codes INSEE catégorie juridique (champ `categorie_juridique` Sirene) → classe
# Référence: nomenclature INSEE 2026. Priorité au code (plus fiable que le libellé).
_CODE_TO_CLASS: dict[str, LegalClass] = {
    # ── Personne physique (EI) ──
    "1000": LegalClass.EI,  # Entrepreneur individuel
    # ── Sociétés de capitaux = PM ──
    "5498": LegalClass.PM,  # SARL unipersonnelle (EURL)
    "5499": LegalClass.PM,  # SARL (hors unipersonnelle)
    "5710": LegalClass.PM,  # SAS
    "5720": LegalClass.PM,  # SASU (SAS unipersonnelle)
    "5510": LegalClass.PM,  # SA à conseil d'administration
    "5599": LegalClass.PM,  # SA (autre)
    "5610": LegalClass.PM,  # SA à directoire
    "5699": LegalClass.PM,  # SA à directoire (autre)
    "5505": LegalClass.PM,  # SA à participation ouvrière
    "5605": LegalClass.PM,  # SA à participation ouvrière à directoire
    "5800": LegalClass.PM,  # Société européenne (SE)
    "3120": LegalClass.PM,  # Société étrangère immatriculée au RCS
    # ── Sociétés d'exercice libéral = PM ──
    # SELARL, SELAS, SELAFA, SELCA, SELURL → PM
    # ── Coopératives / GIE / associations = PM ──
    "6210": LegalClass.PM,  # GEIE
    "6220": LegalClass.PM,  # GIE
    "6317": LegalClass.PM,  # Société coopérative agricole
    "8220": LegalClass.PM,  # Association déclarée (B2B si pro)
    "8450": LegalClass.PM,  # Ordre professionnel
    "9220": LegalClass.PM,  # Association déclarée
    "9300": LegalClass.PM,  # Fondation
    # ── Personnes morales de droit public = PM ──
    "7210": LegalClass.PM,  # Commune
    "7220": LegalClass.PM,  # Département
    "7230": LegalClass.PM,  # Région
    "7381": LegalClass.PM,  # Organisme consulaire (CCI, CMA)
    "7410": LegalClass.PM,  # EPIC
    # ── Sociétés de personnes / civiles = NUANCED (PM mais données associés perso) ──
    "5202": LegalClass.NUANCED,  # SNC
    "5306": LegalClass.NUANCED,  # SCS (commandite simple)
    "5308": LegalClass.NUANCED,  # SCA (commandite par actions)
    "6540": LegalClass.NUANCED,  # SCI
    "6541": LegalClass.NUANCED,  # SCI construction-vente
    "6585": LegalClass.NUANCED,  # SCP (société civile professionnelle)
    "6589": LegalClass.NUANCED,  # SCM (société civile de moyens)
    "6599": LegalClass.NUANCED,  # Autre société civile
    "6533": LegalClass.NUANCED,  # GAEC
    "6536": LegalClass.NUANCED,  # EARL
    "9110": LegalClass.NUANCED,  # Syndicat de copropriété
    "9210": LegalClass.NUANCED,  # Association non déclarée
}


def _compile(patterns: list[str]) -> list[tuple[re.Pattern, LegalClass, str, str]]:
    """Compile une liste de (regex, classe, rationale, base_légale)."""
    out = []
    bases = {
        LegalClass.PM: "opt-out B2B CPCE L.34-5 + RGPD 6(1)(f)",
        LegalClass.EI: "opt-in ePrivacy requis (données personnelles personne physique)",
        LegalClass.NUANCED: "LIA documenté obligatoire + info art.13/14 + minimisation",
    }
    rationales = {
        "sas": "La SAS/SASU est une société commerciale dotée de la personnalité morale, y compris à associé unique.",
        "sa": "La SA et la Société Européenne sont des personnes morales commerciales.",
        "sarl": "La SARL/EURL est une société dotée de la personnalité morale, même avec un associé unique.",
        "sel": "Les sociétés d'exercice libéral (SELARL/SELAS) sont des personnes morales constituées pour l'exercice d'une profession réglementée.",
        "snc": "SNC: personne morale MAIS associés indéfiniment responsables — traiter l'entité comme PM mais encadrer les données nominatives des associés.",
        "commandite": "Société en commandite: personne morale, mais données des commandités très identifiantes.",
        "civile": "Société civile (SCI/SCP/SCM): personne morale mais proche des associés personnes physiques.",
        "agricole": "Structure agricole (GAEC/EARL): personne morale mais exploitants personnes physiques.",
        "gie": "GIE/GEIE immatriculé: personne morale propre.",
        "association": "Association/fondation dotée de personnalité juridique: PM si prospection pro pertinente.",
        "cooperative": "Société coopérative: personne morale.",
        "public": "Personne morale de droit public / organisme consulaire: PM.",
        "holding": "Holding / société de capitaux: personne morale.",
        "ei": "Entrepreneur individuel: exerce en nom propre → personne physique → données personnelles RGPD.",
        "micro": "Micro/auto-entrepreneur: entrepreneur individuel sous régime simplifié, sans personnalité morale distincte.",
        "independant": "Activité exercée en nom propre par une personne physique (artiste-auteur, agent commercial, VDI, LMP...).",
        "liberal_individual": "Profession libérale: exercice en nom propre possible → EI sauf si en société (à vérifier).",
    }
    for p, cls, key in patterns:
        out.append((re.compile(p, re.IGNORECASE), cls, rationales.get(key, ""), bases[cls]))
    return out


# Patterns ordonnés par priorité (PM stricts en premier, puis EI, puis nuancés)
# Chaque pattern est testé en IGNORECASE sur la forme_juridique normalisée.
_PATTERNS = _compile([
    # ── PM strict (sociétés de capitaux) ──
    (r"\b(sas|s\.a\.s\.?|sasu|s\.a\.s\.u\.?|soci[eé]t[eé] par actions simplifi[eé]e(?:\s+unipersonnelle)?)\b", LegalClass.PM, "sas"),
    (r"\b(sarl|s\.a\.r\.l\.?|eurl|e\.u\.r\.l\.?|soci[eé]t[eé] (?:à|a) responsabilit[eé] limit[eé]e(?:\s+unipersonnelle)?)\b", LegalClass.PM, "sarl"),
    (r"\b(sa\b|s\.a\.?|soci[eé]t[eé] anonyme|soci[eé]t[eé] europ[eé]enne|\bse\b)\b", LegalClass.PM, "sa"),
    (r"\b(selarl|selas|selafa|selca|selurl|soci[eé]t[eé] d'exercice lib[eé]ral)\b", LegalClass.PM, "sel"),
    (r"\b(holding|soci[eé]t[eé] de capitaux|soci[eé]t[eé] d'[eé]conomie mixte)\b", LegalClass.PM, "holding"),
    (r"\b(gie|g\.i\.e\.?|geie|groupement (?:europ[eé]en\s+)?d'int[eé]r[eê]t [eé]conomique)\b", LegalClass.PM, "gie"),
    (r"\b(coop[eé]rative|scop|scic|sica|soci[eé]t[eé] coop[eé]rative)\b", LegalClass.PM, "cooperative"),
    (r"\b(association|fondation|syndicat|ordre professionnel|cci|cma|chambre de)\b", LegalClass.PM, "association"),
    (r"\b([eé]tablissement public|epic|epa|collectivit[eé]|commune|d[eé]partement|r[eé]gion|administration)\b", LegalClass.PM, "public"),
    # ── EI strict (personne physique) ──
    (r"\b(entrepreneur individuel|entreprise individuelle|\bei\b|e\.i\.?|exploitation en nom propre|en nom propre|commer[cç]ant individuel|artisan individuel|travailleur ind[eé]pendant|ind[eé]pendant)\b", LegalClass.EI, "ei"),
    (r"\b(micro[-\s]?entrepreneur|auto[-\s]?entrepreneur|r[eé]gime micro|micro[-\s]?entreprise)\b", LegalClass.EI, "micro"),
    (r"\b(artiste[-\s]?auteur|agent commercial individuel|vdi|vendeur (?:à|a) domicile|lmnp|lmp)\b", LegalClass.EI, "independant"),
    # ── NUANCED (personne morale mais données associés perso) ──
    (r"\b(snc|s\.n\.c\.?|soci[eé]t[eé] en nom collectif)\b", LegalClass.NUANCED, "snc"),
    (r"\b(scs|sca|soci[eé]t[eé] en commandite)\b", LegalClass.NUANCED, "commandite"),
    (r"\b(sci|s\.c\.i\.?|scp|scm|scea|soci[eé]t[eé] civile)\b", LegalClass.NUANCED, "civile"),
    (r"\b(gaec|earl|groupement agricole|exploitation agricole)\b", LegalClass.NUANCED, "agricole"),
    (r"\b(avocat|m[eé]decin|chirurgien|dentiste|infirmier|kin[eé]sith[eé]rapeute|architecte|expert[-\s]?comptable|notaire|huissier|v[eé]t[eé]rinaire|ost[eé]opathe|sage[-\s]?femme)\b", LegalClass.NUANCED, "liberal_individual"),
])


def _normalize(s: str) -> str:
    """Normalise pour le matching (lowercase, espaces)."""
    return (s or "").lower().strip()


def classify_lead(lead: dict) -> LegalClassification:
    """Classifie un lead en PM / EI / NUANCED.

    Priorité:
      1. Code INSEE `categorie_juridique` (le plus fiable, vient de Sirene)
      2. Libellé `forme_juridique` / `nature_juridique` (regex)
      3. Défaut prudent: NUANCED (ne pas présumer PM)

    Args:
        lead: dict avec idéalement `forme_juridique`, `nature_juridique`,
              `categorie_juridique` (peuplés par enrich_pappers/Sirene).

    Returns:
        LegalClassification avec classe + base légale + canaux autorisés.
    """
    forme = _normalize(lead.get("forme_juridique") or lead.get("nature_juridique") or "")
    code = str(lead.get("categorie_juridique") or lead.get("code_nature_juridique") or "").strip()
    sirene_sourced = bool(code or forme)

    # 1. Code INSEE en priorité (fiable)
    if code and code in _CODE_TO_CLASS:
        cls = _CODE_TO_CLASS[code]
        return _build(cls, forme or f"code:{code}", f"code INSEE {code}", sirene_sourced)

    # 2. Regex sur le libellé
    for pattern, cls, rationale, basis in _PATTERNS:
        m = pattern.search(forme)
        if m:
            return _build(cls, forme, f"{pattern.pattern} → «{m.group(0)}»", sirene_sourced, rationale, basis)

    # 3. Défaut prudent: NUANCED (le brief v2 dit "ne pas présumer PM")
    return _build(LegalClass.UNKNOWN, forme or "(vide)", "défaut prudent — Sirene sans match", sirene_sourced)


def _build(cls: LegalClass, forme: str, matched: str, sirene: bool,
           rationale: str = "", basis: str = "") -> LegalClassification:
    """Construit le LegalClassification avec les règles de canaux par défaut."""
    if not rationale:
        rationale = {
            LegalClass.PM: "Personne morale → B2B. Coordonnées professionnelles non RGPD-personnelles en principe.",
            LegalClass.EI: "Entrepreneur individuel = personne physique. Coordonnées = données personnelles RGPD.",
            LegalClass.NUANCED: "Personne morale mais associés/dirigeants personnes physiques. Données nominatives = perso.",
            LegalClass.UNKNOWN: "Sirene n'a pas permis de classifier. Présumer prudent (NUANCED).",
        }[cls]
    if not basis:
        basis = {
            LegalClass.PM: "opt-out B2B CPCE L.34-5 + RGPD 6(1)(f)",
            LegalClass.EI: "opt-in ePrivacy requis (données personnelles personne physique)",
            LegalClass.NUANCED: "LIA documenté obligatoire + info art.13/14 + minimisation",
            LegalClass.UNKNOWN: "LIA documenté obligatoire (présumer données perso par défaut)",
        }[cls]

    return LegalClassification(
        class_=cls,
        forme_juridique=forme,
        matched_pattern=matched,
        rationale=rationale,
        legal_basis=basis,
        # Règles de canaux (la décision finale SMS reste gated par consentement dans PITCHER)
        can_email_opt_out=(cls == LegalClass.PM),
        can_email_opt_in_only=(cls in (LegalClass.EI, LegalClass.UNKNOWN)),
        can_sms=False,  # SMS toujours gated par sms_consent dans PITCHER, jamais auto-autorisé
        needs_lia=(cls in (LegalClass.NUANCED, LegalClass.UNKNOWN)),
        sirene_source=sirene,
    )


def enrich_lead_with_classification(lead: dict) -> LegalClassification:
    """Classifie ET mute le lead in-place avec les champs de classification.

    Ajoute au lead:
      - legal_class: "PM" | "EI" | "NUANCED" | "UNKNOWN"
      - legal_basis: base légale RGPD pour prospection
      - legal_needs_lia: bool
      - legal_matched: motif matched (audit)
      - legal_sirene_sourced: bool

    Returns le LegalClassification (pour décision immédiate).
    """
    result = classify_lead(lead)
    lead["legal_class"] = result.class_.value
    lead["legal_basis"] = result.legal_basis
    lead["legal_needs_lia"] = result.needs_lia
    lead["legal_matched"] = result.matched_pattern
    lead["legal_sirene_sourced"] = result.sirene_source
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Self-test
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    tests = [
        ("SARL", {}, "PM"),
        ("Société à responsabilité limitée", {}, "PM"),
        ("EURL", {}, "PM"),
        ("SAS", {}, "PM"),
        ("SASU", {}, "PM"),
        ("Société par actions simplifiée unipersonnelle", {}, "PM"),
        ("SA à conseil d'administration", {}, "PM"),
        ("SELARL", {}, "PM"),
        ("Entrepreneur individuel", {}, "EI"),
        ("Auto-entrepreneur", {}, "EI"),
        ("micro-entrepreneur", {}, "EI"),
        ("Société en nom collectif", {}, "NUANCED"),
        ("Société civile immobilière", {}, "NUANCED"),
        ("GAEC", {}, "NUANCED"),
        ("", {}, "UNKNOWN"),  # vide
        ("Truc bizarre", {}, "UNKNOWN"),  # non matché
        # Via code INSEE (prioritaire)
        ("n'importe", {"categorie_juridique": "1000"}, "EI"),    # code 1000 = EI
        ("n'importe", {"categorie_juridique": "5499"}, "PM"),    # code 5499 = SARL
        ("n'importe", {"categorie_juridique": "5710"}, "PM"),    # code 5710 = SAS
        ("n'importe", {"categorie_juridique": "6540"}, "NUANCED"),  # code 6540 = SCI
    ]
    passed = 0
    for forme, extra, expected in tests:
        lead = {"forme_juridique": forme, **extra}
        r = classify_lead(lead)
        ok = r.class_.value == expected
        passed += ok
        flag = "✅" if ok else "❌"
        src = f" (code {extra.get('categorie_juridique')})" if extra else ""
        print(f"  {flag} «{forme[:40]}»{src} → {r.class_.value:8} (attendu {expected})")
    print(f"\n{passed}/{len(tests)} tests PASS")
