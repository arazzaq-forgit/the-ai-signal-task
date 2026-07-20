from src.llm.chunking import chunk_text


def test_short_text_passes_through_unchanged():
    short = "This is a short article."
    assert chunk_text(short, char_budget=6000) == short


def test_cuts_at_paragraph_boundary_when_available():
    text = ("First paragraph with important facts. " * 20) + "\n\n" + ("Second paragraph. " * 200)
    result = chunk_text(text, char_budget=1000)
    assert "Second paragraph" not in result
    assert len(result) <= 1000


def test_cuts_at_sentence_boundary_when_no_paragraph_break():
    text = "Sentence one is here. Sentence two is here. Sentence three is here. " * 50
    result = chunk_text(text, char_budget=100)
    assert result.rstrip()[-1] in ".!?"


def test_hard_cut_fallback_for_text_with_no_breaks():
    text = "a" * 10000
    result = chunk_text(text, char_budget=500)
    assert len(result) == 500


def test_empty_and_none_input_handled():
    assert chunk_text("") == ""
    assert chunk_text(None) == ""
