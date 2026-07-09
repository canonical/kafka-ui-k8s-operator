#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import json
import logging
import re
from pathlib import Path

import pytest
import requests
from helpers import (
    APP_NAME,
    IMAGE_RESOURCE_KEY,
    IMAGE_URI,
    KAFKA_APP,
    KAFKA_CHANNEL,
    TRAEFIK_APP,
    TRAEFIK_CHANNEL,
)
from oauth_tools import (
    access_application_login_page,
    click_on_sign_in_button_by_text,
    complete_auth_code_login,
    deploy_identity_bundle,
    get_cookies_from_browser_by_url,
)
from oauth_tools.external_idp import DexIdpService
from playwright.async_api._generated import BrowserContext, Page
from pytest_operator.plugin import OpsTest

pytest_plugins = ["oauth_tools.fixtures"]

logger = logging.getLogger(__name__)


TRAEFIK_UI_APP = "traefik-ui"
TEST_EMAIL = "admin@example.com"


@pytest.fixture(scope="module", autouse=True)
def _require_tls(request: pytest.FixtureRequest):
    """Skip the whole module unless TLS is enabled."""
    if not request.config.getoption("--tls"):
        pytest.skip("OAuth login requires TLS; run with --tls")


async def test_build_and_deploy(
    ops_test: OpsTest,
    ui_charm: Path,
    hydra_app_name: str,
    public_traefik_app_name: str,
    self_signed_certificates_app_name: str,
    ext_idp_service: DexIdpService,
):
    # `ext_idp_service` will deploy an external idp to use for
    # logging in and manage its lifecycle

    # Deploy the identity bundle
    await deploy_identity_bundle(
        ops_test=ops_test, bundle_channel="0.1/edge", ext_idp_service=ext_idp_service
    )

    await asyncio.gather(
        ops_test.model.deploy(
            KAFKA_APP,
            application_name=KAFKA_APP,
            channel=KAFKA_CHANNEL,
            trust=True,
            config={"roles": "broker,controller"},
        ),
        ops_test.model.deploy(
            ui_charm,
            application_name=APP_NAME,
            trust=True,
            resources={IMAGE_RESOURCE_KEY: IMAGE_URI},
            config={"roles-mapping": f'{{"{TEST_EMAIL}": "admin"}}'},
        ),
        ops_test.model.deploy(
            TRAEFIK_APP,
            application_name=TRAEFIK_UI_APP,
            channel=TRAEFIK_CHANNEL,
            trust=True,
        ),
    )

    await ops_test.model.wait_for_idle(
        apps=[KAFKA_APP],
        status="active",
        raise_on_blocked=False,
        raise_on_error=False,
        timeout=1200,
    )

    await ops_test.model.integrate(APP_NAME, KAFKA_APP)
    await ops_test.model.integrate(f"{KAFKA_APP}:certificates", self_signed_certificates_app_name)
    await ops_test.model.integrate(f"{APP_NAME}:certificates", self_signed_certificates_app_name)

    await ops_test.model.integrate(
        f"{TRAEFIK_UI_APP}:certificates", self_signed_certificates_app_name
    )
    await ops_test.model.integrate(f"{APP_NAME}:ingress", TRAEFIK_UI_APP)

    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, KAFKA_APP, TRAEFIK_UI_APP],
        status="active",
        raise_on_blocked=False,
        raise_on_error=False,
        timeout=1200,
    )

    await ops_test.model.integrate(f"{APP_NAME}:oauth", hydra_app_name)
    await ops_test.model.integrate(f"{APP_NAME}:oauth-ca", self_signed_certificates_app_name)

    await ops_test.model.wait_for_idle(
        status="active",
        raise_on_blocked=False,
        raise_on_error=False,
        timeout=1000,
    )


async def test_oauth_login_with_identity_bundle(
    ops_test: OpsTest,
    page: Page,
    context: BrowserContext,
    ext_idp_service: DexIdpService,
) -> None:
    # Fetch the Kafka UI's URL
    action = (
        await ops_test.model.applications[TRAEFIK_UI_APP]
        .units[0]
        .run_action("show-proxied-endpoints")
    )
    result = await action.wait()
    proxied_endpoints = json.loads(result.results["proxied-endpoints"])
    url = proxied_endpoints.get(APP_NAME, {}).get("url")
    if not url:
        raise Exception("Can't retrieve proxied endpoint for Kafka UI.")

    await access_application_login_page(
        page=page, url=url, redirect_login_url=f"{url}/auth/openid/login"
    )
    await click_on_sign_in_button_by_text(page=page, text="Log in with iam")
    await complete_auth_code_login(page=page, ops_test=ops_test, ext_idp_service=ext_idp_service)

    cookies = await get_cookies_from_browser_by_url(context, url)
    session = requests.Session()
    for cookie in cookies:
        session.cookies.set(cookie["name"], cookie["value"])

    clusters_resp = session.get(f"{url}/api/clusters", verify=False)
    clusters_json = clusters_resp.json()
    logger.info(f"{clusters_json=}")
    assert clusters_json
    assert clusters_json[0].get("status") == "online"
