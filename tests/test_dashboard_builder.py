"""Tests for the dashboard_builder module."""
import json

from grafana_cdktf_helpers.dashboard_builder import (
    GridPosition,
    ThresholdStep,
    Override,
    Target,
    FieldConfig,
    Panel,
    TimeseriesPanel,
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
        # Expanded rows emit empty dicts for panel slots
        assert d["panels"] == [{}]

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
