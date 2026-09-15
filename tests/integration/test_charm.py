#!/usr/bin/env python3
# Copyright 2025 marc
# See LICENSE file for licensing details.

import logging
from pathlib import Path

import jubilant
import pytest
from helpers import (
    APP_NAME,
    CONNECT_APP,
    CONNECT_CHANNEL,
    IMAGE_RESOURCE_KEY,
    IMAGE_URI,
    KAFKA_APP,
    KAFKA_CHANNEL,
    KARAPACE_APP,
    KARAPACE_CHANNEL,
    SECRET_KEY,
    TLS_APP,
    TLS_CHANNEL,
    TRAEFIK_APP,
    TRAEFIK_CHANNEL,
    all_active_idle,
    assert_login,
    get_secret_by_label,
    set_password,
)

logger = logging.getLogger(__name__)


@pytest.fixture
def apps() -> list[str]:
    """Return list of Kafka ecosystem apps."""
    return [APP_NAME, CONNECT_APP, KAFKA_APP, KARAPACE_APP]


def test_build_and_deploy(juju: jubilant.Juju, ui_charm: Path, tls_enabled: bool, apps: list[str]):
    """Build the charm-under-test and deploy it together with related charms.

    Assert on the unit status before any relations/configurations take place.
    """
    juju.deploy(
        KAFKA_APP,
        app=KAFKA_APP,
        trust=True,
        channel=KAFKA_CHANNEL,
        config={"roles": "broker,controller"},
    )
    juju.deploy(CONNECT_APP, app=CONNECT_APP, trust=True, channel=CONNECT_CHANNEL)
    juju.deploy(KARAPACE_APP, app=KARAPACE_APP, trust=True, channel=KARAPACE_CHANNEL)
    juju.deploy(ui_charm, app=APP_NAME, trust=True, resources={IMAGE_RESOURCE_KEY: IMAGE_URI})
    juju.deploy(TLS_APP, app=TLS_APP, channel=TLS_CHANNEL, trust=True)
    juju.deploy(TRAEFIK_APP, app=TRAEFIK_APP, trust=True, channel=TRAEFIK_CHANNEL)

    _apps = apps + [TLS_APP, TRAEFIK_APP]
    juju.wait(
        lambda status: (
            jubilant.all_agents_idle(status, *_apps)
            and jubilant.all_blocked(status, APP_NAME, CONNECT_APP, KARAPACE_APP)
            and jubilant.all_active(status, KAFKA_APP, TLS_APP, TRAEFIK_APP)
        ),
        delay=3,
        timeout=1200,
        successes=10,
    )

    status = juju.status()
    assert status.apps[APP_NAME].app_status.current == "blocked"
    assert status.apps[CONNECT_APP].app_status.current == "blocked"
    assert status.apps[KARAPACE_APP].app_status.current == "blocked"
    assert status.apps[KAFKA_APP].app_status.current == "active"
    assert status.apps[TRAEFIK_APP].app_status.current == "active"


def test_integrate(juju: jubilant.Juju, tls_enabled: bool, apps: list[str]):
    # Activate Traefik TLS
    juju.integrate(TLS_APP, f"{TRAEFIK_APP}:certificates")

    juju.wait(
        lambda status: all_active_idle(status, TLS_APP, TRAEFIK_APP),
        delay=3,
        timeout=900,
        successes=10,
    )

    # integrate non-UI apps with Kafka
    juju.integrate(CONNECT_APP, KAFKA_APP)
    juju.integrate(KARAPACE_APP, KAFKA_APP)

    juju.wait(
        lambda status: all_active_idle(status, CONNECT_APP, KAFKA_APP, KARAPACE_APP),
        delay=3,
        timeout=900,
        successes=10,
    )

    # Integrate TLS with kafka apps in TLS mode
    if tls_enabled:
        for app in apps:
            juju.integrate(TLS_APP, f"{app}:certificates")

    juju.wait(
        lambda status: all_active_idle(status, CONNECT_APP, KAFKA_APP, KARAPACE_APP),
        delay=3,
        timeout=900,
        successes=10,
    )

    # Now integrate all apps with UI app.
    juju.integrate(APP_NAME, KAFKA_APP)
    juju.integrate(APP_NAME, CONNECT_APP)
    juju.integrate(APP_NAME, KARAPACE_APP)
    juju.integrate(APP_NAME, TRAEFIK_APP)

    juju.wait(
        lambda status: all_active_idle(status, *apps),
        delay=3,
        timeout=900,
        successes=10,
    )

    status = juju.status()
    for app in apps:
        assert status.apps[app].app_status.current == "active"


def test_ui(juju: jubilant.Juju):
    assert_login(juju=juju)


def test_password_rotation(juju: jubilant.Juju, apps: list[str]):
    secret_data = get_secret_by_label(juju, f"cluster.{APP_NAME}.app", owner=APP_NAME)
    old_password = secret_data.get(SECRET_KEY)

    new_password = "newStrongPa$$"
    set_password(juju, password=new_password)
    assert new_password != old_password

    juju.wait(
        lambda status: all_active_idle(status, *apps),
        delay=3,
        timeout=900,
        successes=10,
    )

    assert_login(juju=juju, password=new_password)
