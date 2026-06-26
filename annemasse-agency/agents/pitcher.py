#!/usr/bin/env python3
"""
SocialPulse — Agent 5: PITCHER
Prépare les cold messages adaptés au canal (email/SMS/IG/LinkedIn).
"""
import json, datetime
from pathlib import Path
from shared import StateManager, WORMJournal, Mediateur, OUTPUT_DIR

# Notice RGPD conforme — prospection B2B.
# FIX FATAL #1: remplace la mention erronée "art. L.223-1" (qui est Bloctel/téléphone,
#   pas l'email). Base légale: intérêt légitime RGPD art. 6(1)(f) + CPCE art. L.34-5 (régime opt-out B2B).
RGPD_NOTICE = (
    "Notice RGPD / prospection B2B : SocialPulse traite vos données professionnelles "
    "issues de sources publiques B2B afin de vous proposer ses services, sur la base de "
    "son intérêt légitime (RGPD art. 6(1)(f)) et conformément au CPCE art. L.34-5. "
    "Vous pouvez vous opposer à tout moment en répondant STOP. "
    "Droits RGPD : accès, rectification, effacement, limitation, opposition et réclamation CNIL "
    "— contact : privacy@socialpulse.fr."
)

class PitcherAgent:
    def __init__(self, state: StateManager, journal: WORMJournal, mediateur: Mediateur):
        self.state = state; self.journal = journal; self.mediateur = mediateur

    def run(self, campaign: dict):
        queue = self.state.get_queue()
        to_pitch = [l for l in queue if l.get("status") == "filmed"]
        pitched = []
        skipped_sms = []
        skipped_ei = []
        for lead in to_pitch:
            ch = lead.get("channel", "email")
            # FIX FATAL #2 — Gate SMS: opt-in obligatoire (ePrivacy + CPCE L.34-5).
            # SMS cold désactivé par défaut. Autorisé seulement si lead.sms_consent truthy
            # (preuve de consentement horodatée). Sans preuve → skip + log WORM.
            if ch == "sms" and not lead.get("sms_consent"):
                lead.update({"status": "skipped_sms_no_consent", "pitch_ready": False})
                skipped_sms.append(lead)
                self.journal.log("pitcher.sms_skip", "sms",
                                  {"reason": "no_consent", "legal_basis": "ePrivacy opt-in manquant"},
                                  lead["name"])
                print(f"  ⛔ SMS bloqué (no consent): {lead['name']}")
                continue
            # FIX STRUCTUREL #3 — Gate EI: un entrepreneur individuel est une personne
            # physique → ses coordonnées sont des données personnelles RGPD. Email B2B
            # opt-out (CPCE L.34-5) NON autorisé sans consentement. → skip + log WORM.
            # Voir agents/legal_classifier.py + REPOSITIONING-BRIEF.md.
            from agents.legal_classifier import classify_lead, LegalClass
            legal = classify_lead(lead)
            if ch == "email" and legal.can_email_opt_in_only and not lead.get("email_consent"):
                lead.update({"status": "skipped_ei_no_consent", "pitch_ready": False,
                             "legal_class": legal.class_.value})
                skipped_ei.append(lead)
                self.journal.log("pitcher.ei_skip", "email",
                                  {"reason": "ei_no_consent",
                                   "legal_basis": "opt-in ePrivacy requis (personne physique)",
                                   "forme_juridique": legal.forme_juridique,
                                   "matched": legal.matched_pattern},
                                  lead["name"])
                print(f"  ⛔ Email bloqué (EI sans consent): {lead['name']} [{legal.class_.value}]")
                continue
            msg = self._message(lead, ch, campaign)
            lead.update({"pitch_channel": ch, "pitch_message": msg, "pitch_ready": True,
                         "status": "pitched", "legal_class": legal.class_.value,
                         "legal_basis": legal.legal_basis})
            pitched.append(lead)
            self.journal.log("pitcher.prepare", ch, {"length": len(msg),
                              "legal_class": legal.class_.value}, lead["name"])
            print(f"  📤 Pitch: {lead['name']} via {ch} [{legal.class_.value}]")
        self.state.save_queue(queue)
        self._save_report(pitched)
        print(f"\n  ✅ Pitcher: {len(pitched)} messages prêts, "
              f"{len(skipped_sms)} SMS bloqués, {len(skipped_ei)} EI bloqués (no consent)")
        return pitched

    def _message(self, lead, channel, campaign):
        name = lead.get("name",""); sector = lead.get("sector","")
        cold = lead.get("cold_message",""); addr = lead.get("address","")
        city = "Annemasse"
        for c in ["Gaillard","Ville-la-Grand","Saint-Julien"]:
            if c.lower() in addr.lower(): city = c; break
        if channel == "email":
            # FIX FATAL #1 — Mention RGPD conforme (CPCE L.34-5, PAS L.223-1).
            return f"""Objet: {name} — présence web à {city}

Bonjour,

{cold}

Si le sujet n'est pas pertinent, répondez STOP : nous vous retirerons immédiatement de nos relances.

Cordialement,
L'équipe SocialPulse

---
{RGPD_NOTICE}"""
        elif channel == "sms":
            # SMS autorisé uniquement si sms_consent (gate dans run()). Template court conforme.
            return f"SocialPulse: {name}, suite à votre accord, présence web à {city}. STOP=désinscription"
        elif channel == "instagram":
            return f"Salut ! 👋 J'ai vu {name} sur Google Maps — super notes ! 🌟 On aide les {sector.lower()} de {city} à avoir un site pro. On en discute ? (répondez STOP pour stop)"
        elif channel == "linkedin":
            return f"Bonjour,\n\nJ'ai remarqué {name} — excellente réputation {sector} à {city}.\n\nJe travaille avec des professionnels en Haute-Savoie pour créer des sites qui convertissent.\n\nUn échange de 10 min vous intéresserait ?\n\nCordialement,\nSocialPulse (répondez STOP pour ne plus être contacté)"
        return cold

    def _save_report(self, pitched):
        report = [{"name": l.get("name"), "sector": l.get("sector"), "channel": l.get("pitch_channel"),
                    "message": l.get("pitch_message"), "score": l.get("score")} for l in pitched]
        (OUTPUT_DIR / "pitch-report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
