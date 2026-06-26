#!/usr/bin/env python3
"""
SocialPulse — Agent 6: CHECKER
Évalue chaque message avant envoi: personnalisation, anti-IA, opt-out, longueur.
"""
from shared import StateManager, WORMJournal

AI_MARKERS = ["intelligence artificielle","algorithme","machine learning",
    "révolutionnaire","disruptif","innovant","par ailleurs","de plus","n'hésitez pas"]
# NOTE: "ia" retiré de la liste (préexistant) — faux positif systématique car il matche
# soc**ia**l, cord**ia**lement, imméd**ia**tement, manuel, etc. "intelligence artificielle" suffit.
BUZZWORDS = ["synergie","disruption","paradigme","holistique","agile","scalable","lever"]

class CheckerAgent:
    def __init__(self, state: StateManager, journal: WORMJournal):
        self.state = state; self.journal = journal

    def run(self, campaign: dict):
        queue = self.state.get_queue()
        to_check = [l for l in queue if l.get("status") == "pitched"]
        approved, flagged = [], []
        for lead in to_check:
            issues = self._check(lead.get("pitch_message",""), lead)
            if issues:
                lead.update({"checker_issues": issues, "status": "flagged"}); flagged.append(lead)
                print(f"  ⚠️ Flagged: {lead['name']} — {issues}")
            else:
                lead["status"] = "approved"; approved.append(lead)
                print(f"  ✅ Approved: {lead['name']}")
            self.journal.log("checker.eval", "local", {"passed": not issues, "issues": issues}, lead["name"])
        self.state.save_queue(queue)
        print(f"\n  ✅ Checker: {len(approved)} approved, {len(flagged)} flagged")
        return approved, flagged

    def _check(self, message, lead):
        issues = []; ml = message.lower()
        if lead.get("name","").lower() not in ml:
            issues.append("PERSONNALISATION: nom non mentionné")
        for m in AI_MARKERS:
            if m in ml: issues.append(f"AI_MARKER: '{m}'")
        for b in BUZZWORDS:
            if b in ml: issues.append(f"BUZZWORD: '{b}'")
        ch = lead.get("pitch_channel","email")
        if ch in ["email","sms"] and "stop" not in ml and "désinscription" not in ml:
            issues.append("COMPLIANCE: pas de opt-out")

        # FIX FATAL #1 — Mention 'art. L.223-1' INTERDITE.
        # C'est juridiquement faux: L.223-1 = Bloctel/démarchage téléphonique, PAS l'email.
        # La référence correcte pour l'email B2B est CPCE art. L.34-5.
        if "l. 223-1" in ml or "l223-1" in ml or "l.223-1" in ml or "l.223-1" in ml:
            issues.append("FATAL JURIDIQUE: mention 'L.223-1' interdite (c'est Bloctel/téléphone, pas l'email). Remplacer par CPCE L.34-5 + notice RGPD.")

        # FIX FATAL #1bis — Notice RGPD obligatoire dans l'email B2B (base légale + notice).
        if ch == "email":
            has_legal_basis = ("intérêt légitime" in ml) or ("6(1)(f)" in ml) or ("art. 6" in ml)
            has_notice = "rgpd" in ml
            if not has_legal_basis:
                issues.append("COMPLIANCE: email B2B sans base légale explicite (intérêt légitime RGPD art. 6(1)(f))")
            if not has_notice:
                issues.append("COMPLIANCE: email B2B sans notice RGPD")

        # FIX FATAL #2 — SMS bloqué sans preuve de consentement (ePrivacy opt-in + CPCE L.34-5).
        # Sécurité: même si le Pitcher a déjà skippé, si un message SMS arrive ici sans consent, on flag.
        if ch == "sms" and not lead.get("sms_consent"):
            issues.append("FATAL JURIDIQUE: SMS sans preuve de consentement (ePrivacy opt-in). À bloquer au niveau Pitcher (status skipped_sms_no_consent).")

        if ch == "sms" and len(message) > 160:
            issues.append(f"LONGUEUR: SMS > 160 ({len(message)})")
        return issues
