"""The one error a bad dataset raises, holding every problem found."""

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class Problem:
    """One thing wrong with the dataset: where it is and what is wrong."""

    file: str
    record_id: str
    message: str

    def __str__(self) -> str:
        return f"{self.file} [{self.record_id}]: {self.message}"


class DatasetError(Exception):
    """The dataset is invalid; `problems` lists every problem, not only the first."""

    def __init__(self, problems: Iterable[Problem]) -> None:
        self.problems = tuple(sorted(problems))
        lines = "\n".join(f"  - {problem}" for problem in self.problems)
        super().__init__(f"the dataset has {len(self.problems)} problem(s):\n{lines}")
