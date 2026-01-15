from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def detect_version(root: Path) -> str:
    srt_gui = root / "srt_gui.py"
    if not srt_gui.exists():
        return "0.0"
    try:
        text = srt_gui.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return "0.0"

    import re

    m = re.search(r'VERSION\s*=\s*["\']([0-9]+(?:\.[0-9]+)*)["\']', text)
    if m:
        return m.group(1)
    m = re.search(r'字幕翻译工具\s+v([0-9]+(?:\.[0-9]+)*)', text)
    if m:
        return m.group(1)
    return "0.0"


def pyinstaller_add_data(src: Path, dest: str = ".") -> str:
    sep = ";" if os.name == "nt" else ":"
    return f"{src}{sep}{dest}"


def run(cmd: list[str], cwd: Path) -> None:
    subprocess.check_call(cmd, cwd=str(cwd))


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except Exception:
        return False


def safe_remove(path: Path, root: Path) -> None:
    if not path.exists():
        return
    if not _is_within(path, root):
        raise SystemExit(f"Refuse to delete outside project: {path}")
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def ensure_build_deps(root: Path, no_install: bool) -> None:
    missing = []
    try:
        import requests  # noqa: F401
    except Exception:
        missing.append("requests")
    try:
        import colorama  # noqa: F401
    except Exception:
        missing.append("colorama")
    try:
        import PyInstaller  # noqa: F401
    except Exception:
        missing.append("pyinstaller")

    if not missing:
        return

    if no_install:
        raise SystemExit(
            "Missing deps: "
            + ", ".join(missing)
            + "\nRun: python -m pip install -r requirements.txt pyinstaller"
        )

    req = root / "requirements.txt"
    try:
        if req.exists():
            run([sys.executable, "-m", "pip", "install", "-r", str(req), "pyinstaller"], cwd=root)
            return
    except subprocess.CalledProcessError:
        pass

    run([sys.executable, "-m", "pip", "install", "requests", "colorama", "pyinstaller"], cwd=root)


def main() -> int:
    root = project_root()
    parser = argparse.ArgumentParser(description="Build Windows onedir app via PyInstaller")
    parser.add_argument("--name", default=None, help="Output folder/app name")
    parser.add_argument("--version", default=None, help="Version string (used for default name)")
    parser.add_argument("--console", action="store_true", help="Build with console window")
    parser.add_argument("--no-install", action="store_true", help="Do not auto-install build deps")
    parser.add_argument("--no-clean", action="store_true", help="Do not delete previous build/dist artifacts")
    args = parser.parse_args()

    version = (args.version or detect_version(root)).strip() or "0.0"
    name = (args.name or f"srt_translator_gui_v{version}").strip()

    ensure_build_deps(root, no_install=args.no_install)

    entry = root / "srt_gui.py"
    if not entry.exists():
        raise SystemExit(f"Entry not found: {entry}")

    dist_dir = root / "dist"
    build_dir = root / "build"

    if not args.no_clean:
        safe_remove(dist_dir / name, root)
        safe_remove(build_dir, root)
        safe_remove(root / f"{name}.spec", root)

    cmd: list[str] = [sys.executable, "-m", "PyInstaller", "--clean", "--onedir"]
    cmd.append("--console" if args.console else "--noconsole")
    cmd += ["--name", name, "--distpath", str(dist_dir), "--workpath", str(build_dir)]

    icon = root / "srt_translator.ico"
    if icon.exists():
        cmd += ["--icon", str(icon)]

    for data_file in [
        root / "srt_gui_config.json",
        root / "srt_translator.ico",
        root / "srt_translator_icon.png",
    ]:
        if data_file.exists():
            cmd += ["--add-data", pyinstaller_add_data(data_file, ".")]

    cmd.append(str(entry))
    run(cmd, cwd=root)

    out_dir = dist_dir / name
    out_dir.mkdir(parents=True, exist_ok=True)

    # Keep config next to the exe for a portable "green" folder.
    cfg = root / "srt_gui_config.json"
    if cfg.exists():
        shutil.copy2(cfg, out_dir / cfg.name)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
