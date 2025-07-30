#!/usr/bin/env python3
# Copyright 2025 marc
# See LICENSE file for licensing details.

import logging
import re
from pathlib import Path
from subprocess import PIPE, check_output

import jubilant
import yaml

from literals import CONTAINER

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./charmcraft.yaml").read_text())
APP_NAME = METADATA["name"]
CONNECT_APP = "kafka-connect-k8s"
CONNECT_CHANNEL = "latest/edge"
KAFKA_APP = "kafka-k8s"
KAFKA_CHANNEL = "4/edge"
KARAPACE_APP = "karapace-k8s"
KARAPACE_CHANNEL = "latest/edge"
TLS_APP = "self-signed-certificates"
TRAEFIK_APP = "traefik-k8s"
TRAEFIK_CHANNEL = "1.0/stable"

PROTO = "https"
SECRET_KEY = "admin-password"

IMAGE_RESOURCE_KEY = "kafka-ui-image"
IMAGE_URI = METADATA["resources"][IMAGE_RESOURCE_KEY]["upstream-source"]


def all_active_idle(status: jubilant.Status, *apps: str):
    """Check all units are in active|idle state."""
    return jubilant.all_agents_idle(status, *apps) and jubilant.all_active(status, *apps)


def get_secret_by_label(juju: jubilant.Juju, label: str, owner: str) -> dict[str, str]:
    secrets = [
        secret for secret in juju.secrets() if secret.owner == owner and secret.label == label
    ]

    if not secrets:
        return {}

    return juju.show_secret(secrets[0].uri, reveal=True).content


def get_unit_ipv4_address(model_full_name: str | None, unit_name: str) -> str | None:
    """Get unit's IPv4 address.

    This is a safer alternative for `juju.unit.get_public_address()`.
    This function is robust to network changes.
    """
    stdout = check_output(
        f"JUJU_MODEL={model_full_name} juju ssh --container {CONTAINER} {unit_name} hostname -i",
        stderr=PIPE,
        shell=True,
        universal_newlines=True,
    )
    ipv4_matches = re.findall(r"[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}", stdout)

    if ipv4_matches:
        return ipv4_matches[0]

    return None
