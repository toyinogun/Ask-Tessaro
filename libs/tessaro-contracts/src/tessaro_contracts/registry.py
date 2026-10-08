"""Every released contract, by name, built and checked once at import (spec 0003 AC-14)."""

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from tessaro_contracts.contract import ContractError, ToolContract
from tessaro_contracts.people.get_my_leave import GET_MY_LEAVE


@dataclass(frozen=True, slots=True)
class Registry(Mapping[str, ToolContract]):
    """An immutable name to contract map."""

    contracts: Mapping[str, ToolContract]

    def __getitem__(self, name: str) -> ToolContract:
        return self.contracts[name]

    def __iter__(self) -> Iterator[str]:
        return iter(self.contracts)

    def __len__(self) -> int:
        return len(self.contracts)


def build_registry(contracts: Iterable[ToolContract]) -> Registry:
    """Build a registry; ContractError on a duplicate name or a bad `undo_tool`."""
    by_name: dict[str, ToolContract] = {}
    for contract in contracts:
        if contract.name in by_name:
            raise ContractError(f"duplicate tool name {contract.name!r}")
        by_name[contract.name] = contract
    for contract in by_name.values():
        undo = contract.write.undo_tool if contract.write else None
        if undo is None:
            continue
        target = by_name.get(undo)
        if target is None or target.write is None:
            raise ContractError(
                f"{contract.name}: undo_tool {undo!r} must be a registered write tool"
            )
    return Registry(MappingProxyType(by_name))


ALL_CONTRACTS = build_registry([GET_MY_LEAVE])
"""Every contract Tessaro publishes."""


def contract_by_name(name: str) -> ToolContract:
    """The released contract with this name; KeyError when there is none."""
    return ALL_CONTRACTS[name]
