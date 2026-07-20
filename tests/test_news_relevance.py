from src.scrapers.news import _is_ai_relevant


def test_direct_ai_mentions_match():
    assert _is_ai_relevant("Kimi: Threat or menace?", "Chinese company Moonshot AI released a new version") is True
    assert _is_ai_relevant("OpenAI announces GPT-5.6", "") is True
    assert _is_ai_relevant("New neural network beats benchmark", "") is True
    assert _is_ai_relevant("Anthropic raises funding round", "") is True
    assert _is_ai_relevant("AI-powered chatbot launches", "") is True


def test_off_topic_content_does_not_match():
    assert _is_ai_relevant("The apps, gadgets, and tools every reader needs", "A newsletter about reading gadgets") is False


def test_substring_false_positives_avoided():
    # "again", "said", "chair", "remain", "rain" all contain "ai" as a
    # substring — the word-boundary regex must not treat these as AI mentions.
    assert _is_ai_relevant("Nvidia stock dips again", "Wall street traders said the chair was empty") is False
    assert _is_ai_relevant("Rain forecast for the weekend", "It will remain sunny with occasional rain") is False
