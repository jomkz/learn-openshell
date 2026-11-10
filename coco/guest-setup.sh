#!/usr/bin/env bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
K3S_VERSION=v1.35.9+k3s1
HELM_VERSION=v3.19.0
HELM_SHA256=a7f81ce08007091b86d8bd696eb4d86b8d0f2e1b9f6c714be62f82f96a594496
COCO_VERSION=0.23.0

apt-get update
apt-get install -y --no-install-recommends ca-certificates curl tar python3-yaml

if ! command -v k3s >/dev/null; then
  curl --fail --location --silent --show-error https://get.k3s.io -o /tmp/install-k3s.sh
  INSTALL_K3S_VERSION="$K3S_VERSION" INSTALL_K3S_EXEC='server --disable traefik --disable servicelb' sh /tmp/install-k3s.sh
fi
for attempt in $(seq 1 60); do
  if k3s kubectl get nodes --no-headers 2>/dev/null | grep -q .; then
    break
  fi
  sleep 2
done
k3s kubectl wait --for=condition=Ready node --all --timeout=300s

if ! command -v helm >/dev/null; then
  curl --fail --location --silent --show-error --retry 2 \
    "https://get.helm.sh/helm-${HELM_VERSION}-linux-amd64.tar.gz" -o /tmp/helm.tar.gz
  printf '%s  %s\n' "$HELM_SHA256" /tmp/helm.tar.gz | sha256sum --check -
  tar -xzf /tmp/helm.tar.gz -C /tmp linux-amd64/helm
  install -m 755 /tmp/linux-amd64/helm /usr/local/bin/helm
fi

for attempt in $(seq 1 6); do
  if helm upgrade --install coco \
    oci://ghcr.io/confidential-containers/charts/confidential-containers \
    --version "$COCO_VERSION" --namespace coco-system --create-namespace \
    --values /tmp/learn-openshell/coco-values.yaml --wait --timeout 15m; then
    break
  fi
  if (( attempt == 6 )); then
    echo 'CoCo Helm installation failed after retries' >&2
    exit 1
  fi
  echo "K3s may still be restarting its Kata runtime; retrying Helm ($attempt/6)..." >&2
  sleep 10
done
k3s kubectl get runtimeclass kata-qemu-coco-dev
kata_classes=$(k3s kubectl get runtimeclass -o jsonpath='{.items[*].metadata.name}' | tr ' ' '\n' | grep '^kata-' || true)
test "$kata_classes" = kata-qemu-coco-dev || {
  echo "Unexpected Kata RuntimeClasses: $kata_classes" >&2
  exit 1
}
k3s kubectl -n coco-system rollout status daemonset/kata-as-coco-runtime --timeout=600s || {
  k3s kubectl -n coco-system get pods -o wide
  exit 1
}
echo 'K3s and CoCo development RuntimeClass are installed.'
