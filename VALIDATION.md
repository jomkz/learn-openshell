# Local validation

The underlying lab was validated on November 10, 2026 with:

- Fedora Linux 44, x86_64; kernel `7.2.15-200.fc44.x86_64`.
- Podman `5.8.9`, rootless, cgroups v2; SELinux and Landlock present.
- OpenShell CLI and gateway `0.1.7`, downloaded from the release and checked
  against its SHA-256 manifests. The installer embeds those archive hashes.
- Gateway on loopback port 17671; local mutual TLS; no inference providers.

`./lab setup`, gateway configuration preflight, sandbox creation, and the full
`./lab demo` succeeded. Observed results:

| Check | Result |
| --- | --- |
| Write/read `/sandbox/hello.txt` | `hello` |
| Read fake secret through OpenShell | Python `PermissionError` |
| Read same file in an ordinary container | Fake secret readable |
| GET with no network rule | curl failed; supervisor logged `policy_dns_ineligible` and `transparent_tcp_policy_denied` |
| Apply read-only rule | Policy version 2 became effective without sandbox restart |
| GET after policy change | Successful GitHub `/zen` response |
| POST after policy change | JSON `policy_denied`, `layer=l7`, `method=POST`, `path=/zen` |
| Workload container inspection | `network=none`, `privileged=false`, `user=1000:1000` |
| Supervisor container inspection | `network=host`, `privileged=false`, `user=1000:1000` |

Runtime image digests observed through Podman:

```text
ghcr.io/nvidia/openshell/sandbox:0.1.7
sha256:b3a88bdb6c10bcce65fdeb6ec57249c1edcf7c0e6b51112bcbeaa4e85a190cc6

ghcr.io/nvidia/openshell/supervisor:0.1.7
sha256:f3162f10118392c7529a00d371c385e50f70625fb13191e7f15c2d975cf16009
```

After validation, `./lab delete` removed the sandbox and both running containers;
the gateway was stopped. A fresh checkout requires `./lab setup`, followed by
`./lab gateway` and the exercises described in the README.

The project and runtime resources were subsequently named `learn-openshell`.
Shell syntax, configuration consistency, documentation links, and public-file
content were checked after that rename; the full runtime exercise was not repeated.

These checks exercise real OpenShell processes. They do not establish resistance
to a kernel exploit, hardware memory confidentiality, attestation, protected
provider credential release, or compatibility with a Kubernetes deployment.

## Kata / CoCo non-TEE path

The optional VM path was validated on the same x86_64 host on November 10,
2026. It used Ubuntu 24.04 cloud image, K3s v1.35.9+k3s1, CoCo chart v0.23.0
(OCI digest `sha256:b6e12a2a8f310155c38a969bce7d58df86f8eef7098a0775ae9458ee63344686`),
Agent Sandbox v1.0.3, and OpenShell chart v0.1.7 (OCI digest
`sha256:3e5998c749390a6be3a4f553e52e488b6f692e19be7b8bf681a26285d1e18901`).

`./lab coco doctor`, `up`, `smoke`, `openshell`, and `demo` succeeded. Observed
results:

| Check | Result |
| --- | --- |
| Kata smoke pod | Ready with `kata-qemu-coco-dev`; `uname` showed Kata guest kernel `6.18.35`; QEMU process found on K3s node |
| K3s NetworkPolicy | Client HTTP request succeeded before egress deny, failed afterward; server stayed reachable locally |
| Supervisor placement | OpenShell supervisor pod Running with `kata-qemu-coco-dev` and QEMU process; gateway and agent pods used default runtime |
| OpenShell filesystem | Fake secret read denied; workspace write allowed |
| OpenShell network | GitHub GET denied with log evidence, then succeeded after live read-only rule; POST returned `policy_denied` |
| Supervisor restart | Deployment rolled from one Kata pod to another; agent reconnected and an approved GET succeeded afterward |

The VM was then stopped and restarted. Repeating `up` and `openshell`
succeeded with the existing disk, chart releases, and CLI gateway registration.
The validation sandbox was deleted and the VM was stopped; `.local/coco/`
remains for a fresh demo run.

These checks establish development Kata VM placement and policy behavior on
this host. They do not establish TEE confidentiality or hardware attestation.
