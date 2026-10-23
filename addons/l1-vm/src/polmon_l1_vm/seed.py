"""Offline NoCloud seed; only declared lab addresses/services are generated."""

import os
import re
import shutil
import tempfile
from pathlib import Path

import yaml

from polmon.backends.namespace.runner import CommandRunner
from polmon.topology.models import Node, Topology
from polmon_l1_vm.images import VMError

# Метка тома, по которой cloud-init находит источник NoCloud.
SEED_VOLUME_ID = "cidata"


def seed_documents(node: Node, topology: Topology) -> dict[str, str]:
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
    user = {
        "hostname": node.id,
        "manage_etc_hosts": True,
        "package_update": False,
        "package_upgrade": False,
        "write_files": [
            {
                "path": "/var/www/polmon/index.html",
                "content": f"POLMON {node.id} {node.uuid}\n",
                "permissions": "0644",
            }
        ],
        "runcmd": commands,
    }
    return {
        "meta-data": yaml.safe_dump({"instance-id": str(node.uuid), "local-hostname": node.id}),
        "network-config": yaml.safe_dump({"version": 1, "config": config}),
        "user-data": "#cloud-config\n" + yaml.safe_dump(user),
    }


def create_seed(directory: Path, node: Node, topology: Topology, runner: CommandRunner) -> Path:
    """Собирает ISO-образ NoCloud для одного узла; существующий файл не перезаписывается."""
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,31}", node.id):
        raise VMError("vm.node_id")
    path = directory / f"{node.id}-seed.iso"
    # Резервируем имя эксклюзивно: genisoimage не должен затереть чужой файл.
    os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
    staging = Path(tempfile.mkdtemp(prefix=".seed-", dir=directory))
    try:
        for name, content in seed_documents(node, topology).items():
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
