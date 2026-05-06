"""
Tests for GEO Agent — SocialPulse.
Skill #6 (Evals) + Skill #12 (GEO optimization).
"""

import pytest
from geo_agent import (
    DesignMdContract,
    GeoAuditContract,
    GeoOptimizedContent,
    GeoReportContract,
    GeoScoreResult,
    _grade,
    _get_profile,
    _SECTOR_PROFILES,
    generate_design_md,
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


# ── DESIGN.md Tests (inspired by VoltAgent/Google Stitch excellence) ──

class TestDesignMdContract:
    """DesignMdContract validation."""

    def test_contract_validates(self):
        d = DesignMdContract(
            business_name="Test",
            city="Annemasse",
            sector="restaurant",
            markdown="# Design System\nContent here.",
        )
        assert d.business_name == "Test"
        assert d.geo_score == 0
        assert d.sections == []

    def test_contract_requires_markdown_min_10(self):
        with pytest.raises(Exception):
            DesignMdContract(
                business_name="X",
                city="Y",
                sector="z",
                markdown="short",
            )

    def test_contract_geo_score_bounds(self):
        with pytest.raises(Exception):
            DesignMdContract(
                business_name="X",
                city="Y",
                sector="z",
                geo_score=150,
                markdown="# " + "x" * 50,
            )


class TestSectorProfiles:
    """Sector-specific style profiles."""

    def test_all_profiles_have_palette(self):
        for name, profile in _SECTOR_PROFILES.items():
            assert "palette" in profile, f"{name} missing palette"
            pal = profile["palette"]
            for key in ("primary", "secondary", "accent", "background", "surface", "text", "text_muted"):
                assert key in pal, f"{name} missing palette.{key}"

    def test_all_profiles_have_fonts(self):
        for name, profile in _SECTOR_PROFILES.items():
            assert "fonts" in profile, f"{name} missing fonts"
            fonts = profile["fonts"]
            for key in ("heading", "body", "fallback"):
                assert key in fonts, f"{name} missing fonts.{key}"

    def test_all_profiles_have_atmosphere(self):
        for name, profile in _SECTOR_PROFILES.items():
            assert "atmosphere" in profile, f"{name} missing atmosphere"
            assert len(profile["atmosphere"]) > 20

    def test_all_profiles_have_radius_and_shadow(self):
        for name, profile in _SECTOR_PROFILES.items():
            assert "radius" in profile, f"{name} missing radius"
            assert "shadow" in profile, f"{name} missing shadow"
            assert "px" in profile["radius"]

    def test_all_hex_colors_valid(self):
        import re
        hex_pattern = re.compile(r'^#[0-9A-Fa-f]{6}$')
        for name, profile in _SECTOR_PROFILES.items():
            pal = profile["palette"]
            for key, color in pal.items():
                assert hex_pattern.match(color), f"{name}.{key} = {color} is not a valid hex color"

    def test_get_profile_exact_match(self):
        for sector in _SECTOR_PROFILES:
            assert _get_profile(sector) is _SECTOR_PROFILES[sector]

    def test_get_profile_fallback(self):
        profile = _get_profile("astrologue_voyance")
        assert profile is _SECTOR_PROFILES["commerce"]

    def test_get_profile_substring_match(self):
        profile = _get_profile("restaurant_japonais")
        assert profile is _SECTOR_PROFILES["restaurant"]

    def test_profile_count(self):
        assert len(_SECTOR_PROFILES) == 8


class TestGenerateDesignMd:
    """generate_design_md() function."""

    def test_basic_generation(self, perfect_business):
        score = score_geo(perfect_business)
        content = generate_geo_content(perfect_business, score)
        design = generate_design_md(perfect_business, score, content)

        assert isinstance(design, DesignMdContract)
        assert design.business_name == "Restaurant Le Lac"
        assert design.city == "Annemasse"
        assert len(design.markdown) > 1000
        assert len(design.sections) >= 8

    def test_generation_without_score(self, perfect_business):
        design = generate_design_md(perfect_business)
        assert design.geo_score == 0
        assert "0/100" in design.markdown

    def test_generation_without_content(self, perfect_business):
        score = score_geo(perfect_business)
        design = generate_design_md(perfect_business, score, content=None)
        # Should still have GEO content section but with placeholder
        assert "geo_content" in design.sections
        assert "generate_geo_content()" in design.markdown

    def test_sections_always_present(self, minimal_business):
        design = generate_design_md(minimal_business)
        expected = ["header", "atmosphere", "palette", "typography", "layout", "shadows", "geo_content", "schema", "local_seo", "components"]
        for section in expected:
            assert section in design.sections, f"Missing section: {section}"

    def test_markdown_has_business_name(self, perfect_business):
        design = generate_design_md(perfect_business)
        assert perfect_business["name"] in design.markdown

    def test_markdown_has_city(self, perfect_business):
        design = generate_design_md(perfect_business)
        assert "Annemasse" in design.markdown

    def test_markdown_has_geo_score(self, perfect_business):
        score = score_geo(perfect_business)
        design = generate_design_md(perfect_business, score)
        assert f"{score.overall_score}/100" in design.markdown
        assert score.grade in design.markdown

    def test_markdown_has_json_ld(self, perfect_business):
        score = score_geo(perfect_business)
        content = generate_geo_content(perfect_business, score)
        design = generate_design_md(perfect_business, score, content)
        assert '"@context": "https://schema.org"' in design.markdown
        assert '"@type": "LocalBusiness"' in design.markdown

    def test_markdown_has_faq(self, perfect_business):
        score = score_geo(perfect_business)
        content = generate_geo_content(perfect_business, score)
        design = generate_design_md(perfect_business, score, content)
        assert "**Q1**:" in design.markdown
        assert "**A1**:" in design.markdown

    def test_markdown_has_component_rules(self, perfect_business):
        design = generate_design_md(perfect_business)
        assert "CTA Button" in design.markdown
        assert "Navigation" in design.markdown
        assert "Footer" in design.markdown

    def test_restaurant_profile_used(self):
        biz = {"name": "Test", "city": "Gaillard", "sector": "restaurant"}
        design = generate_design_md(biz)
        assert design.style_profile == "restaurant"
        assert "#8B4513" in design.markdown  # restaurant primary

    def test_plombier_profile_used(self):
        biz = {"name": "Test", "city": "Gaillard", "sector": "plombier"}
        design = generate_design_md(biz)
        assert design.style_profile == "plombier"
        assert "#0D47A1" in design.markdown  # plombier primary

    def test_coiffeur_profile_used(self):
        biz = {"name": "Test", "city": "Annemasse", "sector": "coiffeur"}
        design = generate_design_md(biz)
        assert "#1A1A2E" in design.markdown  # coiffeur primary

    def test_audit_section_present_when_score(self, perfect_business):
        score = score_geo(perfect_business)
        design = generate_design_md(perfect_business, score)
        assert "audit" in design.sections
        assert "GEO Audit Summary" in design.markdown
        assert "Definition" in design.markdown  # axis name in audit table

    def test_audit_section_absent_when_no_score(self, minimal_business):
        design = generate_design_md(minimal_business)
        assert "audit" not in design.sections

    def test_reproducible(self, perfect_business):
        """Deterministic: same input → same output."""
        score = score_geo(perfect_business)
        content = generate_geo_content(perfect_business, score)
        d1 = generate_design_md(perfect_business, score, content)
        d2 = generate_design_md(perfect_business, score, content)
        # Everything except timestamp should match
        assert d1.sections == d2.sections
        assert d1.style_profile == d2.style_profile
        assert d1.geo_score == d2.geo_score

    def test_all_sectors_generate(self):
        for sector in _SECTOR_PROFILES:
            biz = {"name": f"Test {sector}", "city": "Annemasse", "sector": sector}
            design = generate_design_md(biz)
            assert len(design.markdown) > 1000, f"{sector} generated too little"
            assert sector in design.markdown or design.style_profile == sector

    def test_unknown_sector_uses_commerce(self):
        biz = {"name": "Test", "city": "Annemasse", "sector": "astrologue"}
        design = generate_design_md(biz)
        assert design.style_profile == "commerce"

    def test_header_has_socialpulse_branding(self, perfect_business):
        design = generate_design_md(perfect_business)
        assert "SocialPulse GEO Agent" in design.markdown

    def test_haute_savoie_mentioned(self, perfect_business):
        design = generate_design_md(perfect_business)
        assert "Haute-Savoie" in design.markdown
        assert "74" in design.markdown

    def test_phone_and_website_in_local_seo(self, perfect_business):
        score = score_geo(perfect_business)
        content = generate_geo_content(perfect_business, score)
        design = generate_design_md(perfect_business, score, content)
        assert "4 50" in design.markdown or "+33" in design.markdown
        assert "https://" in design.markdown
