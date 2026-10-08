"""`python -m tessaro_auth.devkeys`: write local dev token keys into `.env` (`just keys`).

The only writer of `DEV_ADAPTER_SIGNING_KEY`, `DEV_WORKER_SIGNING_KEY` and
`TOKEN_VERIFY_KEYS`. When all three hold a value it changes nothing; otherwise it
generates two fresh Ed25519 pairs (`adapter-1`, `worker-1`) and rewrites all three.
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

from tessaro_auth.keys import KeyEntry, KeySet, b64url_encode

ADAPTER_VAR: Final = "DEV_ADAPTER_SIGNING_KEY"
WORKER_VAR: Final = "DEV_WORKER_SIGNING_KEY"
VERIFY_VAR: Final = "TOKEN_VERIFY_KEYS"
MANAGED: Final = (ADAPTER_VAR, WORKER_VAR, VERIFY_VAR)


def read_env(text: str) -> dict[str, str]:
    """Parse `KEY=value` lines, stripping one pair of matching quotes. Comments are skipped."""
    values: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def _private_b64url(key: Ed25519PrivateKey) -> str:
    raw = key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    return b64url_encode(raw)


def generate_lines() -> dict[str, str]:
    """Fresh `.env` lines for the three managed variables, keyed by variable name."""
    adapter, worker = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    keyset = KeySet.of(
        KeyEntry.create("adapter-1", adapter.public_key()),
        KeyEntry.create("worker-1", worker.public_key()),
    )
    return {
        ADAPTER_VAR: f"{ADAPTER_VAR}={_private_b64url(adapter)}",
        WORKER_VAR: f"{WORKER_VAR}={_private_b64url(worker)}",
        VERIFY_VAR: f"{VERIFY_VAR}='{keyset.to_jwks_json()}'",
    }


def ensure_dev_keys(text: str) -> str | None:
    """The new `.env` text, or None when all three variables already hold a value."""
    current = read_env(text)
    if all(current.get(name) for name in MANAGED):
        return None
    fresh = generate_lines()
    kept: list[str] = []
    for line in text.splitlines():
        name = line.partition("=")[0].strip()
        if "=" in line and not line.lstrip().startswith("#") and name in fresh:
            kept.append(fresh.pop(name))
        else:
            kept.append(line)
    kept.extend(fresh.values())
    return "\n".join(kept) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for `just keys`."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    args = parser.parse_args(argv)
    env_file: Path = args.env_file
    if not env_file.exists():
        sys.stderr.write(f"{env_file} not found; run `just init` first\n")
        return 1
    updated = ensure_dev_keys(env_file.read_text(encoding="utf-8"))
    if updated is None:
        sys.stdout.write(f"{env_file}: dev token keys already set, unchanged\n")
        return 0
    env_file.write_text(updated, encoding="utf-8")
    sys.stdout.write(f"{env_file}: wrote fresh dev token keys (adapter-1, worker-1)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
