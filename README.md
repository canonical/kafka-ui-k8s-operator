# Charmed Kafka UI K8s Operator

[![Release](https://github.com/canonical/kafka-ui-k8s-operator/actions/workflows/release.yaml/badge.svg)](https://github.com/canonical/kafka-ui-k8s-operator/actions/workflows/release.yaml)
[![Tests](https://github.com/canonical/kafka-ui-k8s-operator/actions/workflows/ci.yaml/badge.svg?branch=main)](https://github.com/canonical/kafka-ui-k8s-operator/actions/workflows/ci.yaml?query=branch%3Amain)

The Charmed Kafka UI K8s Operator delivers automated operations management from day 0 to day 2 on [Kafbat's Kafka UI](https://github.com/kafbat/kafka-ui-k8s), and enables users to:

- View Apache Kafka cluster configuration, topics, ACLs, consumer groups and more
- Broker performance monitoring via JMX metrics dashboards
- Authentication and SSL encryption enabled by default
- Integrations with other Charmed Apache Kafka operators, like [Charmed Apache Kafka Connect K8s](https://charmhub.io/kafka-connect-k8s) and [Charmed Karapace K8s](https://charmhub.io/karapace-k8s)

The Charmed Kafka UI K8s Operator uses the latest [`charmed-kafka-ui` Rock](https://github.com/canonical/charmed-kafka-ui-rock) containing Kafbat's Kafka UI, distributed by Canonical.

## Usage

If you are using [MicroK8s](https://microk8s.io/docs) as your Kubernetes, you will need to set it up correctly before using Charmed Kafka UI K8s. Enable the necessary MicroK8s addons with:

```bash
microk8s enable dns
microk8s enable hostpath-storage
```

In order to access the Charmed Kafka UI K8s service from the browser on your host-machine, you will need a load balancer controller. If you don't have one already, the `metallb` addon should be enabled:

```bash
IPADDR=$(ip -4 -j route get 2.2.2.2 | jq -r '.[] | .prefsrc')
microk8s enable metallb:$IPADDR-$IPADDR
```

Before using Charmed Kafka UI K8s, an Apache Kafka cluster needs to be deployed. The Charmed Apache Kafka K8s operator can be deployed as follows:

```bash
juju deploy kafka-k8s --channel 4/edge -n 3 --config roles="broker,controller"
```

To deploy the Charmed Kafka UI K8s operator and relate it with the Apache Kafka cluster, use the following commands:

```bash
juju deploy kafka-ui-k8s --channel latest/edge
juju integrate kafka-ui-k8s kafka-k8s
```

Monitor the deployment via the `juju status` command. Once all the units show as `active|idle`, the Kafka UI is ready to be used.

In order to access the Kafka UI, get the password for the `admin` user with the following command:

```bash
juju ssh --container kafka-ui kafka-ui-k8s/0 'cat /etc/kafka-ui/application-local.yml' 2>/dev/null | \
    yq '.spring.security.user.password' | \
    sed 's/\"//g'
```

Now, expose the ingress service using the [Traefik K8s Operator](https://charmhub.io/traefik-k8s):

```bash
juju deploy traefik-k8s
juju relate kafka-ui-k8s traefik-k8s
```

Run the `show-proxied-endpoints` Juju Action on the `traefik-k8s` application to get the correct URL:

```bash
juju run traefik-k8s/leader show-proxied-endpoints
```

Finally, you can now reach the Kafka UI in your browser with the `admin` username and corresponding password derived above. For example, if using Firefox:

```bash
URL=${juju run traefik-k8s/leader show-proxied-endpoints | jq '."proxied-endpoints"."kafka-ui-k8s".url'}
firefox --new-tab https://$URL
```

## Relations

The Charmed Kafka UI Operator supports Juju [relations](https://documentation.ubuntu.com/juju/latest/reference/relation/) for interfaces listed below.

- `ingress` (**required**) with Traefik
- `kafka_client` (**required**) with Charmed Apache Kafka
- `karapace_client` integration with Charmed Karapace
- `connect_client` integration with Charmed Apache Kafka Connect
- `tls-certificates` interface with any provider charm to manage certificates

## Contributing

Please see the [Juju SDK docs](https://juju.is/docs/sdk) for guidelines on enhancements to this charm following best practice guidelines, and [CONTRIBUTING.md](https://github.com/canonical/kafka-ui-k8-operator/blob/main/CONTRIBUTING.md) for developer guidance.

### We are Hiring!

Also, if you truly enjoy working on open-source projects like this one and you would like to be part of the OSS revolution, please don't forget to check out the [open positions](https://canonical.com/careers/all) we have at [Canonical](https://canonical.com/). 

## License

The Charmed Kafka UI K8s Operator is free software, distributed under the Apache Software License, version 2.0. See [LICENSE](https://github.com/canonical/kafka-ui-k8s-operator/blob/main/LICENSE) for more information.
