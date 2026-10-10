"""`tessaro-seed`: one subcommand per job, each with its own flags and exit codes.

Exit codes: 0 success, 1 the job failed (the reason is printed), 2 bad usage.
"""

import sys
from collections.abc import Callable, Sequence

from tessaro_seed import blueprints, identity_secrets
from tessaro_seed.identity import command as identity

EXIT_USAGE = 2

COMMANDS: dict[str, Callable[[Sequence[str]], int]] = {
    "identity-secrets": identity_secrets.main,
    "identity": identity.main,
    "blueprints": blueprints.main,
}


def main(argv: Sequence[str] | None = None) -> int:
    """Run the subcommand named first in ``argv`` with the rest of the arguments."""
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] not in COMMANDS:
        print(f"usage: tessaro-seed {{{','.join(COMMANDS)}}} [options]", file=sys.stderr)
        return EXIT_USAGE
    return COMMANDS[args[0]](args[1:])
