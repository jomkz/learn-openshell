#!/usr/bin/env python3
"""Disposable QEMU/K3s/CoCo learning lab for a non-TEE OpenShell supervisor."""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parent.parent
COCO = ROOT / "coco"
STATE = ROOT / ".local" / "coco"
IMAGE = "noble-server-cloudimg-amd64.img"
IMAGE_URL = f"https://cloud-images.ubuntu.com/noble/current/{IMAGE}"
IMAGE_SHA_URL = "https://cloud-images.ubuntu.com/noble/current/SHA256SUMS"
WORKLOAD_IMAGE = "localhost/learn-openshell-tools:0.1.7"
CLI_SHA256 = "5c1adfcae797eac9b2e8b9280c66c1f75e4e84d9e31ce6938c5b994314ef6098"
SSH_PORT = 22222
GATEWAY_PORT = 17672
SSH_KEY = STATE / "id_ed25519"
PID_FILE = STATE / "qemu.pid"
GATEWAY = "coco"
SANDBOX = "coco-learning"


def run(args, *, input_text=None, capture=False, check=True, env=None, timeout=None):
    result = subprocess.run(
        [str(arg) for arg in args], input=input_text, text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        check=False, env=env, timeout=timeout,
    )
    if check and result.returncode:
        if capture:
            print(result.stderr, file=sys.stderr)
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(map(str, args[:3]))}")
    return result


def need(*commands):
    missing = [name for name in commands if shutil.which(name) is None]
    if missing:
        raise RuntimeError("missing host commands: " + ", ".join(missing))


def doctor():
    if sys.platform != "linux" or os.uname().machine != "x86_64":
        raise RuntimeError("this VM recipe requires Linux x86_64")
    need("qemu-system-x86_64", "qemu-img", "genisoimage", "ssh", "ssh-keygen", "scp", "curl", "sha256sum", "podman")
    if not os.access("/dev/kvm", os.R_OK | os.W_OK):
        raise RuntimeError("/dev/kvm is not accessible; enable KVM and nested virtualization")
    nested = [Path("/sys/module/kvm_intel/parameters/nested"),
              Path("/sys/module/kvm_amd/parameters/nested")]
    if not any(path.exists() and path.read_text().strip().lower() in ("y", "1") for path in nested):
        raise RuntimeError("nested KVM is not enabled")
    for port in (SSH_PORT, GATEWAY_PORT):
        if not running():
            with socket.socket() as sock:
                try:
                    sock.bind(("127.0.0.1", port))
                except OSError as error:
                    raise RuntimeError(f"loopback port {port} is busy: {error}") from error
    print("Host checks passed: Linux x86_64, KVM, QEMU, SSH, Podman, and local ports.")


def pid():
    if not PID_FILE.exists():
        return None
    try:
        value = int(PID_FILE.read_text().strip())
        command = Path(f"/proc/{value}/cmdline").read_bytes().replace(b"\0", b" ")
        if b"qemu-system-x86_64" in command and str(STATE / "disk.qcow2").encode() in command:
            return value
    except (ValueError, OSError):
        pass
    return None


def running():
    return pid() is not None


def download_image():
    base = STATE / IMAGE
    sha_file = STATE / "SHA256SUMS"
    if base.exists() and sha_file.exists():
        expected = image_hash(sha_file)
        if hash_file(base) == expected:
            return base
    print("Downloading Ubuntu 24.04 cloud image (about 600 MB) and its SHA256SUMS...")
    run(["curl", "--fail", "--location", "--silent", "--show-error", "--retry", "3", IMAGE_SHA_URL, "-o", sha_file])
    run(["curl", "--fail", "--location", "--silent", "--show-error", "--retry", "3", IMAGE_URL, "-o", base])
    if hash_file(base) != image_hash(sha_file):
        base.unlink(missing_ok=True)
        raise RuntimeError("Ubuntu image checksum mismatch; retry if the 'current' image changed during download")
    return base


def image_hash(sha_file):
    for line in sha_file.read_text().splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == IMAGE:
            return parts[0]
    raise RuntimeError(f"{IMAGE} is absent from Ubuntu SHA256SUMS")


def hash_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ssh_args():
    return ["ssh", "-T", "-p", str(SSH_PORT), "-i", SSH_KEY,
            "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", f"UserKnownHostsFile={STATE / 'known_hosts'}",
            "ubuntu@127.0.0.1"]


def guest(args, *, capture=False, check=True, input_text=None, timeout=None):
    if not running():
        raise RuntimeError("VM is stopped; run ./lab coco up")
    return run(ssh_args() + args, capture=capture, check=check,
               input_text=input_text, timeout=timeout)


def guest_script(name):
    print(f"Running guest step: {name}", flush=True)
    return guest(["sudo", "bash", "-s"], input_text=(COCO / name).read_text())


def upload():
    guest(["mkdir", "-p", "/tmp/learn-openshell"])
    for name in ("coco-values.yaml", "openshell-values.yaml", "post-render.py"):
        run(["scp", "-P", str(SSH_PORT), "-i", SSH_KEY,
             "-o", "StrictHostKeyChecking=accept-new",
             "-o", f"UserKnownHostsFile={STATE / 'known_hosts'}",
             COCO / name, f"ubuntu@127.0.0.1:/tmp/learn-openshell/{name}"])
    guest(["chmod", "755", "/tmp/learn-openshell/post-render.py"])


def make_seed():
    if not SSH_KEY.exists():
        run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", SSH_KEY])
    public_key = SSH_KEY.with_suffix(".pub").read_text().strip()
    (STATE / "user-data").write_text(
        "#cloud-config\nusers:\n  - name: ubuntu\n    groups: [adm, sudo]\n"
        "    sudo: ALL=(ALL) NOPASSWD:ALL\n    shell: /bin/bash\n"
        "    lock_passwd: true\n    ssh_authorized_keys:\n"
        f"      - {public_key}\nssh_pwauth: false\n")
    (STATE / "meta-data").write_text("instance-id: learn-openshell-coco\nlocal-hostname: coco-lab\n")
    run(["genisoimage", "-quiet", "-output", STATE / "seed.iso", "-volid", "cidata",
         "-joliet", "-rock", STATE / "user-data", STATE / "meta-data"])


def wait_ssh(seconds=480):
    print("Waiting for Ubuntu cloud-init and SSH...", flush=True)
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not running():
            raise RuntimeError(f"QEMU exited; inspect {STATE / 'serial.log'}")
        result = guest(["true"], check=False, capture=True)
        if result.returncode == 0:
            guest(["cloud-init", "status", "--wait"], timeout=300)
            return
        time.sleep(5)
    raise RuntimeError(f"SSH timeout; inspect {STATE / 'serial.log'}")


def up():
    doctor()
    STATE.mkdir(parents=True, exist_ok=True)
    if not running():
        base = download_image()
        disk = STATE / "disk.qcow2"
        if not disk.exists():
            run(["qemu-img", "create", "-q", "-f", "qcow2", "-F", "qcow2", "-b", base, disk, "40G"])
        make_seed()
        run(["qemu-system-x86_64", "-enable-kvm", "-cpu", "host", "-machine", "q35",
             "-smp", "4", "-m", "8192", "-display", "none", "-serial", f"file:{STATE / 'serial.log'}",
             "-drive", f"file={disk},if=virtio,format=qcow2",
             "-drive", f"file={STATE / 'seed.iso'},media=cdrom,readonly=on",
             "-netdev", f"user,id=net0,hostfwd=tcp:127.0.0.1:{SSH_PORT}-:22,hostfwd=tcp:127.0.0.1:{GATEWAY_PORT}-:{GATEWAY_PORT}",
             "-device", "virtio-net-pci,netdev=net0", "-daemonize", "-pidfile", PID_FILE])
    wait_ssh()
    upload()
    guest_script("guest-setup.sh")
    print("CoCo VM ready. Run ./lab coco smoke, then ./lab coco openshell.")


def smoke():
    guest_script("guest-smoke.sh")
    (STATE / "smoke.ok").write_text("Kata QEMU pod and NetworkPolicy passed\n")


def install_cli():
    target = STATE / "bin" / "openshell"
    if target.exists():
        return target
    need("curl")
    target.parent.mkdir(parents=True, exist_ok=True)
    archive = STATE / "openshell-x86_64-unknown-linux-musl.tar.gz"
    run(["curl", "--fail", "--location", "--silent", "--show-error", "--retry", "2",
         "https://github.com/NVIDIA/OpenShell/releases/download/v0.1.7/openshell-x86_64-unknown-linux-musl.tar.gz",
         "-o", archive])
    if hash_file(archive) != CLI_SHA256:
        archive.unlink(missing_ok=True)
        raise RuntimeError("OpenShell CLI checksum mismatch")
    run(["tar", "-xzf", archive, "-C", target.parent, "openshell"])
    target.chmod(0o755)
    return target


def cli_env():
    env = os.environ.copy()
    for key in ("OPENSHELL_GATEWAY_ENDPOINT", "OPENSHELL_GATEWAY_INSECURE", "OPENSHELL_GATEWAY_CONFIG", "OPENSHELL_WORKSPACE"):
        env.pop(key, None)
    for label in ("config", "state", "data", "cache"):
        path = STATE / label
        path.mkdir(parents=True, exist_ok=True)
        env[f"XDG_{label.upper()}_HOME"] = str(path)
    env["OPENSHELL_TELEMETRY_ENABLED"] = "false"
    return env


def os_cli(*args, capture=False, check=True):
    return run([install_cli(), "--gateway", GATEWAY, *args], env=cli_env(),
               capture=capture, check=check)


def import_tools_image():
    need("podman")
    print("Building the same tools image used in the Podman lab...", flush=True)
    run(["podman", "build", "-t", WORKLOAD_IMAGE, "-f", ROOT / "Containerfile", ROOT])
    archive = STATE / "tools.tar"
    run(["podman", "save", "--format", "docker-archive", "-o", archive, WORKLOAD_IMAGE])
    try:
        run(["scp", "-P", str(SSH_PORT), "-i", SSH_KEY,
             "-o", "StrictHostKeyChecking=accept-new",
             "-o", f"UserKnownHostsFile={STATE / 'known_hosts'}",
             archive, "ubuntu@127.0.0.1:/tmp/learn-openshell/tools.tar"])
        guest(["sudo", "k3s", "ctr", "-n", "k8s.io", "images", "import", "/tmp/learn-openshell/tools.tar"])
        guest(["rm", "-f", "/tmp/learn-openshell/tools.tar"])
    finally:
        archive.unlink(missing_ok=True)


def setup_gateway_config():
    result = guest(["sudo", "k3s", "kubectl", "-n", "openshell", "get", "secret",
                    "openshell-client-tls", "-o", "json"], capture=True)
    data = json.loads(result.stdout)["data"]
    directory = STATE / "config" / "openshell" / "gateways" / GATEWAY / "mtls"
    directory.mkdir(parents=True, exist_ok=True)
    for key in ("ca.crt", "tls.crt", "tls.key"):
        path = directory / key
        path.write_bytes(base64.b64decode(data[key]))
        path.chmod(0o600)
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", GATEWAY_PORT), timeout=2):
                break
        except OSError:
            time.sleep(2)
    else:
        raise RuntimeError("gateway port-forward did not start")
    metadata = directory.parent / "metadata.json"
    endpoint = f"https://127.0.0.1:{GATEWAY_PORT}"
    if metadata.exists():
        saved = json.loads(metadata.read_text())
        if (saved.get("gateway_endpoint") != endpoint or saved.get("auth_mode") != "mtls" or
                saved.get("is_remote") is not False):
            raise RuntimeError("existing coco gateway registration differs from this lab's endpoint")
    else:
        run([install_cli(), "gateway", "add", endpoint,
             "--local", "--name", GATEWAY], env=cli_env())
    os_cli("status")


def openshell():
    if not (STATE / "smoke.ok").exists():
        raise RuntimeError("run ./lab coco smoke first to prove Kata boot and NetworkPolicy enforcement")
    upload()
    guest_script("guest-openshell.sh")
    import_tools_image()
    setup_gateway_config()
    inspect()
    print("OpenShell ready. Run ./lab coco demo.")


def remote(*args, capture=False, check=True):
    return os_cli("sandbox", "exec", SANDBOX, "--no-tty", "--no-login-shell",
                  "--timeout", "30", "--", *args, capture=capture, check=check)


def demo():
    if os_cli("sandbox", "get", SANDBOX, capture=True, check=False).returncode == 0:
        raise RuntimeError(f"{SANDBOX} already exists; run ./lab coco delete before repeating")
    os_cli("sandbox", "create", "--name", SANDBOX, "--from", WORKLOAD_IMAGE,
           "--policy", str(ROOT / "policy-deny.yaml"), "--no-auto-providers",
           "--detach", "--no-tty", "--", "sleep", "infinity")
    print("Checking workload placement and filesystem policy...", flush=True)
    inspect()
    remote("sh", "-c", "echo hello > /sandbox/hello.txt; cat /sandbox/hello.txt")
    remote("python3", "-c", "import pathlib; p=pathlib.Path('/opt/lab-private/example.txt');\n"
           "try: p.read_text()\nexcept PermissionError: print('PASS: fake secret denied')\n"
           "else: raise SystemExit('FAIL: fake secret readable')")
    if remote("curl", "-fsS", "--max-time", "15", "https://api.github.com/zen", check=False).returncode == 0:
        raise RuntimeError("expected default-deny, but GET succeeded")
    for _ in range(10):
        logs = os_cli("logs", SANDBOX, "--since", "5m", "--source", "sandbox", capture=True, check=False).stdout
        if "api.github.com" in logs and ("DENIED" in logs or "denied" in logs):
            break
        time.sleep(1)
    else:
        raise RuntimeError("GET failed without a matching policy-denial log")
    os_cli("policy", "update", SANDBOX, "--rule-name", "github_read", "--binary", "/usr/bin/curl",
           "--add-endpoint", "api.github.com:443:read-only:rest:enforce", "--wait")
    remote("curl", "-fsS", "--max-time", "20", "https://api.github.com/zen")
    print("Restarting the Kata supervisor and waiting for sandbox reconnection...", flush=True)
    guest(["sudo", "k3s", "kubectl", "-n", "openshell", "rollout", "restart", "deployment/openshell-supervisor"])
    guest(["sudo", "k3s", "kubectl", "-n", "openshell", "rollout", "status", "deployment/openshell-supervisor", "--timeout=600s"])
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        if remote("curl", "-fsS", "--max-time", "20", "https://api.github.com/zen", check=False).returncode == 0:
            break
        time.sleep(5)
    else:
        raise RuntimeError("sandbox did not reconnect after supervisor rollout")
    inspect()
    post = remote("curl", "-sS", "--max-time", "20", "-X", "POST", "https://api.github.com/zen", capture=True)
    print(post.stdout)
    if "policy_denied" not in post.stdout:
        raise RuntimeError("POST was not denied by the read-only policy")
    print("PASS: filesystem denial, network denial, live allow, supervisor restart, and POST denial.")


def inspect():
    result = guest(["sudo", "k3s", "kubectl", "-n", "openshell", "get", "pods", "-o", "json"], capture=True)
    pods = json.loads(result.stdout)["items"]
    supervisors = [pod for pod in pods if pod["metadata"].get("labels", {}).get("app.kubernetes.io/component") == "supervisor"]
    if len(supervisors) != 1:
        raise RuntimeError(f"expected one supervisor pod, found {len(supervisors)}")
    supervisor = supervisors[0]
    if supervisor["spec"].get("runtimeClassName") != "kata-qemu-coco-dev":
        raise RuntimeError("supervisor pod is not using kata-qemu-coco-dev")
    if supervisor["status"].get("phase") != "Running":
        raise RuntimeError("Kata supervisor pod is not Running")
    print(f"Supervisor: {supervisor['metadata']['name']} runtimeClass=kata-qemu-coco-dev phase={supervisor['status']['phase']}")
    for pod in pods:
        if pod is supervisor:
            continue
        if (pod["metadata"]["name"] == "openshell-0" or
                pod["metadata"]["name"].startswith("default--")) and pod["spec"].get("runtimeClassName"):
            raise RuntimeError(f"ordinary gateway or workload pod moved into {pod['spec']['runtimeClassName']}")
        print(f"Pod: {pod['metadata']['name']} runtimeClass={pod['spec'].get('runtimeClassName', 'default')} phase={pod['status']['phase']}")
    qemu = guest(["sudo", "pgrep", "-af", "qemu-system-x86_64"], capture=True, check=False)
    if qemu.returncode:
        raise RuntimeError("no Kata QEMU process found in the K3s VM")
    print("Kata QEMU process present on the K3s node.")


def down():
    process = pid()
    if process is None:
        print("VM is stopped.")
        return
    guest(["sudo", "poweroff"], check=False, capture=True)
    for _ in range(30):
        if not running():
            break
        time.sleep(1)
    if running():
        os.kill(process, signal.SIGTERM)
        for _ in range(10):
            if not running():
                break
            time.sleep(1)
    if running():
        raise RuntimeError("VM did not stop; leaving state intact")
    PID_FILE.unlink(missing_ok=True)
    print("VM stopped; disk and keys are retained.")


def main():
    parser = argparse.ArgumentParser(description="Kata / CoCo non-TEE OpenShell lab")
    parser.add_argument("command", choices=("doctor", "up", "smoke", "openshell", "demo", "inspect", "down", "destroy", "delete", "logs", "shell", "cli"))
    parser.add_argument("args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.command == "doctor":
        doctor()
    elif args.command == "up":
        up()
    elif args.command == "smoke":
        smoke()
    elif args.command == "openshell":
        openshell()
    elif args.command == "demo":
        demo()
    elif args.command == "inspect":
        inspect()
    elif args.command == "down":
        down()
    elif args.command == "destroy":
        down()
        shutil.rmtree(STATE, ignore_errors=True)
        print("Removed only this lab's .local/coco state.")
    elif args.command == "delete":
        os_cli("sandbox", "delete", SANDBOX)
    elif args.command == "logs":
        os_cli("logs", SANDBOX, "--since", "15m", "--source", "sandbox")
    elif args.command == "shell":
        os_cli("sandbox", "connect", SANDBOX)
    elif args.command == "cli":
        os_cli(*args.args)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.TimeoutExpired, KeyError, json.JSONDecodeError) as error:
        print(f"coco lab: {error}", file=sys.stderr)
        sys.exit(1)
