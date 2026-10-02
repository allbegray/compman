"""Read-only view of a compose configuration, for reporting.

Only what an operator needs in a notification: which named volumes the stack
mounts, in which service, at which container path. ``compose ps`` cannot supply
this -- its ``Mounts`` column is truncated to an ellipsis in
``--format json`` output -- so the compose files themselves are the source.

Later files override earlier ones for the same service, matching how Docker
Compose merges an override file on top of its base.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import yaml

VOLUMES_KEY = "volumes"
SERVICES_KEY = "services"


@dataclass(frozen=True)
class VolumeMount:
    """One named-volume mount declared by a service."""

    declared: str
    service: str
    target: str

    @property
    def label(self) -> str:
        return f"{self.service}:{self.target}"


def _load_documents(files: Sequence[Path]) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for path in files:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
        except (OSError, yaml.YAMLError):
            continue
        if isinstance(data, dict):
            documents.append(data)
    return documents


def _merge(target: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge(target[key], value)
        else:
            target[key] = value
    return target


def _merged_documents(files: Sequence[Path]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for document in _load_documents(files):
        _merge(merged, document)
    return merged


def _declared_volumes(documents: dict[str, Any]) -> set[str]:
    block = documents.get(VOLUMES_KEY)
    return set(block) if isinstance(block, dict) else set()


def _mount_from_entry(entry: Any, service: str, declared: set[str]) -> VolumeMount | None:
    """Normalize one entry of a service's ``volumes`` list."""
    if isinstance(entry, dict):
        if entry.get("type") != "volume":
            return None
        source = entry.get("source")
        target = entry.get("target")
        if not isinstance(source, str) or not isinstance(target, str):
            return None
        return VolumeMount(source, service, target) if source in declared else None
    if not isinstance(entry, str):
        return None
    # Short syntax: "name:/container/path[:ro]". A single path is an anonymous
    # volume and a host path is a bind mount; neither has a declared name.
    parts = entry.split(":")
    if len(parts) < 2 or parts[0] not in declared:
        return None
    return VolumeMount(parts[0], service, parts[1])


def read_volume_mounts(files: Sequence[Path]) -> tuple[VolumeMount, ...]:
    """Return every distinct named-volume mount declared across ``files``.

    One entry per (volume, service, target) so a volume shared by two services
    reports both mount points; results keep compose declaration order.
    """
    documents = _merged_documents(files)
    declared = _declared_volumes(documents)
    if not declared:
        return ()
    services = documents.get(SERVICES_KEY)
    if not isinstance(services, dict):
        return ()

    mounts: list[VolumeMount] = []
    seen: set[tuple[str, str, str]] = set()
    for service, body in services.items():
        entries = body.get(VOLUMES_KEY) if isinstance(body, dict) else None
        if not isinstance(entries, list):
            continue
        for entry in entries:
            mount = _mount_from_entry(entry, str(service), declared)
            if mount is None:
                continue
            key = (mount.declared, mount.service, mount.target)
            if key in seen:
                continue
            seen.add(key)
            mounts.append(mount)
    return tuple(mounts)