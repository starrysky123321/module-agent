from module_agent.shared.redaction import redact_sensitive_text


def test_url_keys_passwords_and_bearer_tokens_are_hidden():
    raw = "HTTP 429 https://api.example/works?api_key=private-key&query=mnist Bearer private-token https://user:private-pass@db.example"
    clean = redact_sensitive_text(raw)
    assert (
        "private-key" not in clean
        and "private-token" not in clean
        and "private-pass" not in clean
    )
    assert "HTTP 429" in clean and "query=mnist" in clean


def test_configured_tokens_are_hidden_even_without_a_label(monkeypatch):
    from module_agent.shared.config import app_settings

    monkeypatch.setattr(app_settings, "github_token", "fixture-secret-123")
    assert "fixture-secret-123" not in redact_sensitive_text(
        "Unexpected token fixture-secret-123"
    )
