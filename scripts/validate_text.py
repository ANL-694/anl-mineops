from __future__ import annotations

import re
from pathlib import Path

ROOTS = (Path("backend"), Path("docs"), Path("frontend/src"), Path(".github"))
TEXT_SUFFIXES = {".py", ".md", ".tsx", ".ts", ".css", ".yml", ".yaml", ".toml", ".json"}


def main() -> int:
    files = []
    for root in ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.suffix in TEXT_SUFFIXES:
                files.append(path)

    errors: list[str] = []
    for path in files:
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            errors.append(f"{path}: invalid UTF-8 ({exc})")
            continue
        if "\ufffd" in content:
            errors.append(f"{path}: contains U+FFFD")
        if re.search(r"(?<![A-Za-z0-9_])\?[0-9a-fk-or](?![A-Za-z])", content):
            errors.append(f"{path}: possible replaced Minecraft color code")
        if "???" in content:
            errors.append(f"{path}: contains suspicious repeated question marks")
        if any(marker in content for marker in ("Ã", "Â", "â€¦")):
            errors.append(f"{path}: possible mojibake")

    if errors:
        print("\n".join(errors))
        return 1
    print(f"UTF-8 scan passed for {len(files)} source/docs files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
