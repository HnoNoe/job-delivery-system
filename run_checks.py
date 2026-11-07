"""Run all regressions in child processes; return nonzero on any failure."""
from pathlib import Path
import os
import subprocess
import sys

BASE = Path(__file__).resolve().parent


def main():
    commands = [["-m", "unittest", "discover", "-s", "tests", "-v"]]
    commands += [[name] for name in ("verify_formulas.py", "verify_resume_parse.py", "verify_rematch.py",
                                     "verify_viz.py", "verify_ui_compat.py", "verify_health.py", "mock_e2e.py")]
    failed = []
    for args in commands:
        print("\n>>> " + " ".join(args), flush=True)
        result = subprocess.run([sys.executable, *args], cwd=str(BASE),
                                env=dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1"))
        if result.returncode:
            failed.append(" ".join(args))
    print("\nFAILED: " + repr(failed) if failed else "\nAll checks passed.", flush=True)
    return int(bool(failed))


if __name__ == "__main__":
    raise SystemExit(main())
