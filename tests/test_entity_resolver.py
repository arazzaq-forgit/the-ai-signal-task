from src.resolver.entity_resolver import resolve_entity


def test_assignment_example_all_resolve_to_openai():
    for raw in ["OpenAI", "OpenAI, Inc.", "Open AI"]:
        assert resolve_entity(raw).canonical_name == "OpenAI"


def test_known_alias_variations():
    assert resolve_entity("Anthropic PBC").canonical_name == "Anthropic"
    assert resolve_entity("DeepMind").canonical_name == "Google DeepMind"
    assert resolve_entity("11Labs").canonical_name == "ElevenLabs"
    assert resolve_entity("Scale.ai").canonical_name == "Scale AI"
    assert resolve_entity("huggingface.co").canonical_name == "Hugging Face"


def test_fuzzy_match_catches_real_typo():
    result = resolve_entity("Antropic")  # missing 'h'
    assert result.canonical_name == "Anthropic"
    assert result.method == "fuzzy"
    assert result.confidence > 0.9


def test_unrelated_company_is_honest_no_match():
    result = resolve_entity("Ben and Jerrys Ice Cream LLC")
    assert result.method == "no_match"
    assert result.canonical_name == result.raw_name  # unchanged, not forced to a wrong canonical


def test_empty_input_handled():
    result = resolve_entity("")
    assert result.method == "no_match"


# Regression tests: these are real false positives found when this pipeline
# ran against live Product Hunt data with the old WRatio-based scorer.
# WRatio over-rewards substring containment (e.g. "pika" is literally inside
# "deePIKAsharma"), which is wrong for short company names. These must all
# resolve to no_match with the current ratio-based scorer + length guards.
REAL_FALSE_POSITIVES_FROM_LIVE_DATA = [
    "Hungry Labs", "Habit Labs", "Mixed Media Labs", "Canopy Labs", "Kimono Labs",
    "Clara Labs", "Akido Labs", "Shift Labs", "Tara AI", "Heroic Labs",
    "Harmi Ai", "AI Lottery Predictor", "Chinnu Labs", "ImagineVid AI", "Pendulum AI",
    "AI Tools Directory", "B2B AI Directory", "SkillyTalk AI", "Audiobeta",
    "Tab", "L.", "SnapMagic", "HER", "Magic Instruments", "MagicBus", "GL",
    "Deepika Sharma", "buckramstudio",
]


def test_regression_no_false_positives_from_live_data():
    for raw in REAL_FALSE_POSITIVES_FROM_LIVE_DATA:
        result = resolve_entity(raw)
        assert result.method == "no_match", (
            f"REGRESSION: {raw!r} incorrectly matched to {result.canonical_name!r} "
            f"(confidence={result.confidence}) — this was a real false positive "
            f"found in live data with the old scorer."
        )
