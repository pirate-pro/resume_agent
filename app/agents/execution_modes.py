from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from app.agents.runtime import AgentToolTrace


@dataclass(slots=True)
class ModeActionResult:
    payload: Any = None
    observations: list[str] = field(default_factory=list)
    tool_traces: list[AgentToolTrace] = field(default_factory=list)


@dataclass(slots=True)
class PlanStep:
    step_id: str
    description: str


@dataclass(slots=True)
class PlanAndSolveExecution:
    plan: list[PlanStep]
    state: dict[str, Any]
    observations: list[str]
    tool_traces: list[AgentToolTrace]


class PlanAndSolveExecutor:
    def execute(
        self,
        *,
        objective: str,
        planner: Callable[[str], list[PlanStep]],
        solver: Callable[[PlanStep, dict[str, Any]], ModeActionResult],
    ) -> PlanAndSolveExecution:
        plan = planner(objective)
        state: dict[str, Any] = {}
        observations: list[str] = []
        tool_traces: list[AgentToolTrace] = []
        for step in plan:
            observations.append(f"plan.step.{step.step_id}: {step.description}")
            step_result = solver(step, state)
            if step_result.observations:
                observations.extend(step_result.observations)
            if step_result.tool_traces:
                tool_traces.extend(step_result.tool_traces)
            state[step.step_id] = step_result.payload
        return PlanAndSolveExecution(
            plan=plan,
            state=state,
            observations=observations,
            tool_traces=tool_traces,
        )


@dataclass(slots=True)
class ReActLoopStep:
    thought: str
    action: str
    observation: str


@dataclass(slots=True)
class ReActExecution:
    loop: list[ReActLoopStep]
    state: dict[str, Any]
    observations: list[str]
    tool_traces: list[AgentToolTrace]


class ReActExecutor:
    def execute(
        self,
        *,
        objective: str,
        max_steps: int,
        step_runner: Callable[[int, dict[str, Any]], tuple[ReActLoopStep, ModeActionResult, bool]],
    ) -> ReActExecution:
        state: dict[str, Any] = {"objective": objective}
        loop: list[ReActLoopStep] = []
        observations: list[str] = []
        tool_traces: list[AgentToolTrace] = []
        for index in range(max_steps):
            loop_step, action_result, done = step_runner(index, state)
            loop.append(loop_step)
            observations.append(loop_step.observation)
            if action_result.observations:
                observations.extend(action_result.observations)
            if action_result.tool_traces:
                tool_traces.extend(action_result.tool_traces)
            state[f"step_{index}"] = action_result.payload
            if done:
                break
        return ReActExecution(loop=loop, state=state, observations=observations, tool_traces=tool_traces)


@dataclass(slots=True)
class ReflectionExecution:
    initial_payload: Any
    final_payload: Any
    critique_payload: Any
    observations: list[str]
    tool_traces: list[AgentToolTrace]


class ReflectionExecutor:
    def execute(
        self,
        *,
        objective: str,
        actor: Callable[[], ModeActionResult],
        critic: Callable[[Any], ModeActionResult],
        reviser: Callable[[Any, Any], ModeActionResult] | None = None,
    ) -> ReflectionExecution:
        observations = [objective]
        tool_traces: list[AgentToolTrace] = []

        initial_result = actor()
        if initial_result.observations:
            observations.extend(initial_result.observations)
        if initial_result.tool_traces:
            tool_traces.extend(initial_result.tool_traces)

        critique_result = critic(initial_result.payload)
        if critique_result.observations:
            observations.extend(critique_result.observations)
        if critique_result.tool_traces:
            tool_traces.extend(critique_result.tool_traces)

        final_payload = initial_result.payload
        if reviser is not None:
            revise_result = reviser(initial_result.payload, critique_result.payload)
            if revise_result.observations:
                observations.extend(revise_result.observations)
            if revise_result.tool_traces:
                tool_traces.extend(revise_result.tool_traces)
            if revise_result.payload is not None:
                final_payload = revise_result.payload

        return ReflectionExecution(
            initial_payload=initial_result.payload,
            final_payload=final_payload,
            critique_payload=critique_result.payload,
            observations=observations,
            tool_traces=tool_traces,
        )
