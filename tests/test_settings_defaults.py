from typing import Any, cast

from app.core.settings import Settings


def test_cost_aware_tool_context_defaults() -> None:
    settings = cast(Any, Settings)(_env_file=None)

    assert settings.tool_schema_disclosure_mode == "search"
    assert settings.tool_context_window_mode == "compact"
    assert settings.workflow_rule_selection_mode == "sparse"
