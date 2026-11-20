"""Decision rules of m3-ha-cluster/scripts/select_bootstrap_node.sh.

Each case writes synthetic grastate.dat files and checks the recommendation
and exit code (0 = recommendation, 2 = unsafe to decide).
"""

import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "m3-ha-cluster/scripts/select_bootstrap_node.sh"
UUID = "9ba5051b-e515-11f1-b080-d6e3434d2bb8"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


def grastate(tmp_path: Path, name: str, seqno: int, safe: int = 0, uuid: str = UUID) -> str:
    path = tmp_path / f"{name}.dat"
    path.write_text(
        "# GALERA saved state\nversion: 2.1\n"
        f"uuid:    {uuid}\nseqno:   {seqno}\nsafe_to_bootstrap: {safe}\n"
    )
    return f"{name}={path}"


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True)


def test_node_marked_safe_to_bootstrap_wins(tmp_path):
    result = run(
        grastate(tmp_path, "gigavolt-1", 128),
        grastate(tmp_path, "gigavolt-2", 129),
        grastate(tmp_path, "gigavolt-3", 130, safe=1),
    )
    assert result.returncode == 0
    assert "BOOTSTRAP: gigavolt-3 (safe_to_bootstrap: 1" in result.stdout


def test_highest_seqno_wins_after_clean_stops(tmp_path):
    result = run(
        grastate(tmp_path, "gigavolt-1", 210),
        grastate(tmp_path, "gigavolt-2", 214),
        grastate(tmp_path, "gigavolt-3", 212),
    )
    assert result.returncode == 0
    assert "BOOTSTRAP: gigavolt-2 (highest committed seqno: 214)" in result.stdout


def test_unknown_position_after_crash_is_unsafe(tmp_path):
    # A stale node with a valid-looking seqno must not be chosen while the
    # crashed nodes' positions are unknown.
    result = run(
        grastate(tmp_path, "gigavolt-1", 133),
        grastate(tmp_path, "gigavolt-2", -1),
        grastate(tmp_path, "gigavolt-3", -1),
    )
    assert result.returncode == 2
    assert "UNSAFE: gigavolt-2 has seqno -1" in result.stdout
    assert "--wsrep-recover" in result.stdout


def test_recovered_positions_resolve_the_crash(tmp_path):
    result = run(
        grastate(tmp_path, "gigavolt-1", 133),
        grastate(tmp_path, "gigavolt-2", -1),
        grastate(tmp_path, "gigavolt-3", -1),
        "--recovered", "gigavolt-2=135",
        "--recovered", "gigavolt-3=135",
    )
    assert result.returncode == 0
    assert "BOOTSTRAP: gigavolt-2 (highest committed seqno: 135)" in result.stdout


def test_diverged_cluster_uuids_are_unsafe(tmp_path):
    result = run(
        grastate(tmp_path, "gigavolt-1", 50),
        grastate(tmp_path, "gigavolt-2", 60, uuid="00000000-1111-2222-3333-444444444444"),
    )
    assert result.returncode == 2
    assert "different cluster UUIDs" in result.stdout


def test_requires_at_least_two_nodes(tmp_path):
    result = run(grastate(tmp_path, "gigavolt-1", 10))
    assert result.returncode == 1
