"""Tests unitaires pour le Feedback Loop SocialPulse."""

import pytest
import json
from pathlib import Path


class TestOutreachEvent:
    """Tests de l'enregistrement outreach."""

    def test_log_outreach(self, clean_feedback):
        fb = clean_feedback
        e = fb.OutreachEvent(
            lead_name="Test Restaurant",
            lead_sector="Restaurant",
            lead_city="Annemasse",
            lead_score=80,
            channel="email",
        )
        result = fb.log_outreach(e)
        assert result["total_sent"] == 1

    def test_multiple_events(self, clean_feedback):
        fb = clean_feedback
        for i in range(5):
            e = fb.OutreachEvent(
                lead_name=f"Lead {i}",
                lead_sector="Restaurant",
                channel="email",
            )
            fb.log_outreach(e)
        
        fw = fb.load_feedback()
        assert fw.total_sent == 5

    def test_update_replied(self, clean_feedback):
        fb = clean_feedback
        e = fb.OutreachEvent(lead_name="Test", channel="email")
        result = fb.log_outreach(e)
        event_id = result["id"]
        
        fb.update_outreach(event_id, {"replied": True, "reply_sentiment": "positive"})
        
        events = fb.load_outreach()
        assert events[0]["replied"] == True
        
        fw = fb.load_feedback()
        assert fw.total_replied == 1

    def test_update_deal(self, clean_feedback):
        fb = clean_feedback
        e = fb.OutreachEvent(lead_name="Test", channel="email")
        result = fb.log_outreach(e)
        
        fb.update_outreach(result["id"], {
            "replied": True,
            "deal_won": True,
            "deal_amount_eur": 500,
            "service_sold": "landing_page",
        })
        
        fw = fb.load_feedback()
        assert fw.total_deals == 1
        assert fw.total_revenue_eur == 500
        assert fw.avg_deal_eur == 500

    def test_reply_rates_by_sector(self, clean_feedback):
        fb = clean_feedback
        
        # 5 Restaurant: 2 replies
        for i in range(5):
            e = fb.OutreachEvent(lead_name=f"Resto {i}", lead_sector="Restaurant", channel="email")
            result = fb.log_outreach(e)
            if i < 2:
                fb.update_outreach(result["id"], {"replied": True})
        
        fw = fb.load_feedback()
        assert "Restaurant" in fw.sector_reply_rates
        assert fw.sector_reply_rates["Restaurant"] == 40.0  # 2/5 = 40%


class TestPipelineWeights:
    """Tests des poids adaptatifs."""

    def test_default_weights(self, clean_feedback):
        fb = clean_feedback
        fw = fb.load_feedback()
        assert fw.website_weight == 0.30
        assert fw.review_gap_weight == 0.25

    def test_scoring_adjustments(self, clean_feedback):
        fb = clean_feedback
        adj = fb.get_scoring_adjustments()
        assert "weights" in adj
        assert "funnel" in adj
        assert adj["weights"]["website"] == 0.30


class TestWORMJournal:
    """Tests du journal."""

    def test_journal_created(self, clean_feedback):
        fb = clean_feedback
        e = fb.OutreachEvent(lead_name="Test", channel="email")
        fb.log_outreach(e)
        
        entries = list(fb.JOURNAL_DIR.glob("*.json"))
        assert len(entries) >= 1

    def test_journal_chain(self, clean_feedback):
        fb = clean_feedback
        for i in range(3):
            e = fb.OutreachEvent(lead_name=f"Test {i}", channel="email")
            fb.log_outreach(e)
        
        entries = sorted(fb.JOURNAL_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime)
        prev_hash = ""
        for entry_path in entries:
            with open(entry_path) as f:
                entry = json.load(f)
            if prev_hash:
                assert entry.get("prev_hash") == prev_hash
            prev_hash = entry.get("hash", "")
