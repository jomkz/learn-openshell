#!/usr/bin/env bash
set -euo pipefail
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
AGENT_SANDBOX_VERSION=v1.0.3
OPENSHELL_VERSION=0.1.7

k3s kubectl apply -f "https://github.com/kubernetes-sigs/agent-sandbox/releases/download/${AGENT_SANDBOX_VERSION}/sandbox.yaml"
k3s kubectl wait --for=condition=Established crd/sandboxes.agents.x-k8s.io --timeout=120s
k3s kubectl -n agent-sandbox-system rollout status deployment/agent-sandbox-controller --timeout=300s

helm upgrade --install openshell oci://ghcr.io/nvidia/openshell/helm-chart \
  --version "$OPENSHELL_VERSION" --namespace openshell --create-namespace \
  --values /tmp/learn-openshell/openshell-values.yaml \
  --post-renderer /tmp/learn-openshell/post-render.py --wait --timeout 15m
k3s kubectl -n openshell rollout status deployment/openshell-supervisor --timeout=600s

cat >/etc/systemd/system/learn-openshell-forward.service <<'EOF'
[Unit]
Description=Local OpenShell gateway port forward
After=k3s.service
Requires=k3s.service
[Service]
ExecStart=/usr/local/bin/k3s kubectl -n openshell port-forward --address 0.0.0.0 svc/openshell 17672:8080
Restart=always
RestartSec=3
Environment=KUBECONFIG=/etc/rancher/k3s/k3s.yaml
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now learn-openshell-forward.service

test "$(k3s kubectl -n openshell get deployment openshell-supervisor -o jsonpath='{.spec.template.spec.runtimeClassName}')" = kata-qemu-coco-dev
k3s kubectl -n openshell get pods -o wide
echo 'OpenShell gateway and Kata supervisor installed.'
