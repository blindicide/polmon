"""Declarative topology models and YAML serialization."""

from polmon.topology.allocation import (
    LAB_MAC_PREFIX,
    migrate_to_lab_profile,
    next_free_host,
    next_free_mac,
    next_free_subnet,
)
from polmon.topology.io import dump_topology, load_topology, parse_topology
from polmon.topology.models import Topology

__all__ = [
    "LAB_MAC_PREFIX",
    "Topology",
    "dump_topology",
    "load_topology",
    "migrate_to_lab_profile",
    "next_free_host",
    "next_free_mac",
    "next_free_subnet",
    "parse_topology",
]
