"""Offline NoCloud seed; only declared lab addresses/services are generated."""

from pathlib import Path

import yaml

from polmon.backends.namespace.runner import CommandRunner
from polmon.topology.models import Node, Topology


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
    # Alpine's BusyBox HTTP server needs no guest package acquisition or credentials.
    commands = []
    for service in node.services:
        commands.append(
            [
                "busybox",
                "httpd",
                "-p",
                f"{node.interfaces[0].ipv4}:{service.port}",
                "-h",
                "/var/www/polmon",
            ]
        )
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
    from polmon_l1_vm.images import VMError

    raise VMError("vm.scaffold_only")
