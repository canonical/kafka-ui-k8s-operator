#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manager for handling Kafka UI OAuth configuration."""

import logging
from typing import TYPE_CHECKING

from charms.certificate_transfer_interface.v1.certificate_transfer import (
    CertificateTransferRequires,
)
from charms.hydra.v0.oauth import ClientConfig, OAuthRequirer
from ops.framework import EventBase, Object

from literals import OAUTH_CA_REL, OAUTH_REL

if TYPE_CHECKING:
    from charm import KafkaUiCharm

logger = logging.getLogger(__name__)


class OAuthHandler(Object):
    """Handler for managing Kafka UI oauth relations."""

    def __init__(self, charm: "KafkaUiCharm") -> None:
        super().__init__(charm, "oauth")
        self.charm: "KafkaUiCharm" = charm

        client_config = ClientConfig(
            audience=["kafka"],
            redirect_uri=f"{self.charm.context.ingress_url}/login/oauth2/code/iam",
            scope="openid profile email phone offline address",
            grant_types=["authorization_code"],
            # token_endpoint_auth_method="client_secret_post",
        )
        self.oauth = OAuthRequirer(self.charm, client_config, relation_name=OAUTH_REL)
        self.cert_transfer = CertificateTransferRequires(self.charm, OAUTH_CA_REL)

        self.framework.observe(
            self.charm.on[OAUTH_REL].relation_changed, self._on_oauth_relation_changed
        )
        self.framework.observe(
            self.charm.on[OAUTH_REL].relation_broken, self._on_oauth_relation_broken
        )
        self.framework.observe(
            self.cert_transfer.on.certificate_set_updated, self._on_oauth_ca_changed
        )
        self.framework.observe(
            self.cert_transfer.on.certificates_removed, self._on_oauth_ca_changed
        )

    def _on_oauth_relation_changed(self, event: EventBase) -> None:
        """Handle `_on_oauth_relation_changed` event."""
        if not self.charm.unit.is_leader():
            return

        provider_info = self.oauth.get_provider_info()
        if not (provider_info and provider_info.client_secret):
            event.defer()
            return

        self.charm.context.app.oauth_client_secret = provider_info.client_secret
        self.charm.on.config_changed.emit()

    def _on_oauth_relation_broken(self, event: EventBase) -> None:
        """Handle `_on_oauth_relation_broken` event."""
        if not self.charm.unit.is_leader():
            return

        self.charm.context.app.oauth_client_secret = ""
        self.charm.on.config_changed.emit()

    def _on_oauth_ca_changed(self, event: EventBase) -> None:
        """Reconcile the OAuth CA truststore when the transferred cert set changes."""
        if not self.charm.workload.container_can_connect:
            event.defer()
            return

        if self.reconcile_ca_truststore():
            self.charm.workload.restart()

    def reconcile_ca_truststore(self) -> bool:
        """Reconcile the JVM default truststore with the OAuth CAs.

        Returns:
            True if the truststore was modified.
        """
        certificates = self.cert_transfer.get_all_certificates()
        return self.charm.tls_manager.set_oauth_truststore(certificates)
