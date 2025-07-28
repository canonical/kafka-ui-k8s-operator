#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Kafka Connect workload class and methods."""

import logging
import socket
from contextlib import closing
from typing import Iterable, Mapping

from charmlibs import pathops
from ops import Container, pebble
from tenacity import retry, retry_if_result, stop_after_attempt, wait_fixed
from typing_extensions import override

from core.workload import WorkloadBase
from literals import GROUP, SERVICE_NAME, USER_NAME

logger = logging.getLogger(__name__)


class Workload(WorkloadBase):
    """Wrapper for performing common operations specific to the Kafka Connect Snap."""

    service: str = SERVICE_NAME
    SNAP_NAME = "charmed-kafka-ui"

    def __init__(self, container: Container, profile: str = "production") -> None:
        self.container = container
        self.root = pathops.ContainerPath("/", container=container)

    @override
    def start(self) -> None:
        self.container.add_layer("kafka-ui", self.layer, combine=True)
        self.container.restart(self.service)

    @override
    def stop(self) -> None:
        self.container.stop(self.service)

    @override
    def restart(self) -> None:
        self.start()

    @override
    def read(self, path: str) -> list[str]:
        return (
            [] if not (self.root / path).exists() else (self.root / path).read_text().split("\n")
        )

    @override
    def write(self, content: str, path: str, mode: str = "w") -> None:
        (self.root / path).write_text(content, user=USER_NAME, group=GROUP)

    @override
    def exec(
        self,
        command: list[str] | str,
        env: Mapping[str, str] | None = None,
        working_dir: str | None = None,
    ) -> str:
        command = command if isinstance(command, list) else [command]
        try:
            process = self.container.exec(
                command=command,
                environment=env,
                working_dir=working_dir,
                combine_stderr=True,
            )
            output, _ = process.wait_output()
            return output
        except pebble.ExecError as e:
            logger.error(f"cmd failed - cmd={command}, stdout={e.stdout}, stderr={e.stderr}")
            logger.error(e)
            raise e

    @override
    @retry(
        wait=wait_fixed(1),
        stop=stop_after_attempt(5),
        retry=retry_if_result(lambda result: result is False),
        retry_error_callback=lambda _: False,
    )
    def active(self) -> bool:
        if not self.installed:
            return False

        if self.service not in self.container.get_services():
            return False

        return self.container.get_service(self.service).is_running()

    @override
    def check_socket(self, host: str, port: int) -> bool:
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
            return sock.connect_ex((host, port)) == 0

    @property
    @override
    def installed(self) -> bool:
        """Whether the workload service is installed or not."""
        if not self.container.can_connect():
            return False

        return True

    @property
    @override
    def container_can_connect(self) -> bool:
        return self.container.can_connect()

    @property
    @override
    def layer(self) -> pebble.Layer:
        command = [
            "java",
            f"-Dspring.config.additional-location={self.paths.config_dir}/application-local.yml",
            "--add-opens",
            "java.rmi/javax.rmi.ssl=ALL-UNNAMED",
            "-Xms1G",
            "-Xmx1G",
            "-XX:+UseG1GC",
            "-jar",
            "/opt/kafka-ui/libs/api-1.3.0.jar",
        ]

        layer_config: pebble.LayerDict = {
            "summary": "Kafka UI Layer",
            "description": "Pebble config layer for Apache Kafka UI",
            "services": {
                self.service: {
                    "override": "merge",
                    "summary": "Kafka UI",
                    "command": " ".join(command),
                    "startup": "enabled",
                    "user": USER_NAME,
                    "group": GROUP,
                }
            },
        }
        return pebble.Layer(layer_config)
        raise NotImplementedError

    @override
    def set_environment(self, env_vars: Iterable[str]) -> None:
        raw_current_env = self.read(self.paths.env)
        current_env = self.map_env(raw_current_env)

        updated_env = current_env | self.map_env(env_vars)
        content = "\n".join([f"{key}={value}" for key, value in updated_env.items()])
        self.write(content=content + "\n", path=self.paths.env)

    @staticmethod
    def map_env(env: Iterable[str]) -> dict[str, str]:
        """Parse env variables into a dict."""
        map_env = {}
        for var in env:
            key = "".join(var.split("=", maxsplit=1)[0])
            value = "".join(var.split("=", maxsplit=1)[1:])
            if key:
                # only check for keys, as we can have an empty value for a variable
                map_env[key] = value
        return map_env
