from dataclasses import asdict, dataclass, field


@dataclass(slots=True)
class ResumeBlock:
    page_no: int
    block_type: str
    block_index: int
    raw_text: str
    normalized_text: str
    confidence: float = 1.0
    bbox_json: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class ResumeParseResult:
    blocks: list[ResumeBlock] = field(default_factory=list)
    extracted_fields: dict = field(default_factory=dict)
    risk_items: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "blocks": [block.to_dict() for block in self.blocks],
            "extracted_fields": self.extracted_fields,
            "risk_items": self.risk_items,
        }
