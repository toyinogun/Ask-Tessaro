"""`python -m tessaro_privacy_proxy.devkeys`: fill the proxy's dev keys in `.env` (`just keys`).

Fills each of `PROXY_CLIENT_KEY`, `PROXY_MAPPING_KEY` and `PROXY_LOOKUP_KEY` only when it is
missing or empty, so existing keys (and the mappings they protect) are never rotated.
"""

import argparse
import os
import secrets
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from tessaro_privacy_proxy.mapping.cipher import KEY_BYTES, encode_key

MANAGED: Final = ("PROXY_CLIENT_KEY", "PROXY_MAPPING_KEY", "PROXY_LOOKUP_KEY")


def _fresh(name: str) -> str:
    if name == "PROXY_CLIENT_KEY":
        return secrets.token_urlsafe(KEY_BYTES)
    return encode_key(os.urandom(KEY_BYTES))


def _value(line: str) -> str:
    return line.partition("=")[2].strip().strip("'\"")


def ensure_proxy_keys(text: str) -> str | None:
    """The new `.env` text, or None when every managed variable already holds a value."""
    lines = text.splitlines()
    present = {
        line.partition("=")[0].strip(): _value(line)
        for line in lines
        if "=" in line and not line.lstrip().startswith("#")
    }
    missing = [name for name in MANAGED if not present.get(name)]
    if not missing:
        return None
    fresh = {name: f"{name}={_fresh(name)}" for name in missing}
    updated = [
        fresh.pop(name) if name in fresh else line
        for line, name in ((line, line.partition("=")[0].strip()) for line in lines)
    ]
    return "\n".join([*updated, *fresh.values()]) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for `just keys`."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    args = parser.parse_args(argv)
    env_file: Path = args.env_file
    if not env_file.exists():
        sys.stderr.write(f"{env_file} not found; run `just init` first\n")
        return 1
    updated = ensure_proxy_keys(env_file.read_text(encoding="utf-8"))
    if updated is None:
        sys.stdout.write(f"{env_file}: privacy proxy keys already set, unchanged\n")
        return 0
    env_file.write_text(updated, encoding="utf-8")
    sys.stdout.write(f"{env_file}: wrote fresh privacy proxy keys\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
