"""Turn CustomResourceDefinitions into the JSON schemas kubeconform reads (spec 0007 AC-11).

Reads CRD YAML on stdin (``kubectl get crd <names> -o yaml``) and writes one strict schema per
served version to ``<out>/<group>/<kind>_<version>.json``, so ``just check`` validates Cilium,
Sealed Secrets and Argo CD objects without network access. Objects that list properties and do
not preserve unknown fields get ``additionalProperties: false``, like kubeconform's own strict
conversion.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

# JSON schema nodes are arbitrary nested dicts and lists, so Any is the honest type here.
Node = Any


# Branches of these keywords only add constraints (often ``required`` lists written as
# ``properties``), so closing them would reject every real object.
COMBINATORS = frozenset({"allOf", "anyOf", "oneOf", "not"})


def strict(node: Node, *, close: bool = True) -> Node:
    """Return a copy of ``node`` with closed objects and int-or-string types made explicit."""
    if isinstance(node, list):
        return [strict(item, close=close) for item in node]
    if not isinstance(node, dict):
        return node
    out = {
        key: strict(value, close=close and key not in COMBINATORS) for key, value in node.items()
    }
    if out.pop("x-kubernetes-int-or-string", False):
        out.pop("type", None)
        out["oneOf"] = [{"type": "string"}, {"type": "integer"}]
    preserve = out.get("x-kubernetes-preserve-unknown-fields", False)
    if close and "properties" in out and "additionalProperties" not in out and not preserve:
        out["additionalProperties"] = False
    return out


def schemas(crd: dict[str, Node]) -> dict[str, Node]:
    """Map ``<group>/<kind>_<version>.json`` to a strict schema for each served version."""
    spec = crd["spec"]
    group, kind = spec["group"], spec["names"]["kind"].lower()
    result: dict[str, Node] = {}
    for version in spec["versions"]:
        if not version.get("served", False):
            continue
        schema = strict(version["schema"]["openAPIV3Schema"])
        schema["$schema"] = "http://json-schema.org/draft-07/schema#"
        result[f"{group}/{kind}_{version['name']}.json"] = schema
    return result


def main() -> int:
    """Read CRDs on stdin and write their schemas under ``--out``."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    docs = [doc for doc in yaml.safe_load_all(sys.stdin) if doc]
    crds = [item for doc in docs for item in doc.get("items", [doc])]
    for crd in crds:
        if crd.get("kind") != "CustomResourceDefinition":
            print(f"skipping {crd.get('kind')}", file=sys.stderr)
            continue
        for rel, schema in schemas(crd).items():
            path = args.out / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(schema, indent=1, sort_keys=True) + "\n")
            print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
