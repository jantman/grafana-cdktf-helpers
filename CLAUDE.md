# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Python library of shared CDKTF helper classes for Grafana alert rules, dashboards, and monitoring. Consumed by site-specific CDKTF projects via pip from git. Requires Python >= 3.10.

## Commands

```bash
# Install for development with test dependencies
pip install -e ".[test]"

# Run all tests
pytest

# Run a single test file or test
pytest tests/test_utils.py
pytest tests/test_imports.py::test_alert_rule_classes -v
```

No linter or formatter is configured.

## Architecture

### Core Inheritance Hierarchy

`MetricThresholdRule` (in `alert_rule_helpers.py`, ~350 lines) is the central abstraction. It builds Grafana alert rules with two strategies:
- **Modern alert rules**: 3-stage pipeline (Query → Reduce → Threshold) using `RuleGroupRuleData` expressions
- **Classic conditions**: Multi-query evaluation using `condition` blocks with combined conditions

Specialized subclasses: `MetricMeanThresholdRule`, `MetricMinThresholdRule`, `MetricMaxThresholdRule`, `MetricLastThresholdRule`, `BooleanDisappearingSeriesRule`, `IsHealthySeriesRule`, `InfoLabelValueRule`, `MetricChangeRule`, `SystemdInactiveUnitRule`.

### High-Level Monitoring Classes

These compose multiple rule groups and dashboards into full monitoring configurations:
- **`Hosts`** — host-level monitoring (systemd, filesystem, memory, swap, MySQL)
- **`MetaMonitoring`** — Prometheus/Alertmanager self-monitoring
- **`NutUps`** — NUT UPS device monitoring
- **`BaseStack`** — base CDKTF stack initializing Grafana provider and Prometheus data source

### Runtime Dependency on Generated Code

Source files import from `imports.grafana.*` — these are CDKTF-generated provider bindings created per-project by `cdktf get`. They only exist on `sys.path` when running from a consuming project. Tests mock these via `tests/conftest.py` using `sys.modules` patching.

### Dashboard Bundling

`grafana_cdktf_helpers/dashboards/` contains 17 static JSON dashboard files loaded at runtime by `utils.load_dashboard()` with optional placeholder substitution.

## Releasing

Bump `version` in `pyproject.toml` and push/merge to `main`. The `.github/workflows/release.yml` workflow auto-creates a git tag and GitHub Release.
