"""`RunState`: the shared, typed state agents operate over (MPS §13).

Agents are stateless functions: `Agent.run(state) -> state`. Nothing here is
mutated in place — every `with_*` method returns a new `RunState` built from
the previous one, mirroring the same functional-update style as
`Finding.with_evidence`/`with_state` in the domain core. This is what makes
a run's history reconstructable and each agent's effect on it inspectable
in isolation, rather than a shared mutable blob agents quietly clobber.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from cortexward.domain import Finding, Patch
from cortexward.ports import AnalysisRequest


@dataclass(frozen=True)
class RunState:
    """Everything one orchestrated agent run threads through its agents.

    `notes` is an append-only log of `(agent_name, note)` pairs — free-form
    scratch communication between agents (e.g. the Planner's chosen strategy,
    a Reviewer's rationale) that doesn't belong on the `Finding`/`Patch`
    models themselves. `completed_agents` and `rounds_completed` exist for
    the Coordinator agent's termination decisions (MPS §13: bounded retries,
    not unbounded agent loops).
    """

    request: AnalysisRequest
    findings: tuple[Finding, ...] = ()
    patches: tuple[Patch, ...] = ()
    notes: tuple[tuple[str, str], ...] = ()
    completed_agents: tuple[str, ...] = ()
    rounds_completed: int = 0

    def with_findings(self, findings: tuple[Finding, ...]) -> RunState:
        return replace(self, findings=findings)

    def with_patches(self, patches: tuple[Patch, ...]) -> RunState:
        return replace(self, patches=(*self.patches, *patches))

    def with_patches_updated(self, patches: tuple[Patch, ...]) -> RunState:
        """Replaces the whole `patches` tuple, unlike `with_patches`' append.

        For an agent (e.g. Reviewer) recording a gate verdict on patches
        `Repair` already proposed this run — `patches` must be the full,
        already-updated set, not new ones to add.
        """
        return replace(self, patches=patches)

    def with_note(self, agent_name: str, note: str) -> RunState:
        return replace(self, notes=(*self.notes, (agent_name, note)))

    def with_completed(self, agent_name: str) -> RunState:
        return replace(self, completed_agents=(*self.completed_agents, agent_name))

    def with_round_complete(self) -> RunState:
        return replace(self, rounds_completed=self.rounds_completed + 1)

    def notes_from(self, agent_name: str) -> tuple[str, ...]:
        """Every note `agent_name` has recorded so far, in recording order."""
        return tuple(note for name, note in self.notes if name == agent_name)


__all__ = ["RunState"]
