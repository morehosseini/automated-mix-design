"""Re-run the current BRE/DOE evidence pack.

Run from the project root:
    python3 Code/run_reproducibility.py

The source R03 notebook is executed in memory and is not overwritten.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENGINE_DIR = PROJECT_ROOT / "Code" / "bre_engine"
NOTEBOOK = PROJECT_ROOT / "Code" / "Concrete_Mix_Design_R03.ipynb"


def run_step(label: str, command: list[str], cwd: Path) -> None:
    print(f"\n=== {label} ===")
    print("$", " ".join(command))
    completed = subprocess.run(command, cwd=cwd)
    if completed.returncode:
        raise SystemExit(f"{label} failed with exit code {completed.returncode}")


def run_notebook() -> None:
    try:
        import nbformat
    except ImportError as exc:
        raise SystemExit(
            "Notebook execution requires the dependencies in requirements.txt: "
            f"{exc}"
        ) from exc

    if shutil.which("jupyter") is None:
        raise SystemExit("The `jupyter` command is required to execute the R03 notebook.")

    temp_dir = Path(tempfile.mkdtemp(prefix="automated_mix_design_r03_"))
    executed = temp_dir / "R03_executed.ipynb"
    command = [
        "jupyter", "nbconvert", "--to", "notebook", "--execute",
        "--output", str(executed), "--ExecutePreprocessor.timeout=120",
        str(NOTEBOOK),
    ]
    completed = subprocess.run(command, cwd=PROJECT_ROOT / "Code")
    if completed.returncode:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise SystemExit(f"R03 notebook execution failed with exit code {completed.returncode}")

    notebook = nbformat.read(executed, as_version=4)
    errors = [
        output
        for cell in notebook.cells
        if cell.cell_type == "code"
        for output in cell.get("outputs", [])
        if output.output_type == "error"
    ]
    shutil.rmtree(temp_dir, ignore_errors=True)
    if errors:
        raise SystemExit(f"R03 notebook produced {len(errors)} error output(s)")
    print("R03 notebook: 0 error outputs")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-digitization", action="store_true")
    parser.add_argument("--skip-notebook", action="store_true")
    args = parser.parse_args()

    if not args.skip_digitization:
        for script in ("digitize_fig2.py", "digitize_fig3.py", "digitize_fig4_v2.py"):
            run_step(f"digitize {script}", [sys.executable, script], ENGINE_DIR)

    run_step("unit checks", [sys.executable, "test_bre_engine.py"], ENGINE_DIR)
    run_step("worked-example validation", [sys.executable, "validate_examples.py"], ENGINE_DIR)

    if not args.skip_notebook:
        run_notebook()

    print("\nReproducibility checks completed successfully.")


if __name__ == "__main__":
    main()
