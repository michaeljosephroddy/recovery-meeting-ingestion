from app.scraping.zero_source_audit import classify_zero_source_text


def test_zero_audit_does_not_treat_generic_src_as_embed() -> None:
    html = """
    <html>
      <body>
        <img src="/logo.png">
        <script src="/wp-content/theme.js"></script>
        <p>Find a meeting near you.</p>
      </body>
    </html>
    """

    bucket, priority, signals = classify_zero_source_text(
        html=html,
        text="Find a meeting",
        error="",
    )

    assert bucket == "meeting_keywords_only"
    assert priority == 4
    assert "embed" not in signals


def test_zero_audit_detects_real_calendar_embed() -> None:
    html = """
    <iframe src="https://calendar.google.com/calendar/embed?src=na@example.org"></iframe>
    """

    bucket, priority, signals = classify_zero_source_text(
        html=html,
        text="Tuesday 7:30 pm recovery meeting",
        error="",
    )

    assert bucket == "possible_embed_or_calendar"
    assert priority == 1
    assert "embed" in signals


def test_zero_audit_prefers_structured_feed_over_generic_embed() -> None:
    html = """
    <script>
      var crouton = {root_server: "https://bmlt.example.org/main_server",
        service_body: [12]};
    </script>
    """

    bucket, priority, signals = classify_zero_source_text(
        html=html,
        text="Meetings Monday 19:00",
        error="",
    )

    assert bucket == "possible_missed_structured_feed"
    assert priority == 1
    assert "structured_feed" in signals


def test_zero_audit_classifies_failed_timeout() -> None:
    bucket, priority, signals = classify_zero_source_text(
        html="",
        text="",
        last_status="failed",
        error="Timeout 30000ms exceeded",
    )

    assert bucket == "failed_timeout"
    assert priority == 4
    assert signals == []
