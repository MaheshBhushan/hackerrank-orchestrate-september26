"""Check that an extracted submission reproduces output.csv byte for byte."""

import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


def main():
    repository = Path(__file__).resolve().parents[2]
    with tempfile.TemporaryDirectory(prefix="buy-or-wait-package-") as temporary:
        root = Path(temporary)
        for layout in ("nested", "flat"):
            layout_root = root / layout
            code = layout_root / "code" if layout == "nested" else layout_root
            code.mkdir(parents=True)
            with zipfile.ZipFile(repository / "code.zip") as archive:
                archive.extractall(code)
            shutil.copytree(repository / "dataset", layout_root / "dataset")
            # Remove sample labels and the blank template: neither is a runtime input.
            (layout_root / "dataset" / "sample_requests.csv").unlink()
            (layout_root / "dataset" / "output.csv").unlink()
            subprocess.run(
                [sys.executable, str(code / "main.py")], cwd=root, check=True
            )
            if (layout_root / "output.csv").read_bytes() != (
                repository / "output.csv"
            ).read_bytes():
                raise ValueError(
                    f"{layout} archive does not reproduce the final output"
                )
        environment = dict(os.environ, PYTHONPATH=str(code))
        subprocess.run(
            [
                sys.executable,
                "-m",
                "unittest",
                "discover",
                "-s",
                str(code / "evaluation"),
                "-p",
                "test_*.py",
            ],
            cwd=root,
            env=environment,
            check=True,
        )
    print(
        "Extracted archive reproduces all 250 predictions and passes the regression tests."
    )


if __name__ == "__main__":
    main()
