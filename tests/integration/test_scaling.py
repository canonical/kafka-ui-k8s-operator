#!/usr/bin/env python3
# Copyright 2025 marc
# See LICENSE file for licensing details.

import logging
import random
import time
from pathlib import Path

import jubilant
import requests
from helpers import (
    APP_NAME,
    IMAGE_RESOURCE_KEY,
    IMAGE_URI,
    INGRESS_REL,
    KAFKA_APP,
    KAFKA_CHANNEL,
    ROUTE_REL,
    SECRET_KEY,
    TLS_APP,
    TLS_CHANNEL,
    TRAEFIK_APP,
    TRAEFIK_CHANNEL,
    all_active_idle,
    get_secret_by_label,
)
from tenacity import Retrying, stop_after_attempt, wait_fixed

logger = logging.getLogger(__name__)


def _assert_login(juju: jubilant.Juju):
    status = juju.status()
    unit = next(iter(status.apps[APP_NAME].units.keys()))
    show_unit = juju.show_unit(unit)
    match = [rel for rel in show_unit.relation_info if rel.endpoint == "traefik-route"]
    if not match:
        raise Exception("No traefik-route relation found!")

    route_rel_data = match[0].app_data
    base_url = f"{route_rel_data['scheme']}://{route_rel_data['external_host']}"
    url = f"{base_url}/{juju.model}-{APP_NAME}"

    secret_data = get_secret_by_label(juju, label=f"cluster.{APP_NAME}.app", owner=APP_NAME)
    password = secret_data.get(SECRET_KEY)

    if not password:
        raise Exception("Can't fetch the admin user's password.")

    login_resp = requests.post(
        f"{url}/login",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={"username": "admin", "password": password},
        verify=False,
    )
    assert login_resp.status_code == 200
    # Successful login would lead to a redirect
    assert len(login_resp.history) > 0

    cookies = login_resp.history[0].cookies
    clusters_resp = requests.get(
        f"{url}/api/clusters",
        headers={"Content-Type": "application/json"},
        cookies=cookies,
        verify=False,
    )

    clusters_json = clusters_resp.json()
    logger.info(f"{clusters_json=}")
    assert len(clusters_json) > 0
    assert clusters_json[0].get("status") == "online"


def test_deploy_ui_and_kafka_active(juju: jubilant.Juju, ui_charm: Path):
    juju.deploy(
        KAFKA_APP,
        app=KAFKA_APP,
        trust=True,
        channel=KAFKA_CHANNEL,
        config={"roles": "broker,controller"},
    )
    juju.deploy(ui_charm, app=APP_NAME, trust=True, resources={IMAGE_RESOURCE_KEY: IMAGE_URI})
    juju.deploy(TLS_APP, app=TLS_APP, channel=TLS_CHANNEL, trust=True)
    juju.deploy(TRAEFIK_APP, app=TRAEFIK_APP, trust=True, channel=TRAEFIK_CHANNEL)

    juju.integrate(TLS_APP, f"{TRAEFIK_APP}:certificates")
    juju.integrate(APP_NAME, KAFKA_APP)
    juju.integrate(APP_NAME, f"{TRAEFIK_APP}:{INGRESS_REL}")

    juju.wait(
        lambda status: all_active_idle(status, KAFKA_APP, APP_NAME, TLS_APP),
        delay=3,
        timeout=1200,
        successes=10,
    )


def test_scale_with_no_route_rel(juju: jubilant.Juju):
    juju.add_unit(APP_NAME, num_units=2)
    time.sleep(30)

    juju.wait(
        lambda status: jubilant.all_agents_idle(status, APP_NAME, KAFKA_APP),
        delay=3,
        timeout=900,
        successes=10,
    )

    status = juju.status()
    # missing traefik-route relation should lead to blocked status
    assert status.apps[APP_NAME].app_status.current == "blocked"


def test_integrate_traefik_route(juju: jubilant.Juju):
    juju.integrate(APP_NAME, f"{TRAEFIK_APP}:{ROUTE_REL}")

    juju.wait(
        lambda status: jubilant.all_agents_idle(status, APP_NAME, KAFKA_APP),
        delay=3,
        timeout=900,
        successes=10,
    )

    status = juju.status()
    # both ingress & traefik-route relation should lead to blocked status
    assert status.apps[APP_NAME].app_status.current == "blocked"

    juju.remove_relation(APP_NAME, f"{TRAEFIK_APP}:{INGRESS_REL}")
    juju.wait(
        lambda status: all_active_idle(status, APP_NAME, KAFKA_APP),
        delay=3,
        timeout=900,
        successes=10,
    )

    time.sleep(30)
    _assert_login(juju=juju)


def test_min_units_availability(juju: jubilant.Juju):
    # suppress update-status waking up units
    juju.model_config({"update-status-hook-interval": "1000m"})

    status = juju.status()
    to_keep = random.choice(list(status.apps[APP_NAME].units))
    logger.info(f"Killing service on all units but {to_keep}")
    for unit in status.apps[APP_NAME].units:
        if unit != to_keep:
            juju.ssh(unit, "pebble stop kafka-ui", container="kafka-ui")

    time.sleep(30)
    for attempt in Retrying(stop=stop_after_attempt(3), wait=wait_fixed(10), reraise=True):
        with attempt:
            _assert_login(juju=juju)
