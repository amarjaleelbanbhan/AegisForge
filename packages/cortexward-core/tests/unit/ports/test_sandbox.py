"""Conformance test for the Sandbox port."""

from __future__ import annotations

import time

import pytest

from cortexward.ports import (
    EgressPolicy,
    ExecutionResult,
    ExecutionSpec,
    ResourceLimits,
    SandboxPort,
)

pytestmark = pytest.mark.unit


class _FakeSandbox:
    isolation_tier = "fake-in-process"

    def execute(self, spec: ExecutionSpec) -> ExecutionResult:
        started = time.monotonic()
        if spec.egress != EgressPolicy.DENY_ALL and not spec.allowed_hosts:
            raise ValueError("allow-list egress requires at least one allowed host")
        return ExecutionResult(
            exit_code=0,
            stdout=" ".join(spec.command),
            stderr="",
            timed_out=False,
            duration_seconds=time.monotonic() - started,
        )


def test_fake_sandbox_satisfies_protocol() -> None:
    assert isinstance(_FakeSandbox(), SandboxPort)


def test_default_egress_is_deny_all() -> None:
    spec = ExecutionSpec(command=("echo", "hi"), input_bundle_ref="sha256:abc")
    assert spec.egress is EgressPolicy.DENY_ALL
    assert spec.limits == ResourceLimits()
    assert spec.image == "python:3.11-slim"


def test_execute_runs_command() -> None:
    spec = ExecutionSpec(command=("echo", "hi"), input_bundle_ref="sha256:abc")
    result = _FakeSandbox().execute(spec)
    assert result.exit_code == 0
    assert result.stdout == "echo hi"


def test_allow_list_without_hosts_is_rejected() -> None:
    spec = ExecutionSpec(
        command=("curl", "x"), input_bundle_ref="sha256:abc", egress=EgressPolicy.ALLOW_LIST
    )
    with pytest.raises(ValueError, match="allow-list"):
        _FakeSandbox().execute(spec)
