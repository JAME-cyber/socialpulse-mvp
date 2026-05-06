#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════╗
║  SOCIALPULSE — FEEDBACK LOOP (Skill #11)                       ║
║  Tracking du pipeline: lead → contact → reply → deal           ║
║                                                                  ║
║  Contrairement à DropAtom (campagnes ads), SocialPulse tracke:  ║
║  → Emails/envois par lead                                       ║
║  → Taux de réponse par secteur/ville/canal                      ║
║  → Taux de conversion reply → deal                              ║
║  → Revenue par deal                                              ║
╚══════════════════════════════════════════════════════════════════╝
"""

import json
import hashlib
import os
import sys
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional
from collections import Counter

BASE_DIR = Path(__file__).parent
STATE_DIR = BASE_DIR / "state"
OUTREACH_PATH = STATE_DIR / "outreach-log.json"
FEEDBACK_PATH = STATE_DIR / "feedback-weights.json"
JOURNAL_DIR = STATE_DIR / "journal"


# ─── Outreach Log ───────────────────────────────────────────────────

@dataclass
class OutreachEvent:
    """Un événement de contact avec un lead."""
    id: str = ""
    lead_place_id: str = ""
    lead_name: str = ""
    lead_sector: str = ""
    lead_city: str = ""
    lead_score: int = 0
    
    channel: str = ""          # email, sms, instagram, linkedin
    sent_at: str = ""
    
    # Content
    subject: str = ""
    
    # Response tracking
    opened: bool = False
    opened_at: str = ""
    replied: bool = False
    replied_at: str = ""
    reply_sentiment: str = ""  # positive, negative, neutral, opt_out
    
    # Deal
    meeting_booked: bool = False
    meeting_date: str = ""
    deal_won: bool = False
    deal_amount_eur: float = 0.0
    service_sold: str = ""     # landing_page, website, instagram_mgmt, video


# ─── Feedback Weights (pipeline learning) ───────────────────────────

@dataclass
class PipelineWeights:
    """Poids adaptatifs du scoring SocialPulse."""
    # Scoring weights
    website_weight: float = 0.30
    review_gap_weight: float = 0.25
    sector_weight: float = 0.25
    location_weight: float = 0.20
    
    # Sector adjustments (learned from replies)
    sector_reply_rates: dict = field(default_factory=dict)
    
    # City adjustments
    city_reply_rates: dict = field(default_factory=dict)
    
    # Channel effectiveness
    channel_reply_rates: dict = field(default_factory=dict)
    
    # Score range that converts best
    best_score_min: int = 70
    best_score_max: int = 95
    
    # Funnel metrics
    total_sent: int = 0
    total_opened: int = 0
    total_replied: int = 0
    total_deals: int = 0
    open_rate: float = 0.0
    reply_rate: float = 0.0
    deal_rate: float = 0.0
    avg_deal_eur: float = 0.0
    total_revenue_eur: float = 0.0
    
    # Best performing
    best_sector: str = ""
    best_city: str = ""
    best_channel: str = ""
    
    updated_at: str = ""


# ─── Load / Save ────────────────────────────────────────────────────

def load_outreach() -> list[dict]:
    if not OUTREACH_PATH.exists():
        return []
    with open(OUTREACH_PATH) as f:
        return json.load(f)

def save_outreach(events: list[dict]):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTREACH_PATH, "w") as f:
        json.dump(events, f, indent=2, ensure_ascii=False)

def load_feedback() -> PipelineWeights:
    if not FEEDBACK_PATH.exists():
        return PipelineWeights(updated_at=datetime.now(timezone.utc).isoformat())
    with open(FEEDBACK_PATH) as f:
        d = json.load(f)
    return PipelineWeights(**{k: v for k, v in d.items() 
                              if k in PipelineWeights.__dataclass_fields__})

def save_feedback(fw: PipelineWeights):
    FEEDBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
    fw.updated_at = datetime.now(timezone.utc).isoformat()
    with open(FEEDBACK_PATH, "w") as f:
        json.dump(asdict(fw), f, indent=2, ensure_ascii=False)


# ─── Core: Log Outreach ─────────────────────────────────────────────

def log_outreach(event: OutreachEvent) -> dict:
    """Enregistrer un envoi de message."""
    import time
    raw = f"{event.lead_place_id}:{event.channel}:{event.sent_at}:{time.monotonic_ns()}"
    event.id = hashlib.sha256(raw.encode()).hexdigest()[:12]
    
    events = load_outreach()
    events.append(asdict(event))
    save_outreach(events)
    
    # Recalculate feedback
    fw = recalculate_feedback(events)
    save_feedback(fw)
    
    write_journal("outreach_sent", {
        "lead": event.lead_name,
        "channel": event.channel,
        "sector": event.lead_sector,
    })
    
    return {"id": event.id, "total_sent": fw.total_sent}


def update_outreach(event_id: str, updates: dict) -> dict:
    """Mettre à jour un événement (opened, replied, deal)."""
    events = load_outreach()
    
    found = False
    target_name = ""
    for e in events:
        if e["id"] == event_id:
            e.update(updates)
            found = True
            target_name = e.get("lead_name", "?")
            break
    
    if not found:
        return {"error": f"Event {event_id} not found"}
    
    save_outreach(events)
    fw = recalculate_feedback(events)
    save_feedback(fw)
    
    action = "unknown"
    if updates.get("deal_won"):
        action = "deal_won"
        write_journal("deal_won", {
            "lead": target_name,
            "amount": updates.get("deal_amount_eur", 0),
            "service": updates.get("service_sold", ""),
        })
    elif updates.get("replied"):
        action = "reply_received"
        write_journal("reply", {
            "lead": target_name,
            "sentiment": updates.get("reply_sentiment", ""),
        })
    elif updates.get("opened"):
        action = "email_opened"
    
    return {"updated": True, "action": action, "stats": {
        "open_rate": fw.open_rate,
        "reply_rate": fw.reply_rate,
        "deal_rate": fw.deal_rate,
        "total_revenue": fw.total_revenue_eur,
    }}


# ─── Core: Recalculate Feedback ─────────────────────────────────────

def recalculate_feedback(events: list[dict]) -> PipelineWeights:
    """Recalculer les métriques du pipeline."""
    fw = PipelineWeights()
    
    if not events:
        return fw
    
    fw.total_sent = len(events)
    
    opened = [e for e in events if e.get("opened")]
    replied = [e for e in events if e.get("replied")]
    deals = [e for e in events if e.get("deal_won")]
    
    fw.total_opened = len(opened)
    fw.total_replied = len(replied)
    fw.total_deals = len(deals)
    
    fw.open_rate = round(len(opened) / max(len(events), 1) * 100, 1)
    fw.reply_rate = round(len(replied) / max(len(events), 1) * 100, 1)
    fw.deal_rate = round(len(deals) / max(len(events), 1) * 100, 1)
    
    # Revenue
    deal_amounts = [e.get("deal_amount_eur", 0) for e in deals if e.get("deal_amount_eur")]
    fw.total_revenue_eur = round(sum(deal_amounts), 2)
    if deal_amounts:
        fw.avg_deal_eur = round(sum(deal_amounts) / len(deal_amounts), 2)
    
    # ─── Sector reply rates ──────────────────────────────────────
    sector_sent = Counter(e.get("lead_sector", "?") for e in events)
    sector_replied = Counter(e.get("lead_sector", "?") for e in replied)
    for sector, count in sector_sent.items():
        if count >= 2:
            fw.sector_reply_rates[sector] = round(
                sector_replied.get(sector, 0) / count * 100, 1
            )
    
    # ─── City reply rates ────────────────────────────────────────
    city_sent = Counter(e.get("lead_city", "?") for e in events)
    city_replied = Counter(e.get("lead_city", "?") for e in replied)
    for city, count in city_sent.items():
        if count >= 2:
            fw.city_reply_rates[city] = round(
                city_replied.get(city, 0) / count * 100, 1
            )
    
    # ─── Channel reply rates ─────────────────────────────────────
    ch_sent = Counter(e.get("channel", "?") for e in events)
    ch_replied = Counter(e.get("channel", "?") for e in replied)
    for ch, count in ch_sent.items():
        if count >= 2:
            fw.channel_reply_rates[ch] = round(
                ch_replied.get(ch, 0) / count * 100, 1
            )
    
    # Best performers
    if fw.sector_reply_rates:
        fw.best_sector = max(fw.sector_reply_rates, key=fw.sector_reply_rates.get)
    if fw.city_reply_rates:
        fw.best_city = max(fw.city_reply_rates, key=fw.city_reply_rates.get)
    if fw.channel_reply_rates:
        fw.best_channel = max(fw.channel_reply_rates, key=fw.channel_reply_rates.get)
    
    # Score range that converts best
    deal_scores = [e.get("lead_score", 0) for e in deals]
    if len(deal_scores) >= 2:
        fw.best_score_min = min(deal_scores)
        fw.best_score_max = max(deal_scores)
    
    return fw


# ─── Adjustments for Scoring ────────────────────────────────────────

def get_scoring_adjustments() -> dict:
    """Retourne les ajustements pour le SCOUT/DIAGNOSER."""
    fw = load_feedback()
    
    return {
        "weights": {
            "website": fw.website_weight,
            "review_gap": fw.review_gap_weight,
            "sector": fw.sector_weight,
            "location": fw.location_weight,
        },
        "sector_bonuses": fw.sector_reply_rates,
        "city_bonuses": fw.city_reply_rates,
        "best_score_range": (fw.best_score_min, fw.best_score_max),
        "funnel": {
            "sent": fw.total_sent,
            "open_rate": fw.open_rate,
            "reply_rate": fw.reply_rate,
            "deal_rate": fw.deal_rate,
            "revenue": fw.total_revenue_eur,
        }
    }


# ─── WORM Journal ───────────────────────────────────────────────────

def write_journal(action: str, data: dict):
    JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
    
    existing = list(JOURNAL_DIR.glob("*.json"))
    prev_hash = ""
    if existing:
        existing.sort(key=lambda p: p.stat().st_mtime)
        with open(existing[-1]) as f:
            prev_hash = json.load(f).get("hash", "")
    
    now = datetime.now(timezone.utc)
    entry = {
        "timestamp": now.isoformat(),
        "agent": "FEEDBACK",
        "action": action,
        "prev_hash": prev_hash,
        **data,
    }
    
    entry_str = json.dumps(entry, sort_keys=True)
    entry["hash"] = hashlib.sha256(entry_str.encode()).hexdigest()
    
    filename = f"feedback-{now.strftime('%Y%m%d-%H%M%S')}.json"
    with open(JOURNAL_DIR / filename, "w") as f:
        json.dump(entry, f, indent=2, ensure_ascii=False)


# ─── CLI ────────────────────────────────────────────────────────────

def cmd_status():
    fw = load_feedback()
    events = load_outreach()
    
    print(f"\n╔══════════════════════════════════════════════════════════════╗")
    print(f"║  SOCIALPULSE FEEDBACK LOOP                                  ║")
    print(f"╚══════════════════════════════════════════════════════════════╝")
    print()
    
    if not events:
        print("  📭 Aucun outreach enregistré.")
        print("  → Utilisez: python3 feedback.py simulate 20")
        print("  → Ou: feedback.log_outreach(OutreachEvent(...))")
        return
    
    print(f"  📊 Pipeline:")
    print(f"     Envoyés: {fw.total_sent}")
    print(f"     Ouverts: {fw.total_opened} ({fw.open_rate}%)")
    print(f"     Réponses: {fw.total_replied} ({fw.reply_rate}%)")
    print(f"     Deals: {fw.total_deals} ({fw.deal_rate}%)")
    print(f"     💰 Revenue: €{fw.total_revenue_eur:.0f}")
    if fw.avg_deal_eur:
        print(f"     💶 Avg deal: €{fw.avg_deal_eur:.0f}")
    print()
    
    if fw.best_sector:
        print(f"  🏆 Best sector: {fw.best_sector}")
    if fw.best_city:
        print(f"  📍 Best city: {fw.best_city}")
    if fw.best_channel:
        print(f"  📨 Best channel: {fw.best_channel}")
    
    if fw.sector_reply_rates:
        print(f"\n  📂 Sector Reply Rates:")
        for sector, rate in sorted(fw.sector_reply_rates.items(), key=lambda x: -x[1]):
            emoji = "🟢" if rate > 15 else "🟡" if rate > 5 else "🔴"
            print(f"     {emoji} {sector}: {rate}%")
    
    if fw.channel_reply_rates:
        print(f"\n  📨 Channel Reply Rates:")
        for ch, rate in sorted(fw.channel_reply_rates.items(), key=lambda x: -x[1]):
            emoji = "🟢" if rate > 15 else "🟡" if rate > 5 else "🔴"
            print(f"     {emoji} {ch}: {rate}%")


def cmd_simulate(n_events: int):
    """Simuler N outreach events pour tester."""
    import random
    
    # Load real leads for realistic simulation
    leads_path = STATE_DIR / "lead-queue.json"
    if leads_path.exists():
        with open(leads_path) as f:
            leads = json.load(f)
    else:
        leads = [{"place_id": f"sim-{i}", "name": f"Lead {i}", "sector": "Restaurant", 
                  "city": "Annemasse", "score": 75} for i in range(100)]
    
    channels = ["email", "sms", "instagram", "linkedin"]
    services = ["landing_page", "website", "instagram_mgmt", "video"]
    
    print(f"\n🎲 Simulation de {n_events} outreach events...\n")
    
    for i in range(n_events):
        lead = random.choice(leads)
        channel = random.choice(channels)
        
        # Simulate realistic funnel
        opened = random.random() < 0.35
        replied = opened and random.random() < 0.25
        deal = replied and random.random() < 0.30
        
        # Sector influences reply rate
        sector = lead.get("sector", "Restaurant")
        if sector in ("Avocat", "Cabinet comptable", "Immobilier"):
            replied = opened and random.random() < 0.35
        elif sector in ("Restaurant", "Salon de coiffure"):
            replied = opened and random.random() < 0.15
        
        event = OutreachEvent(
            lead_place_id=lead.get("place_id", ""),
            lead_name=lead.get("name", "?"),
            lead_sector=sector,
            lead_city=lead.get("city", "Annemasse"),
            lead_score=lead.get("score", 50),
            channel=channel,
            sent_at=datetime.now(timezone.utc).isoformat(),
            opened=opened,
            replied=replied,
            reply_sentiment=random.choice(["positive", "neutral", "negative"]) if replied else "",
            deal_won=deal,
            deal_amount_eur=random.choice([350, 500, 800, 1200]) if deal else 0,
            service_sold=random.choice(services) if deal else "",
        )
        
        result = log_outreach(event)
        emoji = "💰" if deal else "📧" if replied else "👁️" if opened else "📤"
        print(f"  {i+1:>3}. {emoji} {lead.get('name','?')[:30]:<30} | {channel:<10} | {sector:<20} | {'DEAL' if deal else 'reply' if replied else 'open' if opened else 'sent'}")
    
    print()
    cmd_status()


def cmd_report():
    """Exporter le rapport."""
    fw = load_feedback()
    events = load_outreach()
    
    path = BASE_DIR / "output" / "feedback-report.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(path, "w") as f:
        f.write("# SocialPulse Feedback Report\n\n")
        f.write(f"**Generated:** {datetime.now(timezone.utc).isoformat()}\n\n")
        f.write(f"## Pipeline\n\n")
        f.write(f"| Metric | Value |\n|--------|-------|\n")
        f.write(f"| Sent | {fw.total_sent} |\n")
        f.write(f"| Open Rate | {fw.open_rate}% |\n")
        f.write(f"| Reply Rate | {fw.reply_rate}% |\n")
        f.write(f"| Deal Rate | {fw.deal_rate}% |\n")
        f.write(f"| Revenue | €{fw.total_revenue_eur:.0f} |\n")
        f.write(f"| Avg Deal | €{fw.avg_deal_eur:.0f} |\n\n")
        
        f.write(f"## Sector Performance\n\n")
        f.write(f"| Sector | Sent | Reply Rate |\n|--------|------|------------|\n")
        sector_sent = Counter(e.get("lead_sector", "?") for e in events)
        for sector, rate in sorted(fw.sector_reply_rates.items(), key=lambda x: -x[1]):
            f.write(f"| {sector} | {sector_sent.get(sector, 0)} | {rate}% |\n")
    
    print(f"✅ Report saved to {path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        cmd_status()
    elif sys.argv[1] == "status":
        cmd_status()
    elif sys.argv[1] == "simulate":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
        cmd_simulate(n)
    elif sys.argv[1] == "report":
        cmd_report()
    elif sys.argv[1] == "reset":
        for p in [OUTREACH_PATH, FEEDBACK_PATH]:
            if p.exists():
                os.remove(p)
        print("✅ Reset done")
    else:
        print("Commands: status | simulate N | report | reset")
