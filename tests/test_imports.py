"""Test that all package modules are importable."""


def test_import_package():
    import grafana_cdktf_helpers
    assert hasattr(grafana_cdktf_helpers, '__doc__')


def test_import_alert_rule_helpers():
    from grafana_cdktf_helpers.alert_rule_helpers import (
        MetricThresholdRule,
        MetricMeanThresholdRule,
        MetricMinThresholdRule,
        MetricMaxThresholdRule,
        MetricLastThresholdRule,
        SystemdInactiveUnitRule,
        BooleanDisappearingSeriesRule,
        IsHealthySeriesRule,
        InfoLabelValueRule,
        MetricChangeRule,
    )
    # Verify all 10 classes are importable
    classes = [
        MetricThresholdRule, MetricMeanThresholdRule,
        MetricMinThresholdRule, MetricMaxThresholdRule,
        MetricLastThresholdRule, SystemdInactiveUnitRule,
        BooleanDisappearingSeriesRule, IsHealthySeriesRule,
        InfoLabelValueRule, MetricChangeRule,
    ]
    assert len(classes) == 10
    for cls in classes:
        assert callable(cls)


def test_import_unifi_helpers():
    from grafana_cdktf_helpers.unifi_helpers import (
        IntefaceErrorRateRule,
        DeviceCountRule,
        DeviceSubsystemRule,
        MissingClientRule,
    )
    assert callable(IntefaceErrorRateRule)
    assert callable(DeviceCountRule)
    assert callable(DeviceSubsystemRule)
    assert callable(MissingClientRule)


def test_import_nut():
    from grafana_cdktf_helpers.nut import NutUps
    assert callable(NutUps)


def test_import_metamonitoring():
    from grafana_cdktf_helpers.metamonitoring import MetaMonitoring
    assert callable(MetaMonitoring)


def test_import_hosts():
    from grafana_cdktf_helpers.hosts import Hosts
    assert callable(Hosts)


def test_import_stack():
    from grafana_cdktf_helpers.stack import BaseStack, REQUIRED_CDKTF_VERSION
    assert callable(BaseStack)
    assert isinstance(REQUIRED_CDKTF_VERSION, str)


def test_import_utils():
    from grafana_cdktf_helpers.utils import load_dashboard, get_shared_dashboard_path
    assert callable(load_dashboard)
    assert callable(get_shared_dashboard_path)


def test_import_dashboard_builder():
    from grafana_cdktf_helpers.dashboard_builder import (
        GridPosition,
        ThresholdStep,
        Override,
        Target,
        FieldConfig,
        Panel,
        TimeseriesPanel,
        Row,
        RowContext,
        Dashboard,
        Annotation,
        temperature_panel,
        humidity_panel,
        radon_panel,
    )
    # Verify all 11 classes + 3 factory functions are importable
    classes = [
        GridPosition, ThresholdStep, Override, Target, FieldConfig,
        Panel, TimeseriesPanel, Row, RowContext, Dashboard, Annotation,
    ]
    assert len(classes) == 11
    for cls in classes:
        assert callable(cls)
    factories = [temperature_panel, humidity_panel, radon_panel]
    assert len(factories) == 3
    for fn in factories:
        assert callable(fn)


def test_inheritance_chain():
    """Verify the class hierarchy is correct."""
    from grafana_cdktf_helpers.alert_rule_helpers import (
        MetricThresholdRule,
        MetricMeanThresholdRule,
        MetricMinThresholdRule,
        MetricMaxThresholdRule,
        MetricLastThresholdRule,
        SystemdInactiveUnitRule,
        BooleanDisappearingSeriesRule,
        IsHealthySeriesRule,
        InfoLabelValueRule,
        MetricChangeRule,
    )
    assert issubclass(MetricMeanThresholdRule, MetricThresholdRule)
    assert issubclass(MetricMinThresholdRule, MetricThresholdRule)
    assert issubclass(MetricMaxThresholdRule, MetricThresholdRule)
    assert issubclass(MetricLastThresholdRule, MetricThresholdRule)
    assert issubclass(SystemdInactiveUnitRule, MetricMeanThresholdRule)
    assert issubclass(BooleanDisappearingSeriesRule, MetricThresholdRule)
    assert issubclass(IsHealthySeriesRule, MetricThresholdRule)
    assert issubclass(InfoLabelValueRule, MetricThresholdRule)
    assert issubclass(MetricChangeRule, MetricThresholdRule)

    from grafana_cdktf_helpers.unifi_helpers import (
        IntefaceErrorRateRule,
        DeviceCountRule,
        DeviceSubsystemRule,
        MissingClientRule,
    )
    assert issubclass(IntefaceErrorRateRule, MetricThresholdRule)
    assert issubclass(DeviceCountRule, MetricThresholdRule)
    assert issubclass(DeviceSubsystemRule, MetricMinThresholdRule)
    assert issubclass(MissingClientRule, MetricThresholdRule)
