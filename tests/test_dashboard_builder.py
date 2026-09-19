"""Tests for the dashboard_builder module."""
import json

from grafana_cdktf_helpers.dashboard_builder import (
    GridPosition,
    ThresholdStep,
    Override,
    Target,
    LokiTarget,
    FieldConfig,
    Panel,
    TimeseriesPanel,
    HeatmapPanel,
    XYChartPanel,
    LogsPanel,
    Row,
    Dashboard,
    Annotation,
    temperature_panel,
    humidity_panel,
    radon_panel,
)

DS_UID = "test-ds-uid"


class TestGridPosition:

    def test_defaults(self):
        gp = GridPosition()
        assert gp.h == 8
        assert gp.w == 12
        assert gp.x == 0
        assert gp.y == 0

    def test_custom(self):
        gp = GridPosition(h=4, w=6, x=3, y=10)
        assert gp.h == 4
        assert gp.w == 6
        assert gp.x == 3
        assert gp.y == 10


class TestThresholdStep:

    def test_color_only(self):
        ts = ThresholdStep("green")
        assert ts.color == "green"
        assert ts.value is None

    def test_color_and_value(self):
        ts = ThresholdStep("red", 80)
        assert ts.color == "red"
        assert ts.value == 80


class TestTarget:

    def test_defaults(self):
        t = Target(expr="up")
        assert t.expr == "up"
        assert t.legend_format == "{{friendly_name}}"
        assert t.ref_id == "A"
        assert t.interval == ""
        assert t.hide is False
        assert t.instant is False

    def test_to_dict(self):
        t = Target(expr="up{job='test'}", legend_format="{{job}}", ref_id="B",
                   interval="1m", hide=True, instant=True)
        d = t.to_dict(DS_UID)
        assert d["datasource"] == {"type": "prometheus", "uid": DS_UID}
        assert d["editorMode"] == "code"
        assert d["expr"] == "up{job='test'}"
        assert d["instant"] is True
        assert d["range"] is False
        assert d["legendFormat"] == "{{job}}"
        assert d["refId"] == "B"
        assert d["hide"] is True
        assert d["interval"] == "1m"

    def test_to_dict_range_mode(self):
        t = Target(expr="up")
        d = t.to_dict(DS_UID)
        assert d["instant"] is False
        assert d["range"] is True


class TestFieldConfig:

    def test_defaults(self):
        fc = FieldConfig()
        assert fc.unit == "short"
        assert len(fc.thresholds) == 2
        assert fc.color_mode == "palette-classic"
        assert fc.fill_opacity == 0
        assert fc.line_width == 1
        assert fc.gradient_mode == "none"
        assert fc.axis_label == ""
        assert fc.overrides == []
        assert fc.draw_style == "line"
        assert fc.stacking_mode == "none"

    def test_to_dict_structure(self):
        fc = FieldConfig(unit="fahrenheit")
        d = fc.to_dict()
        assert "defaults" in d
        assert "overrides" in d
        assert d["defaults"]["unit"] == "fahrenheit"
        assert d["defaults"]["color"]["mode"] == "palette-classic"
        assert d["defaults"]["custom"]["drawStyle"] == "line"
        assert d["defaults"]["custom"]["fillOpacity"] == 0

    def test_to_dict_thresholds(self):
        fc = FieldConfig(thresholds=[
            ThresholdStep("green"),
            ThresholdStep("yellow", 50),
            ThresholdStep("red", 80),
        ])
        d = fc.to_dict()
        steps = d["defaults"]["thresholds"]["steps"]
        assert len(steps) == 3
        assert steps[0] == {"color": "green", "value": None}
        assert steps[1] == {"color": "yellow", "value": 50}
        assert steps[2] == {"color": "red", "value": 80}

    def test_to_dict_overrides(self):
        fc = FieldConfig(overrides=[
            Override("byName", "Average", [{"id": "custom.fillOpacity", "value": 20}])
        ])
        d = fc.to_dict()
        assert len(d["overrides"]) == 1
        o = d["overrides"][0]
        assert o["matcher"]["id"] == "byName"
        assert o["matcher"]["options"] == "Average"
        assert o["properties"] == [{"id": "custom.fillOpacity", "value": 20}]

    def test_to_dict_custom_draw_style_and_stacking(self):
        fc = FieldConfig(draw_style="bars", stacking_mode="normal")
        d = fc.to_dict()
        assert d["defaults"]["custom"]["drawStyle"] == "bars"
        assert d["defaults"]["custom"]["stacking"]["mode"] == "normal"


class TestPanel:

    def test_defaults(self):
        p = Panel("Test", "stat")
        assert p.title == "Test"
        assert p.type == "stat"
        assert p.datasource_uid is None
        assert p.description == ""
        assert p.fixed_id is None
        assert p.targets == []
        assert p.id is None

    def test_to_dict(self):
        p = Panel("Test Panel", "stat", datasource_uid=DS_UID,
                  grid_pos=GridPosition(h=4, w=6, x=3, y=5))
        p.id = 42
        d = p.to_dict()
        assert d["title"] == "Test Panel"
        assert d["type"] == "stat"
        assert d["id"] == 42
        assert d["datasource"]["uid"] == DS_UID
        assert d["gridPos"] == {"h": 4, "w": 6, "x": 3, "y": 5}
        assert d["targets"] == []
        assert d["description"] == ""


class TestTimeseriesPanel:

    def test_auto_ref_ids(self):
        targets = [Target(expr="a"), Target(expr="b"), Target(expr="c")]
        panel = TimeseriesPanel("Test", targets, datasource_uid=DS_UID)
        assert panel.targets[0].ref_id == "A"
        assert panel.targets[1].ref_id == "B"
        assert panel.targets[2].ref_id == "C"

    def test_explicit_ref_ids_preserved(self):
        targets = [
            Target(expr="a", ref_id="X"),
            Target(expr="b", ref_id="Y"),
        ]
        panel = TimeseriesPanel("Test", targets, datasource_uid=DS_UID)
        assert panel.targets[0].ref_id == "X"
        assert panel.targets[1].ref_id == "Y"

    def test_to_dict(self):
        targets = [Target(expr="up")]
        panel = TimeseriesPanel("Timeseries", targets,
                                field_config=FieldConfig(unit="percent"),
                                legend_calcs=["mean", "max"],
                                datasource_uid=DS_UID)
        panel.id = 1
        d = panel.to_dict()
        assert d["type"] == "timeseries"
        assert d["fieldConfig"]["defaults"]["unit"] == "percent"
        assert d["options"]["legend"]["calcs"] == ["mean", "max"]
        assert d["options"]["legend"]["showLegend"] is True
        assert d["options"]["tooltip"]["mode"] == "single"


class TestRow:

    def test_defaults(self):
        r = Row("Test Row")
        assert r.title == "Test Row"
        assert r.collapsed is False
        assert r.panels == []

    def test_add_panel(self):
        r = Row("Test")
        p = Panel("P1", "stat", datasource_uid=DS_UID)
        result = r.add_panel(p)
        assert result is p
        assert len(r.panels) == 1

    def test_to_dict_expanded(self):
        r = Row("Expanded Row")
        r.id = 1
        r.grid_pos = GridPosition(h=1, w=24, x=0, y=0)
        p = Panel("P1", "stat", datasource_uid=DS_UID)
        p.id = 2
        r.add_panel(p)
        d = r.to_dict()
        assert d["collapsed"] is False
        assert d["title"] == "Expanded Row"
        assert d["type"] == "row"
        assert d["id"] == 1
        # Expanded rows must emit an empty panels array; the real panels live at
        # the dashboard top level. Emitting `{}` stubs rendered as phantom
        # "No data" panels under Grafana 12/13's new dashboard engine.
        assert d["panels"] == []

    def test_to_dict_collapsed(self):
        r = Row("Collapsed Row", collapsed=True)
        r.id = 1
        r.grid_pos = GridPosition(h=1, w=24, x=0, y=0)
        p = Panel("P1", "stat", datasource_uid=DS_UID)
        p.id = 2
        r.add_panel(p)
        d = r.to_dict()
        assert d["collapsed"] is True
        # Collapsed rows include full panel dicts
        assert len(d["panels"]) == 1
        assert d["panels"][0]["title"] == "P1"

    def test_to_dict_no_grid_pos(self):
        r = Row("No Pos")
        r.id = 1
        d = r.to_dict()
        assert d["gridPos"] == {"h": 1, "w": 24, "x": 0, "y": 0}


class TestAnnotation:

    def test_defaults(self):
        a = Annotation("test", "blue")
        assert a.name == "test"
        assert a.icon_color == "blue"
        assert a.tags == []
        assert a.enabled is True

    def test_to_dict(self):
        a = Annotation("deploy", "green", tags=["deploy", "prod"], enabled=False)
        d = a.to_dict()
        assert d["name"] == "deploy"
        assert d["iconColor"] == "green"
        assert d["enable"] is False
        assert d["target"]["tags"] == ["deploy", "prod"]
        assert d["datasource"]["uid"] == "grafana"


class TestDashboard:

    def test_constructor(self):
        d = Dashboard("Test", datasource_uid=DS_UID)
        assert d.title == "Test"
        assert d.datasource_uid == DS_UID
        assert d.description == ""
        assert d.uid is None
        assert d.dashboard_id is None
        assert d.version == 1
        assert d.schema_version == 38
        assert d.rows == []
        assert d.panels == []
        assert d.annotations == []

    def test_constructor_custom_params(self):
        d = Dashboard("Test", datasource_uid=DS_UID, dashboard_id=78,
                      version=9, schema_version=39, uid="abc-123",
                      description="desc")
        assert d.dashboard_id == 78
        assert d.version == 9
        assert d.schema_version == 39
        assert d.uid == "abc-123"
        assert d.description == "desc"

    def test_minimal_to_json(self):
        d = Dashboard("Minimal", datasource_uid=DS_UID)
        result = json.loads(d.to_json())
        assert result["title"] == "Minimal"
        assert result["id"] is None
        assert result["version"] == 1
        assert result["schemaVersion"] == 38
        assert result["panels"] == []

    def test_configurable_id_version_schema(self):
        d = Dashboard("Test", datasource_uid=DS_UID,
                      dashboard_id=78, version=9, schema_version=40)
        result = json.loads(d.to_json())
        assert result["id"] == 78
        assert result["version"] == 9
        assert result["schemaVersion"] == 40

    def test_add_row(self):
        d = Dashboard("Test", datasource_uid=DS_UID)
        row = d.add_row("Row 1")
        assert isinstance(row, Row)
        assert len(d.rows) == 1

    def test_row_context_manager(self):
        d = Dashboard("Test", datasource_uid=DS_UID)
        with d.row("Row 1") as r:
            p = Panel("P1", "stat")
            r.add_panel(p)
        assert len(d.rows) == 1
        assert len(d.rows[0].panels) == 1

    def test_id_assignment(self):
        d = Dashboard("Test", datasource_uid=DS_UID)
        row = d.add_row("Row 1")
        p1 = Panel("P1", "stat")
        p2 = Panel("P2", "stat")
        row.add_panel(p1)
        row.add_panel(p2)
        d._assign_ids_and_positions()
        assert row.id == 1
        assert p1.id == 2
        assert p2.id == 3

    def test_fixed_id_handling(self):
        d = Dashboard("Test", datasource_uid=DS_UID)
        row = d.add_row("Row 1")
        p1 = Panel("P1", "stat")
        p2 = Panel("P2", "stat", fixed_id=100)
        p3 = Panel("P3", "stat")
        row.add_panel(p1)
        row.add_panel(p2)
        row.add_panel(p3)
        d._assign_ids_and_positions()
        assert p2.id == 100
        assert p1.id != 100
        assert p3.id != 100

    def test_fixed_id_avoids_conflict(self):
        d = Dashboard("Test", datasource_uid=DS_UID)
        row = d.add_row("Row 1")
        # fixed_id=2 would conflict with auto-assigned id 2
        p1 = Panel("P1", "stat", fixed_id=2)
        p2 = Panel("P2", "stat")
        row.add_panel(p1)
        row.add_panel(p2)
        d._assign_ids_and_positions()
        assert p1.id == 2
        assert p2.id != 2
        assert row.id != 2

    def test_grid_positioning(self):
        d = Dashboard("Test", datasource_uid=DS_UID)
        row = d.add_row("Row 1")
        p1 = Panel("P1", "stat", grid_pos=GridPosition(h=8, w=12, x=0))
        p2 = Panel("P2", "stat", grid_pos=GridPosition(h=8, w=12, x=12))
        row.add_panel(p1)
        row.add_panel(p2)
        d._assign_ids_and_positions()
        # Row at y=0, panels at y=1
        assert row.grid_pos.y == 0
        assert p1.grid_pos.y == 1
        assert p2.grid_pos.y == 1

    def test_multi_row_grid_positioning(self):
        d = Dashboard("Test", datasource_uid=DS_UID)
        row1 = d.add_row("Row 1")
        p1 = Panel("P1", "stat", grid_pos=GridPosition(h=8, w=12, x=0))
        row1.add_panel(p1)

        row2 = d.add_row("Row 2")
        p2 = Panel("P2", "stat", grid_pos=GridPosition(h=8, w=12, x=0))
        row2.add_panel(p2)

        d._assign_ids_and_positions()
        # Row1 at y=0, P1 at y=1, Row2 at y=9, P2 at y=10
        assert row1.grid_pos.y == 0
        assert p1.grid_pos.y == 1
        assert row2.grid_pos.y == 9
        assert p2.grid_pos.y == 10

    def test_id_for_panel(self):
        d = Dashboard("Test", datasource_uid=DS_UID)
        row = d.add_row("Row 1")
        row.add_panel(Panel("My Panel", "stat"))
        d._assign_ids_and_positions()
        assert d.id_for_panel("My Panel") is not None
        assert d.id_for_panel("Nonexistent") is None

    def test_id_for_panel_before_assign(self):
        d = Dashboard("Test", datasource_uid=DS_UID)
        assert d.id_for_panel("anything") is None

    def test_datasource_uid_propagation(self):
        d = Dashboard("Test", datasource_uid=DS_UID)
        row = d.add_row("Row 1")
        p1 = Panel("P1", "stat")  # No datasource_uid
        p2 = Panel("P2", "stat", datasource_uid="custom-uid")
        row.add_panel(p1)
        row.add_panel(p2)
        d._assign_ids_and_positions()
        assert p1.datasource_uid == DS_UID
        assert p2.datasource_uid == "custom-uid"

    def test_datasource_uid_propagation_standalone_panels(self):
        d = Dashboard("Test", datasource_uid=DS_UID)
        p = Panel("Standalone", "stat")
        d.panels.append(p)
        d._assign_ids_and_positions()
        assert p.datasource_uid == DS_UID

    def test_variable_substitution(self):
        d = Dashboard("Test", datasource_uid=DS_UID)
        row = d.add_row("Row 1")
        targets = [Target(expr='metric{entity=~"(!!!my_var!!!)"}')]
        panel = TimeseriesPanel("P1", targets)
        row.add_panel(panel)
        result = d.to_json(variables={"my_var": "sensor.temp"})
        assert "sensor.temp" in result
        assert "!!!my_var!!!" not in result

    def test_annotations_in_json(self):
        d = Dashboard("Test", datasource_uid=DS_UID)
        d.annotations.append(Annotation("deploy", "green", ["deploy"]))
        result = json.loads(d.to_json())
        annotations = result["annotations"]["list"]
        # Built-in + all-annotations + 1 custom
        assert len(annotations) == 3
        assert annotations[0]["builtIn"] == 1
        assert annotations[1]["name"] == "All Annotations"
        assert annotations[1]["target"]["tags"] == []
        assert annotations[1]["target"]["matchAny"] is False
        assert annotations[2]["name"] == "deploy"

    def test_annotations_with_tags(self):
        d = Dashboard("Test", datasource_uid=DS_UID,
                      annotation_tags=["deploy", "backup"])
        result = json.loads(d.to_json())
        annotations = result["annotations"]["list"]
        all_ann = annotations[1]
        assert all_ann["name"] == "All Annotations"
        assert all_ann["target"]["tags"] == ["deploy", "backup"]
        assert all_ann["target"]["matchAny"] is True

    def test_collapsed_row_json(self):
        d = Dashboard("Test", datasource_uid=DS_UID)
        with d.row("Collapsed", collapsed=True) as r:
            r.add_panel(TimeseriesPanel("P1", [Target(expr="up")]))
        result = json.loads(d.to_json())
        panels = result["panels"]
        # Only the row itself, panels are embedded inside the row
        assert len(panels) == 1
        assert panels[0]["type"] == "row"
        assert panels[0]["collapsed"] is True
        assert len(panels[0]["panels"]) == 1

    def test_expanded_row_json(self):
        d = Dashboard("Test", datasource_uid=DS_UID)
        with d.row("Expanded") as r:
            r.add_panel(TimeseriesPanel("P1", [Target(expr="up")]))
        result = json.loads(d.to_json())
        panels = result["panels"]
        # Row + 1 panel after it
        assert len(panels) == 2
        assert panels[0]["type"] == "row"
        assert panels[1]["type"] == "timeseries"

    def test_to_json_full_structure(self):
        d = Dashboard("Full", datasource_uid=DS_UID, uid="test-uid",
                      description="A test dashboard")
        result = json.loads(d.to_json())
        assert result["title"] == "Full"
        assert result["uid"] == "test-uid"
        assert result["description"] == "A test dashboard"
        assert result["editable"] is True
        assert result["style"] == "dark"
        assert result["time"] == {"from": "now-24h", "to": "now"}
        assert result["refresh"] == ""


class TestTemperaturePanel:

    def test_fahrenheit(self):
        panel = temperature_panel("Temp", "sensor.temp", datasource_uid=DS_UID)
        assert panel.type == "timeseries"
        assert len(panel.targets) == 1
        assert "* (9/5)) + 32" in panel.targets[0].expr
        assert panel.field_config.unit == "fahrenheit"

    def test_celsius(self):
        panel = temperature_panel("Temp", "sensor.temp", unit="celsius",
                                  datasource_uid=DS_UID)
        assert "* (9/5)" not in panel.targets[0].expr
        assert "hass_sensor_temperature_celsius" in panel.targets[0].expr
        assert panel.field_config.unit == "celsius"

    def test_entity_pattern(self):
        panel = temperature_panel("Temp", "sensor.a|sensor.b",
                                  datasource_uid=DS_UID)
        assert "sensor.a|sensor.b" in panel.targets[0].expr


class TestHumidityPanel:

    def test_basic(self):
        panel = humidity_panel("Humid", "sensor.humid", datasource_uid=DS_UID)
        assert panel.type == "timeseries"
        assert "hass_sensor_humidity_percent" in panel.targets[0].expr
        assert panel.field_config.unit == "humidity"


class TestRadonPanel:

    def test_with_thresholds(self):
        panel = radon_panel("Radon", ["sensor.radon1"], datasource_uid=DS_UID)
        assert len(panel.targets) == 1
        assert panel.targets[0].ref_id == "A"
        assert panel.field_config.color_mode == "thresholds"
        assert panel.field_config.fill_opacity == 30
        assert panel.field_config.gradient_mode == "scheme"
        assert len(panel.field_config.thresholds) == 4

    def test_without_thresholds(self):
        panel = radon_panel("Radon", ["sensor.r1", "sensor.r2"],
                            with_thresholds=False, datasource_uid=DS_UID)
        assert len(panel.targets) == 2
        assert panel.targets[0].ref_id == "A"
        assert panel.targets[1].ref_id == "B"
        assert panel.field_config.color_mode == "palette-classic"
        assert panel.field_config.fill_opacity == 0

    def test_axis_label(self):
        panel = radon_panel("Radon", ["sensor.r1"], datasource_uid=DS_UID)
        assert panel.field_config.axis_label == "pCi/L"


class TestTargetDatasourceType:
    """The datasource type and query format added in 0.15.0."""

    def test_defaults_to_prometheus(self):
        t = Target(expr="up")
        assert t.datasource_type is None   # unset, not "prometheus"
        assert t.format is None
        assert t.to_dict(DS_UID)["datasource"]["type"] == "prometheus"

    def test_explicit_type_is_emitted(self):
        t = Target(expr="up", datasource_type="influxdb")
        assert t.to_dict(DS_UID)["datasource"]["type"] == "influxdb"

    def test_format_absent_when_unset(self):
        assert "format" not in Target(expr="up").to_dict(DS_UID)

    def test_format_present_when_set(self):
        t = Target(expr="my_metric_bucket", format="heatmap")
        assert t.to_dict(DS_UID)["format"] == "heatmap"

    def test_panel_type_is_inherited_when_target_has_no_opinion(self):
        t = Target(expr="up")
        assert t.to_dict(DS_UID, "loki")["datasource"]["type"] == "loki"

    def test_explicit_target_type_beats_panel_type(self):
        t = Target(expr="up", datasource_type="influxdb")
        assert t.to_dict(DS_UID, "loki")["datasource"]["type"] == "influxdb"

    def test_explicit_prometheus_is_not_overridden_by_panel(self):
        """"Unset" and "deliberately prometheus" are different things.

        A target that names prometheus keeps it even on a Loki panel; only one
        that said nothing inherits. This is why the field defaults to None.
        """
        t = Target(expr="up", datasource_type="prometheus")
        assert t.to_dict(DS_UID, "loki")["datasource"]["type"] == "prometheus"

    def test_unset_is_none_not_a_string(self):
        assert Target(expr="up").datasource_type is None


class TestLokiTarget:

    def test_defaults(self):
        t = LokiTarget(expr='{job="x"}')
        assert t.datasource_type == "loki"
        assert t.legend_format == ""
        assert t.query_type == "range"
        assert t.max_lines is None

    def test_to_dict(self):
        t = LokiTarget(expr='{job="x"} | json', ref_id="B")
        d = t.to_dict(DS_UID)
        assert d["datasource"] == {"type": "loki", "uid": DS_UID}
        assert d["expr"] == '{job="x"} | json'
        assert d["legendFormat"] == ""
        assert d["queryType"] == "range"
        assert d["refId"] == "B"

    def test_max_lines_absent_when_unset(self):
        assert "maxLines" not in LokiTarget(expr='{job="x"}').to_dict(DS_UID)

    def test_max_lines_present_when_set(self):
        t = LokiTarget(expr='{job="x"}', max_lines=500)
        assert t.to_dict(DS_UID)["maxLines"] == 500

    def test_panel_type_does_not_override_loki(self):
        t = LokiTarget(expr='{job="x"}')
        assert t.to_dict(DS_UID, "prometheus")["datasource"]["type"] == "loki"


class TestPanelDatasourceType:

    def test_defaults_to_prometheus(self):
        p = Panel("P", "stat", datasource_uid=DS_UID)
        assert p.datasource_type is None
        assert p.to_dict()["datasource"]["type"] == "prometheus"

    def test_explicit_type_is_emitted(self):
        p = Panel("P", "logs", datasource_uid=DS_UID, datasource_type="loki")
        assert p.to_dict()["datasource"]["type"] == "loki"

    def test_type_is_passed_down_to_targets(self):
        p = Panel("P", "logs", datasource_uid=DS_UID, datasource_type="loki")
        p.targets = [Target(expr='{job="x"}')]
        assert p.to_dict()["targets"][0]["datasource"]["type"] == "loki"

    def test_target_with_own_type_is_not_overridden_by_panel(self):
        p = Panel("P", "stat", datasource_uid=DS_UID, datasource_type="loki")
        p.targets = [Target(expr="up", datasource_type="influxdb")]
        assert p.to_dict()["targets"][0]["datasource"]["type"] == "influxdb"


class TestDashboardDatasourceTypePropagation:

    def test_default_is_prometheus(self):
        assert Dashboard("D", datasource_uid=DS_UID).datasource_type == "prometheus"

    def test_propagates_to_panel_without_one(self):
        d = Dashboard("D", datasource_uid=DS_UID, datasource_type="loki")
        p = Panel("P", "logs")
        d.panels.append(p)
        d._assign_ids_and_positions()
        assert p.datasource_type == "loki"

    def test_does_not_override_panel_with_own_type(self):
        d = Dashboard("D", datasource_uid=DS_UID, datasource_type="loki")
        p = Panel("P", "stat", datasource_type="prometheus")
        d.panels.append(p)
        d._assign_ids_and_positions()
        assert p.datasource_type == "prometheus"

    def test_propagates_into_row_panels(self):
        d = Dashboard("D", datasource_uid=DS_UID, datasource_type="loki")
        row = d.add_row("Row")
        p1 = row.add_panel(Panel("P1", "logs"))
        p2 = row.add_panel(Panel("P2", "stat", datasource_type="prometheus"))
        d._assign_ids_and_positions()
        assert p1.datasource_type == "loki"
        assert p2.datasource_type == "prometheus"

    def test_uid_and_type_are_independent(self):
        """A Loki panel on a Prometheus dashboard sets both of its own."""
        d = Dashboard("D", datasource_uid=DS_UID)
        p = Panel("P", "logs", datasource_uid="loki-uid", datasource_type="loki")
        d.panels.append(p)
        d._assign_ids_and_positions()
        assert p.to_dict()["datasource"] == {"type": "loki", "uid": "loki-uid"}


class TestBackwardsCompatibility:
    """The 0.14.2 output must be reproduced key-for-key.

    23 dashboards in a consuming project are diffed byte-for-byte across this
    change; these assertions catch a defaults regression long before that does.
    """

    def test_target_dict_is_unchanged(self):
        d = Target(expr="up").to_dict(DS_UID)
        assert d == {
            "datasource": {"type": "prometheus", "uid": DS_UID},
            "editorMode": "code",
            "expr": "up",
            "instant": False,
            "legendFormat": "{{friendly_name}}",
            "range": True,
            "refId": "A",
            "hide": False,
            "interval": "",
        }

    def test_target_key_order_is_unchanged(self):
        assert list(Target(expr="up").to_dict(DS_UID).keys()) == [
            "datasource", "editorMode", "expr", "instant", "legendFormat",
            "range", "refId", "hide", "interval",
        ]

    def test_panel_dict_is_unchanged(self):
        p = Panel("P", "stat", datasource_uid=DS_UID)
        p.id = 7
        assert p.to_dict() == {
            "datasource": {"type": "prometheus", "uid": DS_UID},
            "description": "",
            "gridPos": {"h": 8, "w": 12, "x": 0, "y": 0},
            "id": 7,
            "title": "P",
            "type": "stat",
            "targets": [],
        }

    def test_panel_key_order_is_unchanged(self):
        p = Panel("P", "stat", datasource_uid=DS_UID)
        assert list(p.to_dict().keys()) == [
            "datasource", "description", "gridPos", "id", "title", "type",
            "targets",
        ]

    def test_timeseries_panel_key_order_is_unchanged(self):
        p = TimeseriesPanel("P", [Target(expr="up")], datasource_uid=DS_UID)
        assert list(p.to_dict().keys()) == [
            "datasource", "description", "gridPos", "id", "title", "type",
            "targets", "fieldConfig", "options",
        ]


class TestPanelTransformations:

    def test_absent_when_unset(self):
        p = Panel("P", "stat", datasource_uid=DS_UID)
        assert "transformations" not in p.to_dict()

    def test_absent_when_empty_list(self):
        """An empty list must omit the key, not emit ``[]``.

        Emitting it would change every existing panel's JSON and make a
        byte-for-byte upgrade check worthless.
        """
        p = Panel("P", "stat", datasource_uid=DS_UID, transformations=[])
        assert "transformations" not in p.to_dict()

    def test_present_when_non_empty(self):
        transformations = [
            {"id": "extractFields", "options": {"source": "labels"}},
            {"id": "convertFieldType",
             "options": {"conversions": [{"targetField": "distance",
                                          "destinationType": "number"}]}},
        ]
        p = Panel("P", "xychart", datasource_uid=DS_UID,
                  transformations=transformations)
        assert p.to_dict()["transformations"] == transformations


class TestHeatmapPanel:

    def test_type_and_targets(self):
        panel = HeatmapPanel("Heat", [Target(expr="m_bucket", format="heatmap")],
                             datasource_uid=DS_UID)
        panel.id = 1
        d = panel.to_dict()
        assert d["type"] == "heatmap"
        assert d["targets"][0]["format"] == "heatmap"

    def test_calculate_is_false(self):
        """The data arrives already bucketed; Grafana must not re-bucket it."""
        panel = HeatmapPanel("Heat", [Target(expr="m_bucket")],
                             datasource_uid=DS_UID)
        assert panel.to_dict()["options"]["calculate"] is False

    def test_default_options(self):
        panel = HeatmapPanel("Heat", [Target(expr="m_bucket")],
                             datasource_uid=DS_UID)
        opts = panel.to_dict()["options"]
        assert opts["cellGap"] == 1
        assert opts["color"] == {
            "mode": "scheme", "scheme": "Oranges", "fill": "dark-orange",
            "scale": "exponential", "exponent": 0.5, "steps": 64,
            "reverse": False,
        }
        assert opts["exemplars"] == {"color": "rgba(255,0,255,0.7)"}
        assert opts["filterValues"] == {"le": 1e-9}
        assert opts["legend"] == {"show": True}
        assert opts["rowsFrame"] == {"layout": "auto"}
        assert opts["showValue"] == "never"
        assert opts["tooltip"] == {"mode": "single", "yHistogram": False,
                                   "showColorScale": False}
        assert opts["yAxis"] == {"axisPlacement": "left", "reverse": False,
                                 "unit": "short", "axisLabel": ""}

    def test_custom_options(self):
        panel = HeatmapPanel(
            "Heat", [Target(expr="m_bucket")], datasource_uid=DS_UID,
            unit="s", color_scheme="Blues", color_mode="opacity",
            color_steps=32, cell_gap=2, y_axis_label="Bucket",
            legend_show=False, tooltip_mode="multi", show_color_scale=True,
        )
        opts = panel.to_dict()["options"]
        assert opts["color"]["scheme"] == "Blues"
        assert opts["color"]["mode"] == "opacity"
        assert opts["color"]["steps"] == 32
        assert opts["cellGap"] == 2
        assert opts["legend"] == {"show": False}
        assert opts["tooltip"]["mode"] == "multi"
        assert opts["tooltip"]["showColorScale"] is True
        assert opts["yAxis"]["unit"] == "s"
        assert opts["yAxis"]["axisLabel"] == "Bucket"

    def test_field_config_is_not_timeseries_shaped(self):
        """A heatmap has none of the time series drawing options."""
        panel = HeatmapPanel("Heat", [Target(expr="m_bucket")],
                             datasource_uid=DS_UID)
        custom = panel.to_dict()["fieldConfig"]["defaults"]["custom"]
        for key in ("drawStyle", "lineWidth", "fillOpacity", "stacking",
                    "thresholdsStyle", "pointSize", "showPoints"):
            assert key not in custom
        assert custom["scaleDistribution"] == {"type": "linear"}
        assert panel.to_dict()["fieldConfig"]["overrides"] == []

    def test_auto_ref_ids(self):
        panel = HeatmapPanel("Heat", [Target(expr="a"), Target(expr="b")],
                             datasource_uid=DS_UID)
        assert [t.ref_id for t in panel.targets] == ["A", "B"]


class TestXYChartPanel:

    def test_type_and_manual_mapping(self):
        """Without "manual", Grafana picks fields itself and ignores the
        matchers below it."""
        panel = XYChartPanel("Scatter", [LokiTarget(expr='{job="x"}')],
                             x_field="time", y_field="distance",
                             datasource_uid=DS_UID)
        d = panel.to_dict()
        assert d["type"] == "xychart"
        assert d["options"]["mapping"] == "manual"

    def test_field_matchers(self):
        panel = XYChartPanel("Scatter", [LokiTarget(expr='{job="x"}')],
                             x_field="time", y_field="distance",
                             datasource_uid=DS_UID)
        series = panel.to_dict()["options"]["series"]
        assert len(series) == 1
        assert series[0]["x"] == {"matcher": {"id": "byName",
                                              "options": "time"}}
        assert series[0]["y"] == {"matcher": {"id": "byName",
                                              "options": "distance"}}

    def test_no_color_matcher_when_color_field_unset(self):
        panel = XYChartPanel("Scatter", [LokiTarget(expr='{job="x"}')],
                             x_field="time", y_field="distance",
                             datasource_uid=DS_UID)
        assert "color" not in panel.to_dict()["options"]["series"][0]

    def test_color_matcher_when_color_field_set(self):
        panel = XYChartPanel("Scatter", [LokiTarget(expr='{job="x"}')],
                             x_field="time", y_field="distance",
                             color_field="energy", datasource_uid=DS_UID)
        assert panel.to_dict()["options"]["series"][0]["color"] == {
            "matcher": {"id": "byName", "options": "energy"}
        }

    def test_point_size_lives_in_field_config_not_options(self):
        """Grafana reads pointSize from fieldConfig; in options it is ignored."""
        panel = XYChartPanel("Scatter", [LokiTarget(expr='{job="x"}')],
                             x_field="time", y_field="distance",
                             point_size=9, datasource_uid=DS_UID)
        d = panel.to_dict()
        custom = d["fieldConfig"]["defaults"]["custom"]
        assert custom["pointSize"] == {"fixed": 9}
        assert "pointSize" not in d["options"]
        assert "pointSize" not in json.dumps(d["options"])

    def test_field_config_defaults(self):
        panel = XYChartPanel("Scatter", [LokiTarget(expr='{job="x"}')],
                             x_field="time", y_field="distance",
                             unit="km", y_axis_label="Distance",
                             datasource_uid=DS_UID)
        defaults = panel.to_dict()["fieldConfig"]["defaults"]
        assert defaults["unit"] == "km"
        assert defaults["custom"]["show"] == "points"
        assert defaults["custom"]["pointShape"] == "circle"
        assert defaults["custom"]["axisLabel"] == "Distance"

    def test_x_axis_label_absent_by_default(self):
        panel = XYChartPanel("Scatter", [LokiTarget(expr='{job="x"}')],
                             x_field="time", y_field="distance",
                             datasource_uid=DS_UID)
        assert panel.to_dict()["fieldConfig"]["overrides"] == []

    def test_x_axis_label_becomes_an_override_on_the_x_field(self):
        """Grafana has no panel-level x axis label; it is a field override."""
        panel = XYChartPanel("Scatter", [LokiTarget(expr='{job="x"}')],
                             x_field="time", y_field="distance",
                             x_axis_label="Time", datasource_uid=DS_UID)
        assert panel.to_dict()["fieldConfig"]["overrides"] == [{
            "matcher": {"id": "byName", "options": "time"},
            "properties": [{"id": "custom.axisLabel", "value": "Time"}]
        }]

    def test_show_legend_is_bound(self):
        panel = XYChartPanel("Scatter", [LokiTarget(expr='{job="x"}')],
                             x_field="time", y_field="distance",
                             show_legend=True, datasource_uid=DS_UID)
        assert panel.to_dict()["options"]["legend"]["showLegend"] is True

    def test_legend_hidden_by_default(self):
        panel = XYChartPanel("Scatter", [LokiTarget(expr='{job="x"}')],
                             x_field="time", y_field="distance",
                             datasource_uid=DS_UID)
        assert panel.to_dict()["options"]["legend"]["showLegend"] is False

    def test_transformations_are_carried_through(self):
        transformations = [{"id": "extractFields",
                            "options": {"source": "labels"}}]
        panel = XYChartPanel("Scatter", [LokiTarget(expr='{job="x"}')],
                             x_field="time", y_field="distance",
                             datasource_uid=DS_UID,
                             transformations=transformations)
        assert panel.to_dict()["transformations"] == transformations


class TestLogsPanel:

    def test_type(self):
        panel = LogsPanel("Logs", [LokiTarget(expr='{job="x"}')],
                          datasource_uid=DS_UID, datasource_type="loki")
        d = panel.to_dict()
        assert d["type"] == "logs"
        assert d["datasource"]["type"] == "loki"

    def test_default_options(self):
        panel = LogsPanel("Logs", [LokiTarget(expr='{job="x"}')],
                          datasource_uid=DS_UID)
        assert panel.to_dict()["options"] == {
            "dedupStrategy": "none",
            "enableLogDetails": True,
            "prettifyLogMessage": False,
            "showCommonLabels": False,
            "showLabels": False,
            "showLogContextToggle": False,
            "showTime": True,
            "sortOrder": "Descending",
            "wrapLogMessage": True,
        }

    def test_custom_options(self):
        panel = LogsPanel("Logs", [LokiTarget(expr='{job="x"}')],
                          datasource_uid=DS_UID, show_time=False,
                          wrap_log_message=False, sort_order="Ascending",
                          enable_log_details=False, show_labels=True)
        opts = panel.to_dict()["options"]
        assert opts["showTime"] is False
        assert opts["wrapLogMessage"] is False
        assert opts["sortOrder"] == "Ascending"
        assert opts["enableLogDetails"] is False
        assert opts["showLabels"] is True

    def test_all_required_options_present(self):
        """Grafana's schema marks these nine non-optional."""
        panel = LogsPanel("Logs", [LokiTarget(expr='{job="x"}')],
                          datasource_uid=DS_UID)
        for key in ("showLabels", "showCommonLabels", "showTime",
                    "showLogContextToggle", "wrapLogMessage",
                    "prettifyLogMessage", "enableLogDetails", "sortOrder",
                    "dedupStrategy"):
            assert key in panel.to_dict()["options"]

    def test_field_config_is_minimal(self):
        panel = LogsPanel("Logs", [LokiTarget(expr='{job="x"}')],
                          datasource_uid=DS_UID)
        assert panel.to_dict()["fieldConfig"] == {"defaults": {},
                                                  "overrides": []}
