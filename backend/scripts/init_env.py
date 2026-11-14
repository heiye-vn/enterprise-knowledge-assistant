"""Create local-only credentials; preserve an existing .env without printing its secrets."""

import os
import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[2]
target = root / ".env"
template = (root / ".env.example").read_text(encoding="utf-8")
for placeholder in (
    "local-development-password",
    "local-development-storage-password",
    "local-development-graph-password",
):
    template = template.replace(placeholder, secrets.token_hex(24))
try:
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    print("Existing .env preserved.")
else:
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(template)
    print("Created .env with independent local credentials (mode 0600).")
