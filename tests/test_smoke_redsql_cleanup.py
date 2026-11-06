"""The redsql smoke must only remove what its own invocation created (no real Docker needed)."""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import smoke_redsql_image as smoke  # noqa: E402


class FakeDocker:
    def __init__(self, fail_run_of=None):
        self.calls = []
        self.fail_run_of = fail_run_of

    def __call__(self, *args, check=True, **kw):
        self.calls.append(args)
        if args[0] == "run" and "--name" in args and args[args.index("--name") + 1].startswith(self.fail_run_of or "\0"):
            return subprocess.CompletedProcess(args, 125, stdout="name already in use")
        return subprocess.CompletedProcess(args, 0, stdout="")

    def removed(self):
        return [a[-1] for a in self.calls if a[0] == "rm"]


@pytest.fixture(autouse=True)
def reset(monkeypatch):
    smoke.created.update(containers=[], networks=[], images=[])
    yield
    smoke.created.update(containers=[], networks=[], images=[])


def test_name_collision_on_first_container_removes_nothing(monkeypatch):
    fake = FakeDocker(fail_run_of=smoke.REDIS)
    monkeypatch.setattr(smoke, "docker", fake)
    with pytest.raises(SystemExit):
        smoke.main()
    assert fake.removed() == []  # the colliding container is not ours, so it is never removed


def test_failure_on_second_container_removes_only_the_first(monkeypatch):
    fake = FakeDocker(fail_run_of=smoke.DB)
    monkeypatch.setattr(smoke, "docker", fake)
    with pytest.raises(SystemExit):
        smoke.main()
    assert fake.removed() == [smoke.REDIS]
    assert all(a[:2] == ("rm", "-fv") for a in fake.calls if a[0] == "rm")  # data volumes go too


def test_names_are_unique_per_invocation():
    assert smoke.RUN in smoke.DB and smoke.RUN in smoke.REDIS and smoke.RUN in smoke.SYNC
