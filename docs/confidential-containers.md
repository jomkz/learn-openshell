# Exploring a confidential OpenShell supervisor

These notes describe a possible extension of `learn-openshell`, based on the
public OpenShell 0.1.7 source and Confidential Containers documentation. This
repository also includes a [Kata / CoCo non-TEE lab](coco-nontee.md). The
hardware confidential deployment discussed here has not been tested.

## Choose the boundary to protect

The supervisor evaluates policy and mediates credential-bearing requests.
Putting it in a confidential VM could protect that sensitive state from the
infrastructure hosting it. Putting only the agent in a confidential VM protects
a different component. Draw both boundaries before choosing a deployment.

An initial experiment can use shell commands and an ordinary external API,
as this lab does. A model server and GPU are not needed to explore supervisor
policy behavior. Hardware-backed confidentiality is a separate step requiring
an appropriate TEE and attestation configuration.

## Where the sensitive state lives

| Component | Local learning setup | Question for the cluster design |
| --- | --- | --- |
| Gateway | Host process; TLS, signing keys and database under `.local/` | Who can access its state and administer policy? |
| Supervisor | Separate rootless container | Which exact pod or Deployment must move into the confidential VM? |
| Sandbox and workload | Network-disabled container; no providers | Does the agent remain outside the supervisor's VM boundary? |
| Provider credentials | None configured | Where are originals, refresh tokens and runtime credentials stored? |
| Identity services | Not installed | Which services and credentials belong to the trusted computing base? |
| Trustee / attestation agent | Not installed | What evidence gates secret release, and who controls the policy? |
| Inference service | Not needed for curl exercises | What data is sent to the approved external endpoint? |

Do not equate encrypted supervisor memory with end-to-end secret protection.
If credentials are also readable in a normal gateway database or Kubernetes
Secret, those copies remain part of the threat model. If an untrusted host can
replace policy or the supervisor image and still obtain secrets, encryption
alone has not established the desired trust. CoCo's
[trust model](https://confidentialcontainers.org/docs/architecture/trust-model/trust-model/)
is the reference for evaluating those boundaries.

## A concrete deployment trap to investigate

The documented OpenShell Kubernetes option
`driver_config.kubernetes.pod.runtime_class_name` affects the sandbox workload.
It should not be presented as a switch that makes its separate supervisor
confidential. In the inspected 0.1.7 sources:

- The [dedicated supervisor pod builder](https://github.com/NVIDIA/OpenShell/blob/v0.1.7/crates/openshell-driver-kubernetes/src/sandbox_runtime.rs)
  constructs its own PodSpec without a RuntimeClass field.
- The [shared supervisor Deployment template](https://github.com/NVIDIA/OpenShell/blob/v0.1.7/deploy/helm/openshell/templates/supervisor.yaml)
  does not expose a supervisor RuntimeClass setting. The non-TEE lab sets it
  with a targeted Helm post-renderer and rejects missing or ambiguous matches.

This remains a configuration gap for deployments beyond the lab. A Helm
upgrade must continue to use the post-renderer, and any topology or version
change needs renewed placement checks.

The local driver uses a Unix socket. Kubernetes uses a network channel; verify
its authentication, NetworkPolicy enforcement, service reachability, readiness,
and reconnect behavior across the confidential VM boundary. Start by checking
the actual generated pod specs and `kubectl get runtimeclass`; do not assume a class
name implies that TDX/SNP or attestation is active.

## Evidence for evaluating the extension

1. Record exact OpenShell, Kubernetes, Kata Containers, and CoCo/Trustee
   versions. Verify their compatibility in the actual environment.
2. Show the supervisor and workload placement and identify the protected assets
   and the adversary (agent process, guest-kernel escape, or cluster administrator).
3. Reproduce the allowed/denied requests from this local lab on that deployment.
4. For an isolation-only phase, describe the VM boundary and explicitly state
   that hardware confidentiality has not been demonstrated.
5. For a confidential phase, capture hardware attestation and a successful
   secret release. Then change an expected measurement or policy and show that
   secret release is denied. Inspect host-side storage, logs, debug/exec paths,
   and gateway-held copies against the claimed threat model.

CPU-only supervisor confidentiality and confidential GPU inference are separate
experiments. Protecting the supervisor does not make a remote inference service
confidential, and a confidential model server does not by itself protect the
supervisor. Evaluate the assets and trust boundaries of each component.
