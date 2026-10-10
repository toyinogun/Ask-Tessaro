"""Render and check the platform Applications in deploy/argocd/ (spec 0008 AC-18).

A platform Application installs an upstream Helm chart at a pinned version with this repo's
values file, plus this repo's kustomize manifests folder. For each one this renders what Argo CD
would apply (``helm template`` of the chart, then ``kustomize build`` of the folder), writes it to
``<out>/<name>.yaml`` for kubeconform, and fails when the render holds a cluster scoped kind, a
Bitnami image, an image not pinned by tag and digest, an object outside the destination
namespace, a Secret with values, or a chart version other than the one the Application pins.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# Applications and rendered objects are arbitrary nested mappings, so Any is the honest type here.
Node = Any
Runner = Callable[[list[str]], str]

VALUES_REF = "$values/"

# Every kind a platform Application may render, as "<api group>/<kind>". All are namespaced, so
# anything else (a ClusterRole, a CRD, a webhook) fails the check: the AppProject fence admits no
# cluster scoped kind but Namespace (spec 0007), and a new namespaced kind is added here on purpose.
NAMESPACED_KINDS = frozenset(
    {
        "/ConfigMap",
        "/Endpoints",
        "/PersistentVolumeClaim",
        "/Pod",
        "/Secret",
        "/Service",
        "/ServiceAccount",
        "apps/Deployment",
        "apps/StatefulSet",
        "autoscaling/HorizontalPodAutoscaler",
        "batch/CronJob",
        "batch/Job",
        "cilium.io/CiliumNetworkPolicy",
        "networking.k8s.io/Ingress",
        "networking.k8s.io/NetworkPolicy",
        "policy/PodDisruptionBudget",
        "postgresql.cnpg.io/Cluster",
        "rbac.authorization.k8s.io/Role",
        "rbac.authorization.k8s.io/RoleBinding",
    }
)

IMAGE_KEYS = frozenset({"image", "imageName"})
PINNED = re.compile(r"^[^@\s]+:[\w][\w.-]*@sha256:[0-9a-f]{64}$")
CHART_LABEL = "helm.sh/chart"


@dataclass(frozen=True)
class PlatformApp:
    """One Application that installs an upstream chart, with its sources resolved to paths."""

    name: str
    namespace: str
    repo: str
    chart: str
    version: str
    release: str
    value_files: tuple[Path, ...]
    manifests: Path | None


def _documents(path: Path) -> Iterator[Node]:
    with path.open() as handle:
        yield from (doc for doc in yaml.safe_load_all(handle) if doc)


def _platform_app(app: Node, repo_root: Path) -> PlatformApp | None:
    spec = app.get("spec", {})
    sources = spec.get("sources", [])
    chart = next((s for s in sources if "chart" in s), None)
    if chart is None:
        return None
    name = app["metadata"]["name"]
    helm = chart.get("helm", {})
    value_files = []
    for ref in helm.get("valueFiles", []):
        if not ref.startswith(VALUES_REF):
            raise ValueError(f"{name}: value file {ref} must start with {VALUES_REF}")
        value_files.append(repo_root / ref.removeprefix(VALUES_REF))
    manifests = next(
        (
            repo_root / s["path"]
            for s in sources
            if s.get("path", "").startswith("deploy/platform/")
        ),
        None,
    )
    return PlatformApp(
        name=name,
        namespace=spec["destination"]["namespace"],
        repo=chart["repoURL"],
        chart=chart["chart"],
        version=str(chart["targetRevision"]),
        release=helm.get("releaseName", name),
        value_files=tuple(value_files),
        manifests=manifests,
    )


def platform_apps(argocd_dir: Path, repo_root: Path) -> tuple[PlatformApp, ...]:
    """Every Application in ``argocd_dir`` with an upstream chart source, sorted by name.

    Raises ValueError when a value file is not a ``$values/`` reference into this repo.
    """
    found = []
    for path in sorted(argocd_dir.glob("*.yaml")):
        for doc in _documents(path):
            if doc.get("kind") == "Application":
                app = _platform_app(doc, repo_root)
                if app is not None:
                    found.append(app)
    return tuple(sorted(found, key=lambda a: a.name))


def helm_args(app: PlatformApp, kube_version: str) -> list[str]:
    """The ``helm template`` command that renders the chart as Argo CD would."""
    if app.repo.startswith(("https://", "http://")):
        source = [app.chart, "--repo", app.repo]
    else:
        source = [f"oci://{app.repo.removeprefix('oci://')}/{app.chart}"]
    args = ["helm", "template", app.release, *source, "--version", app.version]
    args += ["--namespace", app.namespace, "--kube-version", kube_version]
    for path in app.value_files:
        args += ["--values", str(path)]
    return args


def run_command(args: list[str]) -> str:
    """Run a command and return its stdout; RuntimeError with its stderr when it fails."""
    # Fixed tools (helm, kustomize) with arguments built from this repo's own Applications.
    result = subprocess.run(args, capture_output=True, text=True, check=False)  # noqa: S603
    if result.returncode != 0:
        raise RuntimeError(f"{args[0]} {args[1]} failed: {result.stderr.strip()}")
    return result.stdout


def render(app: PlatformApp, kube_version: str, run: Runner | None = None) -> list[Node]:
    """The objects Argo CD would apply for ``app``: the chart, then the manifests folder."""
    runner = run if run is not None else run_command
    text = runner(helm_args(app, kube_version))
    if app.manifests is not None:
        text += "\n---\n" + runner(["kustomize", "build", str(app.manifests)])
    return [doc for doc in yaml.safe_load_all(text) if doc]


def _images(node: Node) -> Iterator[str]:
    if isinstance(node, dict):
        for key, value in node.items():
            if key in IMAGE_KEYS and isinstance(value, str):
                yield value
            else:
                yield from _images(value)
    elif isinstance(node, list):
        for item in node:
            yield from _images(item)


def _kind(doc: Node) -> str:
    api = str(doc.get("apiVersion", ""))
    group = api.rsplit("/", 1)[0] if "/" in api else ""
    return f"{group}/{doc.get('kind')}"


def _object_problems(app: PlatformApp, doc: Node) -> Iterator[str]:
    meta = doc.get("metadata", {})
    label = f"{doc.get('kind')}/{meta.get('name')}"
    if _kind(doc) not in NAMESPACED_KINDS:
        yield f"{label}: kind {_kind(doc)} is cluster scoped or not allowed"
    namespace = meta.get("namespace")
    if namespace not in (None, app.namespace):
        yield f"{label}: in namespace {namespace}, not {app.namespace}"
    if doc.get("kind") == "Secret" and (doc.get("data") or doc.get("stringData")):
        yield f"{label}: a Secret with values; use a SealedSecret or a generated Secret"
    for image in _images(doc.get("spec", {})):
        if "bitnami" in image.lower():
            yield f"{label}: image {image} is from bitnami"
        if not PINNED.match(image):
            yield f"{label}: image {image} is not pinned by tag and digest"


def problems(app: PlatformApp, manifests: list[Node]) -> list[str]:
    """Every AC-18 problem in one rendered Application; empty when it is clean."""
    found = [p for doc in manifests for p in _object_problems(app, doc)]
    want = f"{app.chart}-{app.version}"
    labels = {
        doc["metadata"]["labels"][CHART_LABEL]
        for doc in manifests
        if CHART_LABEL in doc.get("metadata", {}).get("labels", {})
    }
    if not labels:
        found.append(f"no object carries {CHART_LABEL}, so the rendered chart version is unknown")
    found += [
        f"rendered chart {got}, but the Application pins {want}" for got in sorted(labels - {want})
    ]
    return found


def main(argv: list[str] | None = None) -> int:
    """Render every platform Application into ``--out``; exit 1 on any problem."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--kube-version", default="1.33.0")
    args = parser.parse_args(argv)
    apps = platform_apps(args.repo_root / "deploy" / "argocd", args.repo_root)
    if not apps:
        print("platform: no platform Applications yet")
        return 0
    args.out.mkdir(parents=True, exist_ok=True)
    failed = False
    for app in apps:
        try:
            manifests = render(app, args.kube_version)
        except RuntimeError as error:
            print(f"{app.name}: {error}", file=sys.stderr)
            failed = True
            continue
        found = problems(app, manifests)
        for problem in found:
            print(f"{app.name}: {problem}", file=sys.stderr)
        failed = failed or bool(found)
        (args.out / f"{app.name}.yaml").write_text(yaml.safe_dump_all(manifests, sort_keys=False))
        print(f"platform: {app.name} {app.chart} {app.version}, {len(manifests)} objects")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
