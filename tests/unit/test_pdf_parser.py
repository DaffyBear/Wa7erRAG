from pathlib import Path

import pytest
from rag_core.cleaning.parsers import PdfDocumentParser


def test_pdf_parser_extracts_pages_and_metadata(tmp_path: Path) -> None:
    from reportlab.pdfgen import canvas

    pdf_path = tmp_path / "paper.pdf"
    canvas_writer = canvas.Canvas(str(pdf_path))
    canvas_writer.drawString(72, 720, "Graph neural networks for cascading failure prediction")
    canvas_writer.showPage()
    canvas_writer.drawString(72, 720, "The proposed model improves Recall at K.")
    canvas_writer.save()

    source = PdfDocumentParser().parse(pdf_path)
    assert source.metadata["source_type"] == "pdf"
    assert source.metadata["page_count"] == 2
    assert "Graph neural networks" in source.content
    assert "## Page 2" in source.content


def test_pdf_parser_rejects_image_only_pdf(tmp_path: Path) -> None:
    from pypdf import PdfWriter

    pdf_path = tmp_path / "scan.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with pdf_path.open("wb") as output:
        writer.write(output)

    with pytest.raises(ValueError, match="requires OCR"):
        PdfDocumentParser().parse(pdf_path)
