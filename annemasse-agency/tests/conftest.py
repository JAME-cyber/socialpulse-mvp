import pytest
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from contracts import LeadContract, PipelineStatsContract, validate_lead_queue
from feedback import OutreachEvent, PipelineWeights


# ─── Golden Leads (scores validés empiriquement) ────────────────────
# 
# Scoring: website(30%) + review_gap(25%) + sector(25%) + location(20%)
# website_status scores: none=100, facebook_only=80, pagejaunes_only=70, outdated=60, has_website=20

GOLDEN_LEADS = [
    {
        "name": "Restaurant No Website Annemasse",
        "website_status": "none",      # 100 × 0.30 = 30
        "sector": "Restaurant",         # 100 × 0.25 = 25
        "city": "Annemasse",            # 100 × 0.20 = 20
        "rating": 4.5, "reviews": 10,  # high_rating_low_reviews = 100 × 0.25 = 25
        "expected_score": 100,          # 30+25+25+20 = 100
    },
    {
        "name": "Restaurant Has Website Gaillard",
        "website_status": "has_website",  # 20 × 0.30 = 6
        "sector": "Restaurant",           # 100 × 0.25 = 25
        "city": "Gaillard",               # 90 × 0.20 = 18
        "rating": 4.5, "reviews": 10,     # 100 × 0.25 = 25
        "expected_score": 74,             # 6+25+25+18 = 74
    },
    {
        "name": "Coiffeur FB Only Annemasse",
        "website_status": "facebook_only",  # 80 × 0.30 = 24
        "sector": "Salon de coiffure",       # 100 × 0.25 = 25
        "city": "Annemasse",                 # 100 × 0.20 = 20
        "rating": 4.0, "reviews": 15,       # 100 × 0.25 = 25
        "expected_score": 94,                # 24+25+25+20 = 94
    },
    {
        "name": "Lawyer No Website SJG",
        "website_status": "none",        # 100 × 0.30 = 30
        "sector": "Avocat",              # 90 × 0.25 = 22.5
        "city": "Saint-Julien-en-Genevois",  # 90 × 0.20 = 18
        "rating": 3.5, "reviews": 5,    # 70 × 0.25 = 17.5
        "expected_score": 88,            # 30+22.5+17.5+18 = 88
    },
    {
        "name": "Garage Has Website Gaillard",
        "website_status": "has_website",  # 20 × 0.30 = 6
        "sector": "Garage auto",          # 80 × 0.25 = 20
        "city": "Gaillard",               # 90 × 0.20 = 18
        "rating": 3.0, "reviews": 50,    # 30 × 0.25 = 7.5
        "expected_score": 51,             # 6+20+7.5+18 = 51.5 → ~51
    },
]


@pytest.fixture
def golden_leads():
    return GOLDEN_LEADS


@pytest.fixture
def clean_feedback(tmp_path, monkeypatch):
    import feedback as fb
    monkeypatch.setattr(fb, "STATE_DIR", tmp_path)
    monkeypatch.setattr(fb, "OUTREACH_PATH", tmp_path / "outreach-log.json")
    monkeypatch.setattr(fb, "FEEDBACK_PATH", tmp_path / "feedback-weights.json")
    monkeypatch.setattr(fb, "JOURNAL_DIR", tmp_path / "journal")
    return fb
