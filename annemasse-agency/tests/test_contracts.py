"""Tests unitaires pour les Tool Contracts SocialPulse."""

import pytest
from contracts import (
    LeadContract, PipelineStatsContract, 
    validate_lead_queue, validate_lead,
)


class TestLeadContract:
    """Tests du contrat Lead."""

    def test_valid_lead(self):
        l = LeadContract(name="Taj Mahal", city="Annemasse", category="restaurant")
        assert l.name == "Taj Mahal"

    def test_rejects_empty_name(self):
        with pytest.raises(Exception):
            LeadContract(name="")

    def test_rejects_invalid_website_status(self):
        with pytest.raises(Exception):
            LeadContract(name="Test", website_status="dark_web")

    def test_accepts_valid_website_statuses(self):
        for ws in ["none", "has_website", "facebook_only", "pagejaunes_only", "outdated"]:
            l = LeadContract(name="Test", website_status=ws)
            assert l.website_status == ws

    def test_rejects_invalid_status(self):
        with pytest.raises(Exception):
            LeadContract(name="Test", status="hacked")

    def test_accepts_valid_statuses(self):
        for st in ["discovered", "scored", "flagged", "diagnosed", "contacted", "replied", "deal_won", "gele", "opted_out"]:
            l = LeadContract(name="Test", status=st)
            assert l.status == st

    def test_score_bounded(self):
        with pytest.raises(Exception):
            LeadContract(name="Test", score=-1)
        with pytest.raises(Exception):
            LeadContract(name="Test", score=101)

    def test_lat_lon_ranges(self):
        with pytest.raises(Exception):
            LeadContract(name="Test", lat=91.0)
        with pytest.raises(Exception):
            LeadContract(name="Test", lon=-181.0)

    def test_from_real_data(self):
        """Création depuis un vrai lead JSON."""
        d = {
            "place_id": "osm-281692631",
            "osm_id": 281692631,
            "osm_type": "amenity=restaurant",
            "name": "Taj Mahal",
            "address": "Grande Rue, Saint-Julien-en-Genevois",
            "city": "Saint-Julien-en-Genevois",
            "phone": "",
            "website": "",
            "website_status": "none",
            "category": "restaurant",
            "sector": "Restaurant",
            "sector_icon": "🍽️",
            "channel": "instagram",
            "lat": 46.1414971,
            "lon": 6.0794822,
            "opening_hours": "Mo-Su 12:00-14:00,19:00-22:00",
            "cuisine": "indian",
            "discovered_at": "2026-05-06T10:58:52.280626",
            "source": "osm",
            "status": "scored",
            "score": 80,
            "score_breakdown": {"website": 30, "review_gap": "calculated", "sector": "Restaurant", "location": "Grande Rue, Saint-Julien-en-Genevois", "total": 80},
            "pappers_enriched": False,
        }
        lead = LeadContract(**d)
        assert lead.name == "Taj Mahal"
        assert lead.score == 80

    def test_channel_validation(self):
        with pytest.raises(Exception):
            LeadContract(name="Test", channel="telegram")
        
        for ch in ["email", "sms", "instagram", "linkedin"]:
            l = LeadContract(name="Test", channel=ch)
            assert l.channel == ch


class TestPipelineStatsContract:
    """Tests du contrat PipelineStats."""

    def test_valid_stats(self):
        s = PipelineStatsContract(total_discovered=2382, total_qualified=100, total_messaged=50)
        assert s.total_discovered == 2382

    def test_funnel_must_be_descending(self):
        with pytest.raises(Exception):
            PipelineStatsContract(
                total_discovered=100,
                total_messaged=150,  # Can't message more than discovered!
            )

    def test_zero_stats(self):
        s = PipelineStatsContract()
        assert s.total_discovered == 0


class TestFileValidation:
    """Tests de validation des fichiers state."""

    def test_lead_queue_valid(self):
        state = Path(__file__).parent.parent / "state"
        path = state / "lead-queue.json"
        if not path.exists():
            pytest.skip("No lead-queue.json")
        
        valid, errors = validate_lead_queue(path)
        assert valid > 0
        assert len(errors) == 0, f"Errors: {errors[:3]}"


from pathlib import Path
