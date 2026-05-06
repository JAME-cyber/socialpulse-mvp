"""
Tests for GEO Agent — SocialPulse.
Skill #6 (Evals) + Skill #12 (GEO optimization).
"""

import pytest
from geo_agent import (
    GeoAuditContract,
    GeoOptimizedContent,
    GeoReportContract,
    GeoScoreResult,
    _grade,
    generate_geo_content,
    generate_report,
    score_authority,
    score_definition,
    score_freshness,
    score_geo,
    score_local,
    score_schema,
    score_structure,
)


# ── Fixtures ──────────────────────────────────────────────────

@pytest.fixture
def perfect_business():
    """Un business avec tous les signaux GEO possibles."""
    return {
        "name": "Restaurant Le Lac",
        "city": "Annemasse",
        "sector": "restaurant",
        "website": "https://www.restaurant-le-lac.fr",
        "address": "15 Rue de la Gare",
        "street": "15 Rue de la Gare",
        "postcode": "74100",
        "phone": "+33 4 50 66 12 34",
        "email": "contact@restaurant-le-lac.fr",
        "lat": 46.1934,
        "lon": 6.2369,
        "opening_hours": "Mo-Sa 11:30-14:00,18:30-22:00",
        "description": "Restaurant traditionnel français avec terrasse et vue sur le lac.",
        "tags": "restaurant, cuisine française, terrasse, annemasse",
        "amenity": "restaurant",
        "discovered_at": "2026-05-01T00:00:00Z",
    }


@pytest.fixture
def minimal_business():
    """Un business avec le strict minimum."""
    return {
        "name": "Coiffeur",
        "city": "Gaillard",
        "sector": "coiffeur",
    }


@pytest.fixture
def no_website_business():
    """Un business sans site web."""
    return {
        "name": "Boulangerie Dupont",
        "city": "Ville-la-Grand",
        "sector": "boulangerie",
        "phone": "+33 4 50 00 00 00",
        "lat": 46.195,
        "lon": 6.245,
        "address": "3 Place de la Mairie",
        "postcode": "74100",
    }


@pytest.fixture
def sample_businesses():
    """Un ensemble de businesses pour le rapport."""
    return [
        {"name": "A", "city": "Annemasse", "sector": "restaurant", "website": "https://a.fr",
         "phone": "+33 4 50 00 00 01", "lat": 46.19, "lon": 6.23, "postcode": "74100"},
        {"name": "B", "city": "Gaillard", "sector": "coiffeur"},
        {"name": "C", "city": "Annemasse", "sector": "restaurant", "website": "https://c.fr",
         "address": "1 Rue Test", "lat": 46.19, "lon": 6.24},
        {"name": "D", "city": "Saint-Julien-en-Genevois", "sector": "garage", "phone": "+33 4 50 00 00 04"},
        {"name": "E", "city": "Ville-la-Grand", "sector": "fleuriste",
         "website": "https://e.fr", "lat": 46.20, "lon": 6.25, "opening_hours": "Mo-Sa 09:00-19:00"},
    ]


# ── Contract Tests (Skill #2) ─────────────────────────────────

class TestGeoAuditContract:
    def test_valid_audit(self):
        c = GeoAuditContract(business_name="Test", city="Annemasse", sector="restaurant")
        assert c.city == "Annemasse"
        assert c.sector == "restaurant"

    def test_city_normalized(self):
        c = GeoAuditContract(business_name="T", city="  annemasse  ", sector="test")
        assert c.city == "Annemasse"

    def test_sector_normalized(self):
        c = GeoAuditContract(business_name="T", city="Annemasse", sector="  Restaurant  ")
        assert c.sector == "restaurant"

    def test_empty_name_rejected(self):
        with pytest.raises(Exception):
            GeoAuditContract(business_name="", city="Annemasse", sector="test")

    def test_optional_website(self):
        c = GeoAuditContract(business_name="T", city="Annemasse", sector="test", website="https://example.com")
        assert c.website == "https://example.com"


class TestGeoScoreResult:
    def test_score_bounds(self):
        r = GeoScoreResult(business_name="T", city="A", sector="s",
                           overall_score=50, definition_score=50, authority_score=50,
                           structure_score=50, schema_score=50, local_score=50,
                           freshness_score=50)
        assert r.overall_score == 50

    def test_score_too_high_rejected(self):
        with pytest.raises(Exception):
            GeoScoreResult(business_name="T", city="A", sector="s",
                           overall_score=150, definition_score=50, authority_score=50,
                           structure_score=50, schema_score=50, local_score=50,
                           freshness_score=50)

    def test_score_negative_rejected(self):
        with pytest.raises(Exception):
            GeoScoreResult(business_name="T", city="A", sector="s",
                           overall_score=-1, definition_score=50, authority_score=50,
                           structure_score=50, schema_score=50, local_score=50,
                           freshness_score=50)


# ── Grade Tests ────────────────────────────────────────────────

class TestGrade:
    @pytest.mark.parametrize("score,grade", [
        (95, "A+"), (85, "A"), (75, "B"), (65, "C"), (45, "D"), (20, "F"),
    ])
    def test_grade_boundaries(self, score, grade):
        assert _grade(score) == grade

    def test_grade_90_is_A_plus(self):
        assert _grade(90) == "A+"

    def test_grade_89_is_A(self):
        assert _grade(89) == "A"


# ── Scoring Tests ─────────────────────────────────────────────

class TestScoreDefinition:
    def test_perfect_definition(self, perfect_business):
        score, checks = score_definition(perfect_business)
        assert score >= 70
        assert len(checks) > 0

    def test_minimal_definition(self, minimal_business):
        score, checks = score_definition(minimal_business)
        assert score < 50  # No website, no phone, no address

    def test_has_website_boosts(self, perfect_business):
        score_with, _ = score_definition(perfect_business)
        perfect_business["website"] = ""
        score_without, _ = score_definition(perfect_business)
        assert score_with > score_without


class TestScoreAuthority:
    def test_custom_domain_bonus(self, perfect_business):
        score, checks = score_authority(perfect_business)
        custom = [c for c in checks if c["item"] == "custom_domain"]
        assert len(custom) == 1
        assert custom[0]["pass"] is True

    def test_generic_domain_penalty(self):
        biz = {"name": "Test", "website": "https://facebook.com/test", "phone": "+33..."}
        score, checks = score_authority(biz)
        custom = [c for c in checks if c["item"] == "custom_domain"]
        assert custom[0]["pass"] is False

    def test_no_website_low_score(self, minimal_business):
        score, _ = score_authority(minimal_business)
        assert score < 30


class TestScoreSchema:
    def test_no_website_schema_low(self, minimal_business):
        score, _ = score_schema(minimal_business)
        assert score <= 5  # Bare minimum without website

    def test_with_website_schema_higher(self, perfect_business):
        score, checks = score_schema(perfect_business)
        assert score >= 50
        assert any(c["item"] == "schema_geo" and c["pass"] for c in checks)


class TestScoreLocal:
    def test_target_city_bonus(self, perfect_business):
        score, checks = score_local(perfect_business)
        assert score >= 60
        city_check = [c for c in checks if c["item"] == "target_city"]
        assert city_check[0]["pass"] is True

    def test_department_74(self, perfect_business):
        score, checks = score_local(perfect_business)
        dept = [c for c in checks if c["item"] == "department_74"]
        assert len(dept) == 1
        assert dept[0]["pass"] is True

    def test_non_target_city_lower(self):
        biz = {"name": "Test", "city": "Lyon", "sector": "restaurant"}
        score, _ = score_local(biz)
        # Lyon not in target cities, but still gets base points
        assert score < 60


class TestScoreStructure:
    def test_perfect_structure(self, perfect_business):
        score, _ = score_structure(perfect_business)
        assert score >= 60

    def test_minimal_structure(self, minimal_business):
        score, _ = score_structure(minimal_business)
        assert score >= 30  # Base score


# ── Full Score Tests ──────────────────────────────────────────

class TestScoreGeo:
    def test_perfect_business_scores_high(self, perfect_business):
        result = score_geo(perfect_business)
        assert result.overall_score >= 60
        assert result.grade in ("A+", "A", "B", "C")

    def test_minimal_business_scores_low(self, minimal_business):
        result = score_geo(minimal_business)
        assert result.overall_score < 50
        assert result.grade in ("D", "F")

    def test_no_website_business(self, no_website_business):
        result = score_geo(no_website_business)
        assert result.schema_score < 30  # Schema needs website
        assert result.authority_score < 40

    def test_recommendations_generated(self, minimal_business):
        result = score_geo(minimal_business)
        assert len(result.recommendations) > 0

    def test_geo_queries_generated(self, perfect_business):
        result = score_geo(perfect_business)
        assert len(result.geo_query_coverage) >= 3
        assert any("annemasse" in q.lower() for q in result.geo_query_coverage)

    def test_idempotent(self, perfect_business):
        r1 = score_geo(perfect_business)
        r2 = score_geo(perfect_business)
        assert r1.overall_score == r2.overall_score
        assert r1.grade == r2.grade

    def test_all_scores_bounded(self, perfect_business):
        result = score_geo(perfect_business)
        for attr in ("overall_score", "definition_score", "authority_score",
                     "structure_score", "schema_score", "local_score", "freshness_score"):
            val = getattr(result, attr)
            assert 0 <= val <= 100, f"{attr}={val} out of bounds"


# ── Content Generation Tests ──────────────────────────────────

class TestGenerateGeoContent:
    def test_generates_definition(self, perfect_business):
        result = score_geo(perfect_business)
        content = generate_geo_content(perfect_business, result)
        assert len(content.definition_block) > 50
        assert "Restaurant Le Lac" in content.definition_block

    def test_generates_faq(self, perfect_business):
        result = score_geo(perfect_business)
        content = generate_geo_content(perfect_business, result)
        assert len(content.faq_items) >= 2
        assert all("question" in item and "answer" in item for item in content.faq_items)

    def test_generates_schema(self, perfect_business):
        result = score_geo(perfect_business)
        content = generate_geo_content(perfect_business, result)
        assert content.schema_json_ld["@type"] == "LocalBusiness"
        assert content.schema_json_ld["name"] == "Restaurant Le Lac"

    def test_meta_description_length(self, perfect_business):
        result = score_geo(perfect_business)
        content = generate_geo_content(perfect_business, result)
        assert len(content.meta_description) <= 160

    def test_local_signals(self, perfect_business):
        result = score_geo(perfect_business)
        content = generate_geo_content(perfect_business, result)
        assert len(content.local_signals) >= 3
        assert any("74" in s for s in content.local_signals)

    def test_minimal_business_content(self, minimal_business):
        result = score_geo(minimal_business)
        content = generate_geo_content(minimal_business, result)
        assert content.business_name == "Coiffeur"
        assert content.city == "Gaillard"


# ── Report Tests ───────────────────────────────────────────────

class TestReport:
    def test_empty_report(self):
        report = generate_report([])
        assert report.total_businesses == 0
        assert report.average_score == 0

    def test_report_with_data(self, sample_businesses):
        report = generate_report(sample_businesses)
        assert report.total_businesses == 5
        assert 0 < report.average_score <= 100
        assert report.geo_opportunity_score > 0
        assert len(report.by_sector) >= 2

    def test_grade_distribution(self, sample_businesses):
        report = generate_report(sample_businesses)
        total_graded = sum(report.by_grade.values())
        assert total_graded == 5

    def test_opportunity_inverse_of_score(self, sample_businesses):
        report = generate_report(sample_businesses)
        # Lower average = higher opportunity
        assert report.geo_opportunity_score == round(100 - report.average_score, 1)
