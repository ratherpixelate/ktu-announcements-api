from datetime import date
from app.utils import extract_schemes, get_scheme_for_admission

def test_get_scheme_for_admission():
    assert get_scheme_for_admission(2015) == "2015"
    assert get_scheme_for_admission(2018) == "2015"
    assert get_scheme_for_admission(2019) == "2019"
    assert get_scheme_for_admission(2023) == "2019"
    assert get_scheme_for_admission(2024) == "2024"
    assert get_scheme_for_admission(2026) == "2024"

def test_extract_schemes_explicit_keyword():
    schemes = extract_schemes(date(2026, 5, 10), "Notification for 2019 scheme B.Tech students")
    assert "2019" in schemes

    schemes = extract_schemes(date(2026, 5, 10), "Applicable for 2024 admission batches")
    assert "2024" in schemes

def test_extract_schemes_general():
    schemes = extract_schemes(date(2026, 5, 10), "Holiday declared for the university on Friday")
    assert schemes == ["General"]

def test_extract_schemes_safety_check():
    schemes = extract_schemes(date(2026, 5, 10), "B.Tech S5 supplementary examination schedule")
    assert schemes == []

def test_extract_schemes_btech_ay_calculation():
    schemes = extract_schemes(date(2026, 10, 1), "B.Tech S3 registration for AY 2026-27")
    # S3 = year 2, admission = 2026 - 2 + 1 = 2025 -> scheme 2024
    assert schemes == ["2024"]
