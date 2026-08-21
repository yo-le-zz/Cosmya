from cosmya.ai.provider import redact


def test_redacts_openai_style_key():
    text = "Error calling API with key sk-abc123DEF456ghi789JKL"
    assert "sk-abc123DEF456ghi789JKL" not in redact(text)
    assert "[REDACTED]" in redact(text)


def test_redacts_google_style_key():
    text = "Failed with key AIzaSyD-abcdefghijklmnopqrstuvwxyz0123"
    assert "AIzaSyD" not in redact(text)


def test_redacts_bearer_token():
    text = "Authorization: Bearer abcdefghijklmnop.qrstuvwxyz1234567890"
    assert "abcdefghijklmnop" not in redact(text)


def test_leaves_ordinary_text_untouched():
    text = "The model returned HTTP 500 for model gpt-5"
    assert redact(text) == text
