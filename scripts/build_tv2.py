"""Build two separate, Linux/Python 3.12-compatible Lambda ZIP archives."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def build(source_only=False):
    output = ROOT / "build" / "tv2"
    output.mkdir(parents=True, exist_ok=True)
    manifest = {"runtime": "python3.12", "architecture": "x86_64", "source_only": source_only, "artifacts": {}}
    for function in ("validate", "workflow-starter"):
        source = ROOT / "lambdas" / function
        target = output / f"{function}.zip"
        with tempfile.TemporaryDirectory(prefix=f"{function}-", dir=output) as stage_name:
            stage = Path(stage_name)
            if not source_only:
                subprocess.run([
                    sys.executable, "-m", "pip", "install",
                    "--disable-pip-version-check", "--no-compile",
                    "--platform", "manylinux2014_x86_64", "--implementation", "cp",
                    "--python-version", "3.12", "--only-binary=:all:",
                    "--target", str(stage), "-r", str(source / "requirements.txt"),
                ], check=True)
            with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
                files = [(path, path.relative_to(stage)) for path in stage.rglob("*") if path.is_file()]
                files += [(path, Path(path.name)) for path in source.glob("*.py")]
                for path, relative in sorted(files, key=lambda entry: str(entry[1])):
                    if "__pycache__" in relative.parts or path.suffix == ".pyc":
                        continue
                    info = zipfile.ZipInfo(relative.as_posix(), date_time=(2026, 1, 1, 0, 0, 0))
                    info.create_system = 3
                    info.external_attr = 0o100644 << 16
                    info.compress_type = zipfile.ZIP_DEFLATED
                    archive.writestr(info, path.read_bytes())
        manifest["artifacts"][function] = {
            "file": str(target.relative_to(ROOT)),
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "bytes": target.stat().st_size,
        }
        print(f"Built {target.relative_to(ROOT)}")
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-only", action="store_true", help="Development only: use SDK from Lambda runtime")
    build(parser.parse_args().source_only)
