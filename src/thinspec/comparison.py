"""Replay fixtures through two implementations using the same input bytes."""
from __future__ import annotations

import difflib
import math
import shlex
import subprocess
from itertools import islice
from pathlib import Path
from typing import List, Tuple

from . import ThinSpecError


def compare(root: Path, baseline: str, candidate: str, fixtures: List[str], timeout: float) -> Tuple[bool, List[str]]:
    if not math.isfinite(timeout) or timeout <= 0:
        raise ThinSpecError("Give a positive comparison timeout.")
    try:
        old, new = shlex.split(baseline), shlex.split(candidate)
    except ValueError as exc:
        raise ThinSpecError("Invalid comparison command: %s" % exc) from exc
    if not old or not new:
        raise ThinSpecError("Give a command for each implementation.")

    def run(argv: List[str], data: bytes, side: str, fixture: str) -> bytes:
        try:
            result = subprocess.run(argv, cwd=root, input=data, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise ThinSpecError("%s timed out on %s after %g seconds." % (side, fixture, timeout)) from exc
        except OSError as exc:
            raise ThinSpecError("Cannot run %s on %s: %s" % (side, fixture, exc)) from exc
        if result.returncode:
            detail = result.stderr[-500:].decode("utf-8", errors="replace").strip()
            raise ThinSpecError("%s failed on %s (exit %d)%s." % (side, fixture, result.returncode,
                                                                  ": " + detail if detail else ""))
        return result.stdout

    differences = 0
    report = []
    for fixture in fixtures:
        try:
            data = (root / fixture).read_bytes()
        except OSError as exc:
            raise ThinSpecError("Cannot read fixture %s: %s" % (fixture, exc)) from exc
        a, b = run(old, data, "Baseline", fixture), run(new, data, "Candidate", fixture)
        if a == b:
            report.append("%s: match" % fixture)
            continue
        differences += 1
        report.append("%s: outputs differ (baseline %d bytes, candidate %d bytes)" % (fixture, len(a), len(b)))
        try:
            diff = difflib.unified_diff(a.decode().splitlines(keepends=True), b.decode().splitlines(keepends=True),
                                        fromfile="baseline", tofile="candidate", n=1)
            report.extend(line.rstrip("\n")[:240] for line in islice(diff, 20))
        except UnicodeDecodeError:
            pass  # the byte comparison still catches differences in binary outputs
    report.append("%d matched, %d differed." % (len(fixtures) - differences, differences))
    return differences == 0, report
