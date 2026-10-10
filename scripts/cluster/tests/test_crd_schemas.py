"""crd_schemas.py turns CRDs into the strict schemas kubeconform reads (spec 0007 AC-11)."""

from __future__ import annotations

import copy
import importlib.util
import io
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

SCRIPT = Path(__file__).resolve().parents[1] / "crd_schemas.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("crd_schemas", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


crd_schemas = _load()

# CRD and schema documents are arbitrary nested mappings, so Any is the honest type here.
Node = Any


def crd(
    kind: str = "Widget", group: str = "example.io", versions: list[Node] | None = None
) -> Node:
    """A minimal CustomResourceDefinition with one served version by default."""
    return {
        "apiVersion": "apiextensions.k8s.io/v1",
        "kind": "CustomResourceDefinition",
        "spec": {
            "group": group,
            "names": {"kind": kind},
            "versions": versions
            if versions is not None
            else [
                {
                    "name": "v1",
                    "served": True,
                    "schema": {
                        "openAPIV3Schema": {
                            "type": "object",
                            "properties": {"spec": {"type": "string"}},
                        }
                    },
                }
            ],
        },
    }


class TestStrict:
    """strict(): close objects, keep open ones open, make int-or-string explicit."""

    def test_an_object_with_properties_is_closed(self) -> None:
        node = {"type": "object", "properties": {"a": {"type": "string"}}}
        assert crd_schemas.strict(node)["additionalProperties"] is False

    def test_nested_objects_are_closed_too(self) -> None:
        node = {"properties": {"spec": {"properties": {"a": {"type": "string"}}}}}
        assert crd_schemas.strict(node)["properties"]["spec"]["additionalProperties"] is False

    def test_an_explicit_additional_properties_is_kept(self) -> None:
        node = {"properties": {"a": {}}, "additionalProperties": {"type": "string"}}
        assert crd_schemas.strict(node)["additionalProperties"] == {"type": "string"}

    def test_an_object_that_preserves_unknown_fields_stays_open(self) -> None:
        node = {"properties": {"a": {}}, "x-kubernetes-preserve-unknown-fields": True}
        assert "additionalProperties" not in crd_schemas.strict(node)

    def test_an_object_without_properties_stays_open(self) -> None:
        assert "additionalProperties" not in crd_schemas.strict({"type": "object"})

    @pytest.mark.parametrize("combinator", ["allOf", "anyOf", "oneOf", "not"])
    def test_branches_of_a_combinator_stay_open(self, combinator: str) -> None:
        branch: Node = {"properties": {"a": {"properties": {"b": {}}}}}
        node: Node = {
            "properties": {"x": {}},
            combinator: [branch] if combinator != "not" else branch,
        }
        result = crd_schemas.strict(node)
        inner = result[combinator][0] if combinator != "not" else result[combinator]
        assert "additionalProperties" not in inner
        assert "additionalProperties" not in inner["properties"]["a"]
        assert result["additionalProperties"] is False

    def test_int_or_string_becomes_one_of_string_or_integer(self) -> None:
        node = {"type": "string", "x-kubernetes-int-or-string": True}
        assert crd_schemas.strict(node) == {"oneOf": [{"type": "string"}, {"type": "integer"}]}

    def test_a_false_int_or_string_flag_is_dropped_and_the_type_kept(self) -> None:
        node = {"type": "string", "x-kubernetes-int-or-string": False}
        assert crd_schemas.strict(node) == {"type": "string"}

    def test_lists_and_scalars_pass_through(self) -> None:
        assert crd_schemas.strict([{"properties": {}}, "x", 3]) == [
            {"properties": {}, "additionalProperties": False},
            "x",
            3,
        ]

    def test_the_input_is_not_changed(self) -> None:
        node = {"properties": {"a": {"x-kubernetes-int-or-string": True, "type": "string"}}}
        before = copy.deepcopy(node)
        crd_schemas.strict(node)
        assert node == before


class TestSchemas:
    """schemas(): one strict draft 07 schema per served version, keyed by file path."""

    def test_the_key_is_group_lowercase_kind_and_version(self) -> None:
        result = crd_schemas.schemas(crd(kind="CiliumNetworkPolicy", group="cilium.io"))
        assert list(result) == ["cilium.io/ciliumnetworkpolicy_v1.json"]

    def test_each_schema_declares_draft_07_and_is_strict(self) -> None:
        [schema] = crd_schemas.schemas(crd()).values()
        assert schema["$schema"] == "http://json-schema.org/draft-07/schema#"
        assert schema["additionalProperties"] is False

    def test_versions_that_are_not_served_are_skipped(self) -> None:
        versions = [
            {"name": "v1alpha1", "served": False, "schema": {"openAPIV3Schema": {}}},
            {"name": "v1", "served": True, "schema": {"openAPIV3Schema": {}}},
            {"name": "v2", "schema": {"openAPIV3Schema": {}}},
        ]
        assert list(crd_schemas.schemas(crd(versions=versions))) == ["example.io/widget_v1.json"]

    def test_every_served_version_gets_its_own_schema(self) -> None:
        versions = [
            {"name": "v1", "served": True, "schema": {"openAPIV3Schema": {}}},
            {"name": "v2", "served": True, "schema": {"openAPIV3Schema": {}}},
        ]
        assert sorted(crd_schemas.schemas(crd(versions=versions))) == [
            "example.io/widget_v1.json",
            "example.io/widget_v2.json",
        ]


class TestMain:
    """main(): CRD YAML on stdin, schema files under --out."""

    def run(self, monkeypatch: pytest.MonkeyPatch, stdin: str, out: Path | None) -> int:
        argv = ["crd_schemas.py", *(["--out", str(out)] if out is not None else [])]
        monkeypatch.setattr(sys, "argv", argv)
        monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
        result: int = crd_schemas.main()
        return result

    def test_a_kubectl_list_writes_one_file_per_crd(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        stdin = yaml.safe_dump({"kind": "List", "items": [crd(kind="A"), crd(kind="B")]})
        assert self.run(monkeypatch, stdin, tmp_path) == 0
        written = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*.json"))
        assert written == ["example.io/a_v1.json", "example.io/b_v1.json"]

    def test_separate_documents_are_read_too(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        stdin = yaml.safe_dump_all([crd(kind="A"), None, crd(kind="B")])
        self.run(monkeypatch, stdin, tmp_path)
        assert len(list(tmp_path.rglob("*.json"))) == 2

    def test_the_written_file_is_the_schema_as_sorted_json(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        self.run(monkeypatch, yaml.safe_dump(crd()), tmp_path)
        text = (tmp_path / "example.io" / "widget_v1.json").read_text()
        assert json.loads(text) == crd_schemas.schemas(crd())["example.io/widget_v1.json"]
        assert text.endswith("\n")
        assert text == json.dumps(json.loads(text), indent=1, sort_keys=True) + "\n"

    def test_a_document_that_is_not_a_crd_is_skipped_with_a_note(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        stdin = yaml.safe_dump_all([{"kind": "ConfigMap"}, crd()])
        assert self.run(monkeypatch, stdin, tmp_path) == 0
        assert "skipping ConfigMap" in capsys.readouterr().err
        assert len(list(tmp_path.rglob("*.json"))) == 1

    def test_out_is_required(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with pytest.raises(SystemExit) as exit_info:
            self.run(monkeypatch, "", None)
        assert exit_info.value.code == 2


def test_the_vendored_schemas_are_strict() -> None:
    """Every committed schema closes its top level object, so kubeconform -strict means it."""
    schemas_dir = SCRIPT.parents[2] / "charts" / "schemas"
    files = sorted(schemas_dir.rglob("*.json"))
    assert len(files) == 4
    for path in files:
        schema = json.loads(path.read_text())
        assert schema["$schema"] == "http://json-schema.org/draft-07/schema#", path
        assert schema["additionalProperties"] is False, path
