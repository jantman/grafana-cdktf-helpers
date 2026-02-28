# grafana-cdktf-helpers

Shared CDKTF helper classes for Grafana alert rules, dashboards, and monitoring. Used by my personal infrastructure Puppet repos to manage Grafana via [CDKTF](https://developer.hashicorp.com/terraform/cdktf) (Cloud Development Kit for Terraform).

## Overview

This package provides reusable Python classes for defining Grafana alert rules, dashboards, and monitoring configurations using CDKTF. It extracts common patterns from site-specific CDKTF projects into a shared library.

### Modules

- **`alert_rule_helpers`** — 10 alert rule classes built on a `MetricThresholdRule` base class, supporting various reducers (mean, min, max, last), systemd unit monitoring, boolean series checks, info label validation, and metric change detection.
- **`unifi_helpers`** — 4 UniFi-specific rule classes for interface error rates, device counts, subsystem monitoring, and missing client detection.
- **`nut`** — `NutUps` class for NUT UPS monitoring dashboards and alert rules (battery charge, runtime, voltage, load).
- **`metamonitoring`** — `MetaMonitoring` class for Prometheus/Alertmanager self-monitoring dashboards and alerts.
- **`hosts`** — `Hosts` class for host-level monitoring (systemd, filesystem, memory, swap, MySQL).
- **`stack`** — `BaseStack` class providing common CDKTF stack setup (Grafana provider, Prometheus data source, version checks).
- **`dashboard_builder`** — Pythonic dashboard builder with type-safe dataclasses (`Dashboard`, `TimeseriesPanel`, `Row`, `Target`, `FieldConfig`, etc.) and factory functions for common Home Assistant sensor panels (temperature, humidity, radon).
- **`utils`** — Dashboard loading utilities with placeholder substitution.
- **`dashboards/`** — 17 bundled Grafana dashboard JSON files.

## Installation

```bash
pip install grafana-cdktf-helpers @ git+https://github.com/jantman/grafana-cdktf-helpers.git
```

## Usage

```python
from cdktf import App
from grafana_cdktf_helpers.stack import BaseStack
from grafana_cdktf_helpers.hosts import Hosts
from grafana_cdktf_helpers.metamonitoring import MetaMonitoring

class MyStack(BaseStack):
    def __init__(self, scope, ns):
        super().__init__(scope, ns, grafana_url='http://grafana.example.com:3000/')
        Hosts(self, host_mem={'server1': 64000000000}, org_id=str(self.org_id))
        MetaMonitoring(self, monitoring_hostname='server1', org_id=str(self.org_id))

app = App()
MyStack(app, "grafana-cdktf")
app.synth()
```

### Runtime requirements

This package imports from `imports.grafana.*` — the CDKTF-generated provider bindings. These are generated per-project by `cdktf get` and must be on `sys.path` at runtime (typically by running from the project directory that contains `imports/`).

## Testing

```bash
pip install -e ".[test]"
pytest
```

Tests mock the CDKTF-generated imports so the package can be tested standalone.

## Releasing

1. Bump `version` in `pyproject.toml`
2. Push or merge to `main`
3. The [release workflow](.github/workflows/release.yml) automatically creates a git tag and GitHub Release with a changelog

## License

MIT
