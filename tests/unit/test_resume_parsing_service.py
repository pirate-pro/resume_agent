import pytest

from app.core.middleware.error_handler import WorkflowError
from app.domain.services.resume_parsing_service import ResumeParsingService


def test_parse_docx_extracts_blocks_and_fields(sample_resume_docx) -> None:
    service = ResumeParsingService()

    result = service.parse(str(sample_resume_docx))

    assert result.extracted_fields["name"] == "王小明"
    assert result.extracted_fields["email"] == "wangxiaoming@example.com"
    assert len(result.blocks) >= 10
    assert any("Python" in line for line in result.extracted_fields["skills_lines"])


def test_parse_pdf_success(sample_resume_pdf) -> None:
    service = ResumeParsingService()

    result = service.parse(str(sample_resume_pdf))

    assert result.extracted_fields["phone"] == "+86 13800000000"
    assert result.risk_items == []


def test_parse_unsupported_file_type_raises(tmp_path) -> None:
    path = tmp_path / "resume.txt"
    path.write_text("plain text")
    service = ResumeParsingService()

    with pytest.raises(WorkflowError):
        service.parse(str(path))
