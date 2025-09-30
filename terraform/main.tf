resource "juju_application" "ui" {
  model = var.model
  name  = var.app_name

  charm {
    name     = "kafka-ui-k8s"
    channel  = var.channel
    revision = var.revision
    base     = var.base
  }

  units       = var.units
  constraints = var.constraints
  config      = var.config
  trust       = true
}
