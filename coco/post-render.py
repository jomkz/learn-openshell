#!/usr/bin/env python3
"""Set the non-TEE Kata RuntimeClass on exactly one OpenShell supervisor."""

import sys

import yaml


def render(source):
    documents = [item for item in yaml.safe_load_all(source) if item is not None]
    matches = [
        item for item in documents
        if isinstance(item, dict)
        and item.get("kind") == "Deployment"
        and item.get("metadata", {}).get("labels", {}).get("app.kubernetes.io/component") == "supervisor"
    ]
    if len(matches) != 1:
        raise ValueError(f"expected one supervisor Deployment, found {len(matches)}")
    spec = matches[0]["spec"]["template"]["spec"]
    current = spec.get("runtimeClassName")
    if current not in (None, "kata-qemu-coco-dev"):
        raise ValueError(f"unexpected supervisor RuntimeClass: {current}")
    spec["runtimeClassName"] = "kata-qemu-coco-dev"
    return yaml.safe_dump_all(documents, sort_keys=False)


if __name__ == "__main__":
    try:
        sys.stdout.write(render(sys.stdin.read()))
    except (ValueError, KeyError, yaml.YAMLError) as error:
        print(f"OpenShell supervisor post-render failed: {error}", file=sys.stderr)
        sys.exit(1)
