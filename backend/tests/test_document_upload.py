"""Tests for reading the text of an uploaded PDF document."""
import pytest
from pypdf import PdfWriter

from backend.app.storage import step_02_uploads as uploads

TEXT_PDF = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]/Contents 4 0 R"
    b"/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
    b"4 0 obj<</Length 44>>stream\nBT /F1 12 Tf 20 100 Td (Bartender 8 years) Tj ET\nendstream endobj\n"
    b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
    b"trailer<</Root 1 0 R/Size 6>>\nstartxref\n0\n%%EOF"
)


def test_removes_contact_details_but_keeps_years_and_other_numbers():
    text = (
        "Jane Doe, bartender since 2015 - 2020, 8 years, 120 cocktails.\n"
        "Mail jane.doe@example.com, Tel +49 170 1234567 or 030/123 45 678 or (0170) 123-4567.\n"
        "linkedin.com/in/jane-doe https://jane.example/cv www.jane.example\n"
        "IBAN DE89 3704 0044 0532 0130 00. Geboren am 01.02.1990."
    )
    cleaned = uploads.remove_personal_data(text)
    for gone in ("@", "1234567", "030/123", "123-4567", "linkedin", "jane.example", "DE89", "01.02.1990"):
        assert gone not in cleaned
    assert "Jane Doe, bartender since 2015 - 2020, 8 years, 120 cocktails." in cleaned


def test_removes_birth_year_and_age_but_keeps_career_years():
    text = "Instagram: @cats_cocktails96 | Born: 05.1996. Born 1990. Geboren: März 1990. Date of birth: 5 May 1990. Alter: 34. 34 years old. Barkeeper since 2015, 8 years in bars."
    cleaned = uploads.remove_personal_data(text)
    assert "1990" not in cleaned and "34" not in cleaned and "@" not in cleaned and "1996" not in cleaned
    assert "Barkeeper since 2015, 8 years in bars." in cleaned


def test_month_names_ending_in_ne_keep_their_year():
    text = "Bartender | May 2020 \u2013 June 2022, Bartender | Sept 2018 \u2013 June 2019. N\u00e9 le 01.02.1990"
    cleaned = uploads.remove_personal_data(text)
    assert "June 2022" in cleaned and "June 2019" in cleaned and "1990" not in cleaned


def test_reads_text_from_pdf(tmp_path):
    path = tmp_path / "cv.pdf"
    path.write_bytes(TEXT_PDF)
    assert "Bartender 8 years" in uploads.extract_pdf_text(path)


def test_pdf_without_text_is_reported_as_scan(tmp_path):
    writer = PdfWriter()
    writer.add_blank_page(100, 100)
    path = tmp_path / "scan.pdf"
    with path.open("wb") as handle:
        writer.write(handle)
    with pytest.raises(ValueError, match="No text was found"):
        uploads.extract_pdf_text(path)


def test_damaged_pdf_gets_friendly_message_with_details(tmp_path):
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"%PDF-1.4 not really a pdf")
    with pytest.raises(ValueError, match=r"could not be read.*\(Technical details:"):
        uploads.extract_pdf_text(path)


def test_too_many_pages_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(uploads, "MAX_DOCUMENT_PAGES", 1)
    writer = PdfWriter()
    writer.add_blank_page(100, 100)
    writer.add_blank_page(100, 100)
    path = tmp_path / "long.pdf"
    with path.open("wb") as handle:
        writer.write(handle)
    with pytest.raises(ValueError, match="2 pages; the limit is 1"):
        uploads.extract_pdf_text(path)
