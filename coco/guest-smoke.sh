#!/usr/bin/env bash
set -euo pipefail
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
ns=learn-openshell-smoke
k3s kubectl delete namespace "$ns" --ignore-not-found --wait=true --timeout=180s >/dev/null
k3s kubectl create namespace "$ns" --dry-run=client -o yaml | k3s kubectl apply -f -
trap 'k3s kubectl delete namespace "$ns" --wait=true --timeout=180s >/dev/null 2>&1 || true' EXIT

cat <<EOF | k3s kubectl -n "$ns" apply -f -
apiVersion: v1
kind: Pod
metadata:
  name: kata-smoke
spec:
  runtimeClassName: kata-qemu-coco-dev
  containers:
    - name: shell
      image: docker.io/library/busybox:1.36.1
      command: ["sh", "-c", "sleep 3600"]
EOF
k3s kubectl -n "$ns" wait --for=condition=Ready pod/kata-smoke --timeout=600s || {
  k3s kubectl -n "$ns" describe pod kata-smoke
  exit 1
}
k3s kubectl -n "$ns" exec kata-smoke -- uname -a
test "$(k3s kubectl -n "$ns" get pod kata-smoke -o jsonpath='{.spec.runtimeClassName}')" = kata-qemu-coco-dev
pgrep -f '^/opt/kata/bin/qemu-system-x86_64' >/dev/null
echo 'Kata QEMU process found on the K3s node.'

cat <<EOF | k3s kubectl -n "$ns" apply -f -
apiVersion: v1
kind: Pod
metadata:
  name: net-server
spec:
  containers:
    - name: httpd
      image: docker.io/library/busybox:1.36.1
      command: ["sh", "-c", "mkdir -p /www; echo ok > /www/index.html; httpd -f -p 8080 -h /www"]
---
apiVersion: v1
kind: Pod
metadata:
  name: net-client
  labels:
    role: net-client
spec:
  containers:
    - name: shell
      image: docker.io/library/busybox:1.36.1
      command: ["sh", "-c", "sleep 3600"]
EOF
k3s kubectl -n "$ns" wait --for=condition=Ready pod/net-server pod/net-client --timeout=300s
server_ip=$(k3s kubectl -n "$ns" get pod net-server -o jsonpath='{.status.podIP}')
k3s kubectl -n "$ns" exec net-client -- wget -q -T 5 -O /dev/null "http://${server_ip}:8080/"
cat <<EOF | k3s kubectl -n "$ns" apply -f -
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: deny-client-egress
spec:
  podSelector:
    matchLabels:
      role: net-client
  policyTypes: [Egress]
  egress: []
EOF
sleep 5
if k3s kubectl -n "$ns" exec net-client -- wget -q -T 5 -O /dev/null "http://${server_ip}:8080/"; then
  echo 'FAIL: NetworkPolicy did not block egress' >&2
  exit 1
fi
k3s kubectl -n "$ns" exec net-server -- wget -q -T 5 -O /dev/null http://127.0.0.1:8080/
echo 'PASS: Kata QEMU pod booted and K3s NetworkPolicy blocked egress.'
