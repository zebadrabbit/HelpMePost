from app.ai.plan_validation import validate_plan


def test_validate_plan_accepts_good_shape():
    plan = {
        "bluesky": {"text": "Hi #pets", "hashtags": ["pets", "safety"], "alt_text": []},
        "youtube": {
            "title": "A title",
            "description": "Para 1.\n\nPara 2.",
            "tags": ["a", "b", "c", "d", "e", "f", "g", "h"],
            "category": "Pets & Animals",
        },
    }
    result = validate_plan(plan)
    assert result.ok is True


def test_validate_plan_bluesky_only_does_not_require_or_warn_about_youtube():
    plan = {
        "bluesky": {"text": "Hi #flask #bluesky", "hashtags": ["flask", "bluesky"], "alt_text": []},
    }
    result = validate_plan(plan, targets=["bluesky"])
    assert result.ok is True
    assert not any("youtube." in w for w in result.warnings)
    assert not any("youtube" in e for e in result.errors)


def test_validate_plan_rejects_missing_fields():
    plan = {"bluesky": {"text": "x"}, "youtube": {"title": "y"}}
    result = validate_plan(plan)
    assert result.ok is False
    assert any("bluesky.hashtags" in e or "youtube.description" in e for e in result.errors)
