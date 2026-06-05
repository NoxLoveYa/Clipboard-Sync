"""
build.py  —  Build Clipboard Sync into a standalone .exe file.

Usage:
    python build.py

Requires:  pip install pyinstaller

Output (in the dist/ folder):
    dist/
        ClipboardSync.exe   (unified client + server GUI)
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
DIST = HERE / "dist"

SCRIPTS = [
    {
        "name": "ClipboardSync",
        "source": "clipboard_sync.py",
    },
]


# ── helpers ──────────────────────────────────────────────────────────────────


def _find_spec_files() -> list[Path]:
    """Find .spec files in root and subdirectories."""
    specs: list[Path] = []
    for p in HERE.iterdir():
        if p.suffix == ".spec":
            specs.append(p)
    for sub in (HERE / "server", HERE / "client"):
        if sub.is_dir():
            for p in sub.iterdir():
                if p.suffix == ".spec":
                    specs.append(p)
    return specs


def check_dependencies() -> bool:
    """Make sure PyInstaller is available."""
    try:
        import PyInstaller  # noqa: F401
        return True
    except ImportError:
        print("  [!] PyInstaller is not installed.")
        print("      Run:  pip install pyinstaller")
        return False


def build(name: str, source: str) -> None:
    """Run PyInstaller for a single script."""
    source_path = HERE / source
    if not source_path.exists():
        print(f"  [X] Source not found: {source_path}")
        return

    print(f"\n{'=' * 60}")
    print(f"  Building:  {name}")
    print(f"  Source:    {source_path}")
    print(f"{'=' * 60}")

    # Clean up previous PyInstaller artifacts for this name
    spec_file = HERE / f"{name}.spec"
    if spec_file.exists():
        spec_file.unlink()

    build_dir = HERE / "build"
    if build_dir.exists():
        shutil.rmtree(build_dir, ignore_errors=True)

    cmd = [
        sys.executable or "python",
        "-m", "PyInstaller",
        "--onefile",
        "--windowed",
        "--name", name,
        "--distpath", str(DIST),
        "--workpath", str(HERE / "build"),
        "--specpath", str(HERE),
        str(source_path),
    ]

    print(f"  Running:  {' '.join(cmd)}\n")

    result = subprocess.run(cmd, cwd=HERE)
    if result.returncode != 0:
        print(f"\n  [X] Build failed for {name}")
        return

    # Locate the built exe
    exe = DIST / f"{name}.exe"
    if exe.exists():
        size_mb = exe.stat().st_size / (1024 * 1024)
        print(f"\n  [OK] {name}.exe  ({size_mb:.1f} MB)")
        print(f"      {exe}")
    else:
        print(f"\n  [X] Expected exe not found at: {exe}")


def clean_artifacts() -> None:
    """Remove PyInstaller build leftovers."""
    for spec in _find_spec_files():
        spec.unlink(missing_ok=True)
    build_dir = HERE / "build"
    if build_dir.exists():
        shutil.rmtree(build_dir, ignore_errors=True)
    # __pycache__ inside the project
    for pycache in HERE.rglob("__pycache__"):
        shutil.rmtree(pycache, ignore_errors=True)


def main() -> None:
    print("=" * 60)
    print("  Clipboard Sync - Build Script")
    print("=" * 60)

    if not check_dependencies():
        sys.exit(1)

    # Make sure dist/ exists
    DIST.mkdir(parents=True, exist_ok=True)

    for entry in SCRIPTS:
        build(entry["name"], entry["source"])

    # Tidy up temporary PyInstaller files
    clean_artifacts()

    print(f"\n{'=' * 60}")
    print(f"  Done.  {len(SCRIPTS)} build(s) complete.")
    print(f"  Output folder:  {DIST}")
    print(f"{'=' * 60}")

    # List the built exes
    for exe in sorted(DIST.glob("*.exe")):
        size = exe.stat().st_size / (1024 * 1024)
        print(f"    {exe.name}  ({size:.1f} MB)")


if __name__ == "__main__":
    main()
