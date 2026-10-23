"""Offline NoCloud seed; only declared lab addresses/services are generated."""

import json
import os
import re
import shlex
import shutil
import tempfile
from pathlib import Path

import yaml

from polmon.backends.namespace.runner import CommandRunner
from polmon.topology.models import Node, Topology
from polmon_l1_vm.images import VMError

# Метка тома, по которой cloud-init находит источник NoCloud.
SEED_VOLUME_ID = "cidata"
PEER_REPORT_PATH = "/var/www/polmon/peers.txt"

# Проверка связи гость-гость: каждый гость сам запрашивает страницы соседей и публикует итог.
PEER_SCRIPT = """\
import http.client, json, os, sys, time
peers = json.loads(sys.argv[1])
out = sys.argv[2]
deadline = time.time() + 150
while True:
    lines = []
    for peer, uuid, ip, port in peers:
        try:
            c = http.client.HTTPConnection(ip, port, timeout=3)
            c.request("GET", "/")
            ok = c.getresponse().read(512).decode() == f"POLMON {peer} {uuid}\\n"
        except Exception:
            ok = False
        lines.append(f"{peer} {'ok' if ok else 'fail'}")
    with open(out + ".tmp", "w") as stream:
        stream.write("\\n".join(lines) + "\\n")
    os.replace(out + ".tmp", out)
    if all(line.endswith(" ok") for line in lines) or time.time() > deadline:
        break
    time.sleep(2)
"""


def seed_documents(node: Node, topology: Topology, *, peer_report: bool = False) -> dict[str, str]:
    networks = {network.id: network.ipv4_subnet for network in topology.networks}
    config = []
    for index, interface in enumerate(node.interfaces):
        config.append(
            {
                "type": "physical",
                "name": f"eth{index}",
                "mac_address": interface.mac,
                "subnets": [
                    {
                        "type": "static",
                        "address": f"{interface.ipv4}/{networks[interface.network].prefixlen}",
                    }
                ],
            }
        )
    # В BusyBox образа Alpine нет апплета httpd, а пакеты в гость не скачиваются:
    # используется python3 из базового образа (он нужен самому cloud-init).
    commands = []
    for service in node.services:
        server = (
            f"setsid python3 -m http.server {service.port} --bind {node.interfaces[0].ipv4}"
            " --directory /var/www/polmon </dev/null >/dev/null 2>&1 &"
        )
        commands.append(["sh", "-c", server])
    files = [
        {
            "path": "/var/www/polmon/index.html",
            "content": f"POLMON {node.id} {node.uuid}\n",
            "permissions": "0644",
        }
    ]
    mine = {interface.network for interface in node.interfaces}
    peers = [
        [other.id, str(other.uuid), str(other.interfaces[0].ipv4), other.services[0].port]
        for other in topology.nodes
        if peer_report
        and other.id != node.id
        and other.services
        and other.interfaces[0].network in mine
    ]
    if peers:
        files.append(
            {
                "path": "/usr/local/bin/polmon-peers.py",
                "content": PEER_SCRIPT,
                "permissions": "0755",
            }
        )
        report = (
            f"setsid python3 /usr/local/bin/polmon-peers.py {shlex.quote(json.dumps(peers))}"
            f" {PEER_REPORT_PATH} </dev/null >/dev/null 2>&1 &"
        )
        commands.append(["sh", "-c", report])
    user = {
        "hostname": node.id,
        "manage_etc_hosts": True,
        "package_update": False,
        "package_upgrade": False,
        "write_files": files,
        "runcmd": commands,
    }
    return {
        "meta-data": yaml.safe_dump({"instance-id": str(node.uuid), "local-hostname": node.id}),
        "network-config": yaml.safe_dump({"version": 1, "config": config}),
        "user-data": "#cloud-config\n" + yaml.safe_dump(user),
    }


def create_seed(
    directory: Path,
    node: Node,
    topology: Topology,
    runner: CommandRunner,
    *,
    peer_report: bool = False,
) -> Path:
    """Собирает ISO-образ NoCloud для одного узла; существующий файл не перезаписывается."""
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,31}", node.id):
        raise VMError("vm.node_id")
    path = directory / f"{node.id}-seed.iso"
    # Резервируем имя эксклюзивно: genisoimage не должен затереть чужой файл.
    os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
    staging = Path(tempfile.mkdtemp(prefix=".seed-", dir=directory))
    try:
        for name, content in seed_documents(node, topology, peer_report=peer_report).items():
            (staging / name).write_text(content, encoding="utf-8")
        runner.run(
            [
                "genisoimage",
                "-quiet",
                "-output",
                str(path),
                "-volid",
                SEED_VOLUME_ID,
                "-joliet",
                "-rock",
                str(staging),
            ],
            timeout=30,
        )
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return path
