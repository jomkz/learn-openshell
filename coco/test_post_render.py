#!/usr/bin/env python3
"""A chart drift check for the one Deployment we are allowed to mutate."""

import importlib.util
from pathlib import Path
import unittest

import yaml


spec = importlib.util.spec_from_file_location("post_render", Path(__file__).with_name("post-render.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PostRenderTest(unittest.TestCase):
    def deployment(self, component, runtime=None):
        pod = {"containers": [{"name": component, "image": "example"}]}
        if runtime:
            pod["runtimeClassName"] = runtime
        return {"apiVersion": "apps/v1", "kind": "Deployment",
                "metadata": {"name": component, "labels": {"app.kubernetes.io/component": component}},
                "spec": {"template": {"spec": pod}}}

    def test_only_supervisor_changes(self):
        source = yaml.safe_dump_all([self.deployment("gateway"), self.deployment("supervisor")])
        gateway, supervisor = yaml.safe_load_all(module.render(source))
        self.assertNotIn("runtimeClassName", gateway["spec"]["template"]["spec"])
        self.assertEqual(supervisor["spec"]["template"]["spec"]["runtimeClassName"], "kata-qemu-coco-dev")

    def test_missing_duplicate_or_conflicting_supervisor_fails(self):
        for items in ([self.deployment("gateway")],
                      [self.deployment("supervisor"), self.deployment("supervisor")],
                      [self.deployment("supervisor", "other-runtime")]):
            with self.subTest(items=items), self.assertRaises(ValueError):
                module.render(yaml.safe_dump_all(items))


if __name__ == "__main__":
    unittest.main()
