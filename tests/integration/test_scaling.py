#!/usr/bin/env python3
# Copyright 2025 marc
# See LICENSE file for licensing details.

import logging
import random
import time
from pathlib import Path

import jubilant
from helpers import (
    APP_NAME,
    IMAGE_RESOURCE_KEY,
    IMAGE_URI,
    KAFKA_APP,
    KAFKA_CHANNEL,
    TLS_APP,
    TLS_CHANNEL,
    TRAEFIK_APP,
    TRAEFIK_CHANNEL,
    all_active_idle,
    assert_login,
)
from tenacity import Retrying, stop_after_attempt, wait_fixed

logger = logging.getLogger(__name__)


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
    juju.integrate(APP_NAME, TRAEFIK_APP)

    juju.wait(
        lambda status: all_active_idle(status, KAFKA_APP, APP_NAME, TLS_APP),
        delay=3,
        timeout=1200,
        successes=10,
    )


def test_scale_out(juju: jubilant.Juju):
    juju.add_unit(APP_NAME, num_units=2)
    time.sleep(30)

    juju.wait(
        lambda status: jubilant.all_agents_idle(status, APP_NAME, KAFKA_APP),
        delay=3,
        timeout=900,
        successes=10,
    )

    status = juju.status()
    assert status.apps[APP_NAME].app_status.current == "active"

    # Wait for Traefik checks to settle
    time.sleep(90)
    assert_login(juju=juju)


def test_min_units_availability(juju: jubilant.Juju):
    # suppress update-status waking up units
    juju.model_config({"update-status-hook-interval": "1000m"})

    status = juju.status()
    to_keep = random.choice(list(status.apps[APP_NAME].units))
    logger.info(f"Killing service on all units but {to_keep}")
    for unit in status.apps[APP_NAME].units:
        if unit != to_keep:
            juju.ssh(unit, "pebble stop kafka-ui", container="kafka-ui")

    # Wait for Traefik checks to settle
    time.sleep(90)
    for attempt in Retrying(stop=stop_after_attempt(3), wait=wait_fixed(10), reraise=True):
        with attempt:
            assert_login(juju=juju)
