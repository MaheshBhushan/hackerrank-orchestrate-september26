"""Package only the runnable solution and its evaluation artifacts."""

import zipfile
from pathlib import Path


def main():
    code = Path(__file__).resolve().parents[1]
    destination = code.parent / "code.zip"
    allowed = {".py", ".json", ".md"}
    paths = sorted(
        p
        for p in code.rglob("*")
        if p.is_file() and p.suffix in allowed and "__pycache__" not in p.parts
    )
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in paths:
            info = zipfile.ZipInfo(
                path.relative_to(code).as_posix(), (2026, 9, 12, 0, 0, 0)
            )
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())
    with zipfile.ZipFile(destination) as archive:
        if archive.testzip() is not None:
            raise ValueError("Archive failed integrity check")
        if "evaluation/usage_report.md" not in archive.namelist():
            raise ValueError("Missing mandatory usage report")
    print(f"Packaged {len(paths)} files: {destination}")


if __name__ == "__main__":
    main()
