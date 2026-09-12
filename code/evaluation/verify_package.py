"""Check that an extracted submission reproduces output.csv byte for byte."""

import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


def main():
    repository = Path(__file__).resolve().parents[2]
    with tempfile.TemporaryDirectory(prefix="buy-or-wait-package-") as temporary:
        root = Path(temporary)
        code = root / "code"
        code.mkdir()
        with zipfile.ZipFile(repository / "code.zip") as archive:
            archive.extractall(code)
        (root / "dataset").symlink_to(repository / "dataset", target_is_directory=True)
        subprocess.run([sys.executable, str(code / "main.py")], cwd=root, check=True)
        if (root / "output.csv").read_bytes() != (
            repository / "output.csv"
        ).read_bytes():
            raise ValueError("Packaged solution does not reproduce the final output")
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
