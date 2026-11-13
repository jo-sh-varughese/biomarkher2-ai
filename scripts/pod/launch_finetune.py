"""Run the HER2match fine-tune on a Runpod GPU pod, step by step, from this machine.

    set RUNPOD_API_KEY=...            (never stored in the repo or in the state file)
    python scripts/pod/launch_finetune.py create      # RTX 4090, community cloud
    python scripts/pod/launch_finetune.py upload      # code, replay patches, Run B checkpoint
    python scripts/pod/launch_finetune.py start       # runs scripts/pod/finetune_her2match.sh in the background
    python scripts/pod/launch_finetune.py status      # last log lines, spend so far
    python scripts/pod/launch_finetune.py fetch       # results -> artifacts/v2/ft_her2match/
    python scripts/pod/launch_finetune.py terminate   # delete the pod (ends ALL billing)

Uploads are built first with:  tar code -> dist/her2_code.tgz, replay subset -> dist/her2_replay.tgz.
The pod stops itself when the run ends (and after a hard time limit); `terminate` also deletes its disk.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "dist" / "pod_state.json"
KEY = Path.home() / ".ssh" / "runpod_her2"
# which pod job: finetune_her2match.sh (first attempt) or her2match_experiments.sh (profile + two fine-tunes)
SCRIPT = os.environ.get("POD_SCRIPT", "her2match_experiments.sh")
LOGNAME = {"finetune_her2match.sh": "finetune.log"}.get(SCRIPT, "experiments.log")
RESULTS = {"finetune_her2match.sh": "results_ft_her2match.tgz"}.get(SCRIPT, "results_experiments.tgz")
IMAGE = "runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04"
GPUS = ["NVIDIA GeForce RTX 4090", "NVIDIA GeForce RTX 3090", "NVIDIA RTX A5000", "NVIDIA A40",
        "NVIDIA RTX A6000", "NVIDIA L40S"]  # tried in this order (24-48 GB, ~$0.27-0.80/h)
if os.environ.get("POD_GPU_FIRST"):  # e.g. a type that worked last time
    GPUS = [os.environ["POD_GPU_FIRST"]] + [g for g in GPUS if g != os.environ["POD_GPU_FIRST"]]


def gql(query: str) -> dict:
    key = os.environ.get("RUNPOD_API_KEY")
    if not key:
        sys.exit("Set RUNPOD_API_KEY first.")
    req = urllib.request.Request("https://api.runpod.io/graphql", data=json.dumps({"query": query}).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}",
                                          "User-Agent": "her2-finetune-launcher"})
    with urllib.request.urlopen(req, timeout=60) as r:
        out = json.loads(r.read())
    if out.get("errors"):
        raise RuntimeError(out["errors"])
    return out["data"]


def state() -> dict:
    return json.loads(STATE.read_text()) if STATE.is_file() else {}


def save(s: dict) -> None:
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(s, indent=2))


def ssh_target() -> tuple[str, str]:
    pod = gql(f'query {{ pod(input: {{podId: "{state()["pod_id"]}"}}) {{ desiredStatus costPerHr runtime {{ uptimeInSeconds '
              f'ports {{ ip isIpPublic privatePort publicPort }} }} }} }}')["pod"]
    ports = (pod.get("runtime") or {}).get("ports") or []
    ssh = [p for p in ports if p["privatePort"] == 22 and p["isIpPublic"]]
    if not ssh:
        raise RuntimeError(f"SSH not ready yet (status {pod.get('desiredStatus')})")
    return ssh[0]["ip"], str(ssh[0]["publicPort"])


def ssh(cmd: str, check: bool = True) -> str:
    ip, port = ssh_target()
    r = subprocess.run(["ssh", "-i", str(KEY), "-p", port, "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=20",
                        f"root@{ip}", cmd], capture_output=True, text=True)
    if check and r.returncode:
        raise RuntimeError(r.stderr.strip() or r.stdout.strip())
    return r.stdout


def scp(src: str, dst: str) -> None:
    ip, port = ssh_target()
    src = src.replace("POD:", f"root@{ip}:")
    dst = dst.replace("POD:", f"root@{ip}:")
    subprocess.run(["scp", "-i", str(KEY), "-P", port, "-o", "StrictHostKeyChecking=no", src, dst], check=True)


def create() -> None:
    if state().get("pod_id"):
        sys.exit(f"A pod is already recorded: {state()['pod_id']} (terminate it first).")
    pub = (KEY.with_suffix(".pub")).read_text().strip()
    data, last = None, None
    for cloud in ("COMMUNITY", "SECURE"):
        for gpu in GPUS:
            try:
                data = gql(f'''mutation {{ podFindAndDeployOnDemand(input: {{
                    cloudType: {cloud}, gpuCount: 1, gpuTypeId: "{gpu}", name: "her2-ft-her2match",
                    imageName: "{IMAGE}", containerDiskInGb: 50, volumeInGb: 0, minVcpuCount: 6, minMemoryInGb: 24,
                    ports: "22/tcp", volumeMountPath: "/workspace",
                    env: [{{key: "PUBLIC_KEY", value: "{pub}"}}] }}) {{ id costPerHr machineId }} }}''')["podFindAndDeployOnDemand"]
                print(f"got {gpu} ({cloud.lower()})")
                break
            except RuntimeError as e:
                last = e
                print(f"  {gpu} ({cloud.lower()}): not available")
        if data:
            break
    if not data:
        sys.exit(f"No GPU available right now: {last}")
    save({"pod_id": data["id"], "cost_per_hr": data["costPerHr"], "created": time.time()})
    print(f"pod {data['id']} created at ${data['costPerHr']}/h; waiting for SSH ...")
    for _ in range(60):
        try:
            print("ssh ready:", ssh_target())
            return
        except RuntimeError:
            time.sleep(10)
    print("SSH still not ready; run `status` in a minute.")


def upload() -> None:
    for f in ("dist/her2_code.tgz", "dist/her2_replay.tgz"):
        print("uploading", f, flush=True)
        scp(str(ROOT / f), "POD:/workspace/")
    print("uploading run_b checkpoint", flush=True)
    scp(str(ROOT / "artifacts/v2/run_b/best.pt"), "POD:/workspace/run_b_best.pt")
    print(ssh("ls -la /workspace"))


def start() -> None:
    ssh("mkdir -p /workspace/her2 && cd /workspace/her2 && tar -xzf /workspace/her2_code.tgz --no-same-owner && "
        f"(setsid nohup bash scripts/pod/{SCRIPT} > /workspace/logs_start.txt 2>&1 < /dev/null &)")
    print("started")


def status() -> None:
    s = state()
    pod = gql(f'query {{ pod(input: {{podId: "{s["pod_id"]}"}}) {{ desiredStatus costPerHr runtime {{ uptimeInSeconds }} }} }}')["pod"]
    up = ((pod or {}).get("runtime") or {}).get("uptimeInSeconds") or 0
    hours = (time.time() - s["created"]) / 3600
    print(f"pod {s['pod_id']}: {pod and pod['desiredStatus']}, uptime {up / 60:.0f} min, "
          f"~${hours * float(s['cost_per_hr']):.2f} so far")
    try:
        print(ssh(f"tail -n 15 /workspace/logs/{LOGNAME}; ls /workspace/DONE 2>/dev/null", check=False))
    except RuntimeError as e:
        print("(no SSH:", e, ")")


def fetch() -> None:
    out = ROOT / "dist" / RESULTS
    scp(f"POD:/workspace/{RESULTS}", str(out))
    subprocess.run(["tar", "-xzf", str(out), "-C", str(ROOT / "artifacts" / "v2")], check=True)
    print(f"results unpacked into artifacts/v2/ from {out.name}")


def terminate() -> None:
    s = state()
    gql(f'mutation {{ podTerminate(input: {{podId: "{s["pod_id"]}"}}) }}')
    print(f"pod {s['pod_id']} terminated; ~${(time.time() - s['created']) / 3600 * float(s['cost_per_hr']):.2f} spent")
    STATE.unlink()


if __name__ == "__main__":
    {"create": create, "upload": upload, "start": start, "status": status, "fetch": fetch,
     "terminate": terminate}[sys.argv[1]]()
