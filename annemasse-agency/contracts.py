#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════╗
║  SOCIALPULSE — TOOL CONTRACTS (Skill #2)                       ║
║  Contrats Pydantic pour leads, scores, et pipeline             ║
╚══════════════════════════════════════════════════════════════════╝
"""

from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional
from datetime import datetime
import json
from pathlib import Path


# ─── Lead Contract ──────────────────────────────────────────────────

class LeadContract(BaseModel):
    """Contrat formel pour un lead SocialPulse."""
    
    # Identité OSM
    place_id: str = Field(default="", description="OSM place ID")
    osm_id: int = Field(default=0)
    osm_type: str = Field(default="")
    
    # Business info
    name: str = Field(default="", min_length=1, description="Nom de l'établissement")
    address: str = Field(default="")
    city: str = Field(default="")
    phone: str = Field(default="")
    website: str = Field(default="")
    website_status: str = Field(default="none")
    
    # Classification
    category: str = Field(default="")
    sector: str = Field(default="")
    sector_icon: str = Field(default="")
    channel: str = Field(default="email")
    
    # Géoloc
    lat: float = Field(default=0.0, ge=-90.0, le=90.0)
    lon: float = Field(default=0.0, ge=-180.0, le=180.0)
    
    # Extra
    opening_hours: str = Field(default="")
    cuisine: str = Field(default="")
    
    # Pipeline state
    source: str = Field(default="osm")
    status: str = Field(default="discovered")
    discovered_at: str = Field(default="")
    
    # Scoring
    score: int = Field(default=0, ge=0, le=100)
    score_breakdown: dict = Field(default_factory=dict)
    
    # Enrichment
    pappers_enriched: bool = Field(default=False)
    
    @field_validator("website_status")
    @classmethod
    def validate_website_status(cls, v: str) -> str:
        valid = {"none", "has_website", "facebook_only", "pagejaunes_only", "outdated", "ok", "error", "other"}
        if v and v not in valid:
            raise ValueError(f"Invalid website_status '{v}'. Must be one of {valid}")
        return v
    
    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        valid = {"discovered", "scored", "flagged", "diagnosed", "contacted", 
                 "replied", "meeting_booked", "deal_won", "deal_lost", "gele", "opted_out"}
        if v and v not in valid:
            raise ValueError(f"Invalid status '{v}'")
        return v
    
    @field_validator("channel")
    @classmethod
    def validate_channel(cls, v: str) -> str:
        valid = {"email", "sms", "instagram", "linkedin", "phone", ""}
        if v and v not in valid:
            raise ValueError(f"Invalid channel '{v}'")
        return v
    
    @model_validator(mode="after")
    def validate_geo(self):
        """Si lat/lon fournis, doivent être dans la zone Annemasse."""
        if self.lat != 0 and self.lon != 0:
            # Zone Annemasse: lat 46.13-46.23, lon 6.05-6.28
            if not (46.0 <= self.lat <= 46.5 and 5.8 <= self.lon <= 6.5):
                pass  # Warning only — don't reject, just unusual
        return self


# ─── Score Breakdown Contract ───────────────────────────────────────

class ScoreBreakdownContract(BaseModel):
    """Contrat pour le détail du score."""
    website: int = Field(default=0, ge=0, le=100)
    review_gap: str = Field(default="not_calculated")
    sector: str = Field(default="")
    location: str = Field(default="")
    total: int = Field(default=0, ge=0, le=100)


# ─── Outreach Result Contract ───────────────────────────────────────

class OutreachContract(BaseModel):
    """Contrat pour un contact/ Outreach."""
    lead_id: str = Field(default="")
    lead_name: str = Field(default="")
    channel: str = Field(default="")
    sent_at: str = Field(default="")
    
    # Content
    subject: str = Field(default="")
    message_preview: str = Field(default="", max_length=200)
    
    # Result
    status: str = Field(default="sent")  # sent, delivered, opened, replied, bounced
    opened_at: str = Field(default="")
    replied_at: str = Field(default="")
    reply_sentiment: str = Field(default="")  # positive, negative, neutral
    
    # Deal tracking
    meeting_booked: bool = Field(default=False)
    meeting_date: str = Field(default="")
    deal_status: str = Field(default="")  # proposed, accepted, rejected
    deal_amount_eur: float = Field(default=0.0, ge=0.0)


# ─── Pipeline Stats Contract ────────────────────────────────────────

class PipelineStatsContract(BaseModel):
    """Contrat pour les stats du pipeline."""
    total_discovered: int = Field(default=0, ge=0)
    total_qualified: int = Field(default=0, ge=0)
    total_messaged: int = Field(default=0, ge=0)
    total_replied: int = Field(default=0, ge=0)
    total_deals: int = Field(default=0, ge=0)
    total_revenue_eur: float = Field(default=0.0, ge=0.0)
    
    costs: dict = Field(default_factory=dict)
    daily: dict = Field(default_factory=dict)
    
    @model_validator(mode="after")
    def validate_funnel(self):
        """Le funnel doit être décroissant."""
        assert self.total_discovered >= self.total_qualified >= self.total_messaged >= self.total_replied >= self.total_deals
        return self


# ─── Validation Functions ───────────────────────────────────────────

def validate_lead_queue(path: str | Path) -> tuple[int, list[str]]:
    """Valider un fichier lead-queue.json."""
    path = Path(path)
    if not path.exists():
        return 0, [f"File not found: {path}"]
    
    with open(path) as f:
        leads = json.load(f)
    
    errors = []
    valid = 0
    
    for i, lead in enumerate(leads):
        try:
            LeadContract(**lead)
            valid += 1
        except Exception as e:
            name = lead.get("name", f"#{i}")
            errors.append(f"Lead '{name}': {e}")
            if len(errors) >= 20:
                errors.append(f"... and more errors (stopped at 20)")
                break
    
    return valid, errors


def validate_lead(lead: dict) -> LeadContract:
    return LeadContract(**lead)


# ─── CLI ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2 or sys.argv[1] == "check":
        print("\n╔══════════════════════════════════════════════════════════════╗")
        print("║  SOCIALPULSE CONTRACT CHECK                                ║")
        print("╚══════════════════════════════════════════════════════════════╝\n")
        
        state_dir = Path(__file__).parent / "state"
        
        # Lead queue
        leads_path = state_dir / "lead-queue.json"
        if leads_path.exists():
            valid, errors = validate_lead_queue(leads_path)
            status = "✅" if not errors else "❌"
            print(f"  {status} lead-queue.json: {valid} valid leads")
            for e in errors[:5]:
                print(f"     {e}")
        else:
            print("  ⚠️  lead-queue.json: not found")
        
        # Stats
        stats_path = state_dir / "stats.json"
        if stats_path.exists():
            with open(stats_path) as f:
                stats = json.load(f)
            try:
                PipelineStatsContract(**stats)
                print(f"  ✅ stats.json: valid")
            except Exception as e:
                print(f"  ❌ stats.json: {e}")
    
    elif sys.argv[1] == "schemas":
        out = Path(__file__).parent / "state" / "schemas"
        out.mkdir(parents=True, exist_ok=True)
        for name, model in [("lead", LeadContract), ("outreach", OutreachContract), ("stats", PipelineStatsContract)]:
            with open(out / f"{name}.schema.json", "w") as f:
                json.dump(model.model_json_schema(), f, indent=2)
        print(f"✅ Schemas exported")
