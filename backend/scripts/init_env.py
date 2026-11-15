"""Create the documented local development config, preserving an existing .env."""

import os
from pathlib import Path

root = Path(__file__).resolve().parents[2]
target = root / ".env"
template = (root / ".env.example").read_text(encoding="utf-8")
try:
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    print("Existing .env preserved.")
else:
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(template)
    print("Created .env with documented local development credentials (mode 0600).")
