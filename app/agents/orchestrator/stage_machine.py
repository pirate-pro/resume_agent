MATCH_STAGES = ["intake", "parse", "profile", "retrieve", "rank", "explain", "deliver"]
OPTIMIZATION_STAGES = ["optimize", "review", "deliver"]


class StageMachine:
    def __init__(self, stages: list[str]) -> None:
        self._index = {stage: idx for idx, stage in enumerate(stages)}

    def ensure_transition(self, current_stage: str, next_stage: str) -> None:
        if next_stage not in self._index:
            raise ValueError(f"unknown_stage: {next_stage}")
        if self._index[next_stage] < self._index.get(current_stage, -1):
            raise ValueError(f"invalid_stage_transition: {current_stage}->{next_stage}")
