from dataclasses import asdict, dataclass, field


@dataclass(slots=True)
class ChangeItem:
    section: str
    action: str
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class RiskNote:
    level: str
    message: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class OptimizationDraft:
    optimized_resume_markdown: str
    change_summary: list[ChangeItem] = field(default_factory=list)
    risk_notes: list[RiskNote] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "optimized_resume_markdown": self.optimized_resume_markdown,
            "change_summary": [item.to_dict() for item in self.change_summary],
            "risk_notes": [item.to_dict() for item in self.risk_notes],
        }
