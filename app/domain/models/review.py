from dataclasses import asdict, dataclass, field


@dataclass(slots=True)
class ReviewIssue:
    level: str
    message: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class ReviewReport:
    allow_delivery: bool
    risk_level: str
    issues: list[ReviewIssue] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "allow_delivery": self.allow_delivery,
            "risk_level": self.risk_level,
            "issues": [issue.to_dict() for issue in self.issues],
        }
