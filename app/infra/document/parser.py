from pathlib import Path

from docx import Document
from pypdf import PdfReader

from app.core.middleware.error_handler import WorkflowError


class DocumentTextExtractor:
    def extract_pages(self, file_path: str) -> list[str]:
        path = Path(file_path)
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            return self._extract_pdf(path)
        if suffix == ".docx":
            return self._extract_docx(path)
        raise WorkflowError(f"unsupported_file_type: {suffix}", status_code=422)

    def _extract_pdf(self, path: Path) -> list[str]:
        reader = PdfReader(str(path))
        pages: list[str] = []
        for page in reader.pages:
            pages.append(page.extract_text() or "")
        if not any(page.strip() for page in pages):
            raise WorkflowError("pdf_text_empty", status_code=422)
        return pages

    def _extract_docx(self, path: Path) -> list[str]:
        document = Document(str(path))
        text = "\n".join(paragraph.text for paragraph in document.paragraphs)
        if not text.strip():
            raise WorkflowError("docx_text_empty", status_code=422)
        return [text]
