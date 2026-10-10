"""Read and edit dotenv text: `.env` and the git ignored files under `.secrets/`."""

from collections.abc import Mapping


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value


def read_env(text: str) -> dict[str, str]:
    """`NAME=value` pairs, skipping comments and blank lines; the last duplicate wins."""
    values: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, _, value = stripped.partition("=")
        values[name.strip()] = _unquote(value.strip())
    return values


def set_env(text: str, values: Mapping[str, str]) -> str:
    """New text with each name set once: first line replaced, duplicates dropped, new appended."""
    pending = dict(values)
    seen: set[str] = set()
    lines: list[str] = []
    for line in text.splitlines():
        name = line.partition("=")[0].strip()
        if "=" not in line or line.lstrip().startswith("#") or name not in values:
            lines.append(line)
        elif name not in seen:
            seen.add(name)
            lines.append(f"{name}={pending.pop(name)}")
    lines.extend(f"{name}={value}" for name, value in pending.items())
    return "\n".join(lines) + "\n"
