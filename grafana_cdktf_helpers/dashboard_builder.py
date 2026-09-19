"""
Pythonic dashboard builder for Grafana dashboards.

This module provides a clean, type-safe way to build Grafana dashboards
programmatically without the need for fluent interfaces or method chaining.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Union
import json
import re

from grafana_cdktf_helpers.utils import build_all_annotations_query


@dataclass
class GridPosition:
    """Position and size of a panel in the dashboard grid."""
    h: int = 8
    w: int = 12
    x: int = 0
    y: int = 0


@dataclass
class ThresholdStep:
    """A single threshold step for field configuration."""
    color: str
    value: Optional[float] = None


@dataclass
class Override:
    """Field override for specific series matching."""
    matcher_id: str
    matcher_options: Union[str, Dict[str, Any]]
    properties: List[Dict[str, Any]]


@dataclass
class Target:
    """Query target for a panel, Prometheus unless told otherwise."""
    expr: str
    legend_format: str = "{{friendly_name}}"
    ref_id: str = "A"
    interval: str = ""
    hide: bool = False
    instant: bool = False
    # None means "unset", so an explicit "prometheus" can be told apart from a
    # target that simply never said. What gets emitted still falls back to
    # "prometheus", so the default output is unchanged.
    datasource_type: Optional[str] = None
    # "heatmap", "table", "time_series"... Omitted from the emitted JSON
    # entirely when None: hundreds of existing targets do not carry the key,
    # and adding it to all of them would churn every dashboard's JSON.
    format: Optional[str] = None

    def resolve_datasource_type(self, panel_type: Optional[str] = None) -> str:
        """Pick the datasource type to emit.

        A target that states its own type keeps it; one that said nothing
        inherits the panel's. That is what lets a plain ``Target`` sit on a
        Loki panel without repeating the type on every query, while a target
        deliberately set to ``"prometheus"`` stays Prometheus even there.
        """
        return self.datasource_type or panel_type or "prometheus"

    def to_dict(self, datasource_uid: str,
                datasource_type: Optional[str] = None) -> Dict[str, Any]:
        """Convert to Grafana JSON format."""
        target_dict = {
            "datasource": {
                "type": self.resolve_datasource_type(datasource_type),
                "uid": datasource_uid
            },
            "editorMode": "code",
            "expr": self.expr,
            "instant": self.instant,
            "legendFormat": self.legend_format,
            "range": not self.instant,
            "refId": self.ref_id,
            "hide": self.hide,
            "interval": self.interval
        }
        if self.format is not None:
            target_dict["format"] = self.format
        return target_dict


@dataclass
class LokiTarget(Target):
    """LogQL query target against a Loki datasource.

    ``legend_format`` defaults to empty rather than the Prometheus-shaped
    ``{{friendly_name}}``: a log stream carries no such label, so the default
    would render as literal text.
    """
    legend_format: str = ""
    datasource_type: str = "loki"
    query_type: str = "range"
    max_lines: Optional[int] = None

    def to_dict(self, datasource_uid: str,
                datasource_type: Optional[str] = None) -> Dict[str, Any]:
        """Convert to Grafana JSON format."""
        target_dict = super().to_dict(datasource_uid, datasource_type)
        target_dict["queryType"] = self.query_type
        if self.max_lines is not None:
            target_dict["maxLines"] = self.max_lines
        return target_dict


@dataclass
class FieldConfig:
    """Field configuration for panel visualization."""
    unit: str = "short"
    thresholds: List[ThresholdStep] = field(default_factory=lambda: [
        ThresholdStep("green"),
        ThresholdStep("red", 80)
    ])
    color_mode: str = "palette-classic"
    fill_opacity: int = 0
    line_width: int = 1
    gradient_mode: str = "none"
    axis_label: str = ""
    overrides: List[Override] = field(default_factory=list)
    draw_style: str = "line"
    stacking_mode: str = "none"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to Grafana JSON format."""
        threshold_steps = []
        for threshold in self.thresholds:
            step = {"color": threshold.color}
            if threshold.value is not None:
                step["value"] = threshold.value
            else:
                step["value"] = None
            threshold_steps.append(step)

        override_list = []
        for override in self.overrides:
            override_dict = {
                "matcher": {
                    "id": override.matcher_id,
                    "options": override.matcher_options
                },
                "properties": override.properties
            }
            override_list.append(override_dict)

        return {
            "defaults": {
                "color": {"mode": self.color_mode},
                "custom": {
                    "axisCenteredZero": False,
                    "axisColorMode": "text",
                    "axisLabel": self.axis_label,
                    "axisPlacement": "auto",
                    "barAlignment": 0,
                    "drawStyle": self.draw_style,
                    "fillOpacity": self.fill_opacity,
                    "gradientMode": self.gradient_mode,
                    "hideFrom": {
                        "legend": False,
                        "tooltip": False,
                        "viz": False
                    },
                    "lineInterpolation": "linear",
                    "lineWidth": self.line_width,
                    "pointSize": 5,
                    "scaleDistribution": {"type": "linear"},
                    "showPoints": "auto",
                    "spanNulls": False,
                    "stacking": {
                        "group": "A",
                        "mode": self.stacking_mode
                    },
                    "thresholdsStyle": {"mode": "off"}
                },
                "mappings": [],
                "thresholds": {
                    "mode": "absolute",
                    "steps": threshold_steps
                },
                "unit": self.unit
            },
            "overrides": override_list
        }


def _assign_ref_ids(targets: List[Target]) -> None:
    """Give each target after the first a distinct refId.

    A target that set its own refId keeps it; only ones still carrying the
    ``"A"`` default are renamed.
    """
    ref_ids = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    for i, target in enumerate(targets):
        if target.ref_id == "A" and i > 0:  # Default wasn't changed
            target.ref_id = ref_ids[i]


class Panel:
    """Base class for all panel types."""

    def __init__(self, title: str, panel_type: str,
                 grid_pos: Optional[GridPosition] = None,
                 datasource_uid: Optional[str] = None,
                 description: str = "",
                 fixed_id: Optional[int] = None,
                 datasource_type: Optional[str] = None,
                 transformations: Optional[List[Dict[str, Any]]] = None):
        self.title = title
        self.type = panel_type
        self.grid_pos = grid_pos or GridPosition()
        self.datasource_uid = datasource_uid
        # Left None so Dashboard can tell "unset" from a deliberate
        # "prometheus" and fill only the former.
        self.datasource_type = datasource_type
        self.transformations = transformations
        self.description = description
        self.targets: List[Target] = []
        self.id: Optional[int] = None
        self.fixed_id = fixed_id  # For panels that need specific IDs (e.g., for alert references)
        self._auto_id_counter = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert panel to Grafana JSON format."""
        panel_dict = {
            "datasource": {
                "type": self.datasource_type or "prometheus",
                "uid": self.datasource_uid
            },
            "description": self.description,
            "gridPos": {
                "h": self.grid_pos.h,
                "w": self.grid_pos.w,
                "x": self.grid_pos.x,
                "y": self.grid_pos.y
            },
            "id": self.id,
            "title": self.title,
            "type": self.type,
            "targets": [
                target.to_dict(self.datasource_uid, self.datasource_type)
                for target in self.targets
            ]
        }
        # Emitted only when there is something to emit. An always-present
        # "transformations": [] would change the JSON of every existing panel,
        # which both drowns out the real diff when a consuming project checks a
        # library upgrade and forces the provider to re-send every dashboard --
        # and a full re-send is what strips the panel ids alert links use.
        if self.transformations:
            panel_dict["transformations"] = self.transformations
        return panel_dict


class TimeseriesPanel(Panel):
    """Time series panel for displaying metrics over time."""

    def __init__(self, title: str, targets: List[Target],
                 field_config: Optional[FieldConfig] = None,
                 legend_calcs: Optional[List[str]] = None,
                 **kwargs):
        super().__init__(title, "timeseries", **kwargs)
        self.targets = targets
        self.field_config = field_config or FieldConfig()
        self.legend_calcs = legend_calcs or []

        _assign_ref_ids(self.targets)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to Grafana JSON format."""
        panel_dict = super().to_dict()
        panel_dict["fieldConfig"] = self.field_config.to_dict()
        panel_dict["options"] = {
            "legend": {
                "calcs": self.legend_calcs,
                "displayMode": "list",
                "placement": "bottom",
                "showLegend": True
            },
            "tooltip": {
                "mode": "single",
                "sort": "none"
            }
        }
        return panel_dict


class HeatmapPanel(Panel):
    """Heatmap panel for data that is already bucketed.

    Option names follow Grafana's heatmap panel schema. Pair this with a
    ``Target`` carrying ``format="heatmap"`` so the datasource returns bucket
    series rather than plain time series.
    """

    def __init__(self, title: str, targets: List[Target],
                 unit: str = "short",
                 color_scheme: str = "Oranges",
                 color_mode: str = "scheme",
                 color_steps: int = 64,
                 cell_gap: int = 1,
                 y_axis_label: str = "",
                 legend_show: bool = True,
                 tooltip_mode: str = "single",
                 show_color_scale: bool = False,
                 **kwargs):
        super().__init__(title, "heatmap", **kwargs)
        self.targets = targets
        self.unit = unit
        self.color_scheme = color_scheme
        self.color_mode = color_mode
        self.color_steps = color_steps
        self.cell_gap = cell_gap
        self.y_axis_label = y_axis_label
        self.legend_show = legend_show
        self.tooltip_mode = tooltip_mode
        self.show_color_scale = show_color_scale

        _assign_ref_ids(self.targets)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to Grafana JSON format."""
        panel_dict = super().to_dict()
        panel_dict["fieldConfig"] = {
            "defaults": {
                "custom": {
                    "hideFrom": {
                        "legend": False,
                        "tooltip": False,
                        "viz": False
                    },
                    "scaleDistribution": {"type": "linear"}
                }
            },
            "overrides": []
        }
        panel_dict["options"] = {
            # Forced off, and stated explicitly even though it matches
            # Grafana's own default: the series arrive already bucketed from a
            # histogram, so letting Grafana bucket them again would silently
            # produce a wrong picture. An explicit False also survives someone
            # editing the panel in the UI and re-exporting it.
            "calculate": False,
            "calculation": {},
            "cellGap": self.cell_gap,
            "color": {
                "mode": self.color_mode,
                "scheme": self.color_scheme,
                "fill": "dark-orange",
                "scale": "exponential",
                "exponent": 0.5,
                "steps": self.color_steps,
                "reverse": False
            },
            "exemplars": {"color": "rgba(255,0,255,0.7)"},
            "filterValues": {"le": 1e-9},
            "legend": {"show": self.legend_show},
            "rowsFrame": {"layout": "auto"},
            "showValue": "never",
            "tooltip": {
                "mode": self.tooltip_mode,
                "yHistogram": False,
                "showColorScale": self.show_color_scale
            },
            "yAxis": {
                "axisPlacement": "left",
                "reverse": False,
                "unit": self.unit,
                "axisLabel": self.y_axis_label
            }
        }
        return panel_dict


class XYChartPanel(Panel):
    """Scatter (XY) panel plotting one named field against another.

    Field selection is explicit: ``mapping`` is set to ``"manual"`` because
    under Grafana's ``"auto"`` default the panel picks fields itself and the
    matchers below are never consulted.
    """

    def __init__(self, title: str, targets: List[Target],
                 x_field: str, y_field: str,
                 color_field: Optional[str] = None,
                 point_size: int = 5,
                 x_axis_label: str = "",
                 y_axis_label: str = "",
                 unit: str = "short",
                 show_legend: bool = False,
                 **kwargs):
        super().__init__(title, "xychart", **kwargs)
        self.targets = targets
        self.x_field = x_field
        self.y_field = y_field
        self.color_field = color_field
        self.point_size = point_size
        self.x_axis_label = x_axis_label
        self.y_axis_label = y_axis_label
        self.unit = unit
        self.show_legend = show_legend

        _assign_ref_ids(self.targets)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to Grafana JSON format."""
        panel_dict = super().to_dict()

        series: Dict[str, Any] = {
            "x": {"matcher": {"id": "byName", "options": self.x_field}},
            "y": {"matcher": {"id": "byName", "options": self.y_field}}
        }
        if self.color_field is not None:
            series["color"] = {
                "matcher": {"id": "byName", "options": self.color_field}
            }

        # The panel-wide axisLabel belongs to the y axis. An x axis label has
        # to be an override on the x field itself -- Grafana has no second
        # panel-level key for it -- so it is emitted only when asked for,
        # leaving the overrides list empty in the common case.
        overrides: List[Dict[str, Any]] = []
        if self.x_axis_label:
            overrides.append({
                "matcher": {"id": "byName", "options": self.x_field},
                "properties": [
                    {"id": "custom.axisLabel", "value": self.x_axis_label}
                ]
            })

        panel_dict["fieldConfig"] = {
            "defaults": {
                "custom": {
                    "show": "points",
                    # Grafana reads point size from fieldConfig, not from
                    # options -- it is silently ignored there.
                    "pointSize": {"fixed": self.point_size},
                    "pointShape": "circle",
                    "pointStrokeWidth": 1,
                    "axisPlacement": "auto",
                    "axisLabel": self.y_axis_label,
                    "hideFrom": {
                        "legend": False,
                        "tooltip": False,
                        "viz": False
                    },
                    "scaleDistribution": {"type": "linear"}
                },
                "unit": self.unit
            },
            "overrides": overrides
        }
        panel_dict["options"] = {
            "mapping": "manual",
            "series": [series],
            "legend": {
                "calcs": [],
                "displayMode": "list",
                "placement": "bottom",
                "showLegend": self.show_legend
            },
            "tooltip": {
                "mode": "single",
                "sort": "none"
            }
        }
        return panel_dict


class LogsPanel(Panel):
    """Logs panel rendering raw log lines.

    All nine options Grafana's schema marks non-optional are always emitted;
    the five that nobody here needs to vary are constants rather than
    parameters.
    """

    def __init__(self, title: str, targets: List[Target],
                 show_time: bool = True,
                 wrap_log_message: bool = True,
                 sort_order: str = "Descending",
                 enable_log_details: bool = True,
                 show_labels: bool = False,
                 **kwargs):
        super().__init__(title, "logs", **kwargs)
        self.targets = targets
        self.show_time = show_time
        self.wrap_log_message = wrap_log_message
        self.sort_order = sort_order
        self.enable_log_details = enable_log_details
        self.show_labels = show_labels

        _assign_ref_ids(self.targets)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to Grafana JSON format."""
        panel_dict = super().to_dict()
        panel_dict["fieldConfig"] = {"defaults": {}, "overrides": []}
        panel_dict["options"] = {
            "dedupStrategy": "none",
            "enableLogDetails": self.enable_log_details,
            "prettifyLogMessage": False,
            "showCommonLabels": False,
            "showLabels": self.show_labels,
            "showLogContextToggle": False,
            "showTime": self.show_time,
            "sortOrder": self.sort_order,
            "wrapLogMessage": self.wrap_log_message
        }
        return panel_dict


class Row:
    """Represents a collapsible row section in the dashboard."""

    def __init__(self, title: str, collapsed: bool = False):
        self.title = title
        self.collapsed = collapsed
        self.panels: List[Panel] = []
        self.grid_pos: Optional[GridPosition] = None
        self.id: Optional[int] = None

    def add_panel(self, panel: Panel) -> Panel:
        """Add a panel to this row."""
        self.panels.append(panel)
        return panel

    def to_dict(self) -> Dict[str, Any]:
        """Convert row to Grafana JSON format."""
        return {
            "collapsed": self.collapsed,
            "gridPos": {
                "h": self.grid_pos.h if self.grid_pos else 1,
                "w": self.grid_pos.w if self.grid_pos else 24,
                "x": self.grid_pos.x if self.grid_pos else 0,
                "y": self.grid_pos.y if self.grid_pos else 0
            },
            "id": self.id,
            # Grafana nests panels inside a row's `panels` array only when the row
            # is collapsed; for an expanded row the array must be empty (the panels
            # live at the dashboard top level). Emitting `{}` stubs here rendered as
            # phantom "No data" panels under Grafana 12/13's new dashboard engine.
            "panels": [panel.to_dict() for panel in self.panels] if self.collapsed else [],
            "title": self.title,
            "type": "row"
        }


class RowContext:
    """Context manager for adding panels to a row."""

    def __init__(self, dashboard: Dashboard, title: str, collapsed: bool):
        self.dashboard = dashboard
        self.row = Row(title, collapsed)

    def __enter__(self):
        return self.row

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.dashboard.rows.append(self.row)


@dataclass
class Annotation:
    """Dashboard annotation configuration."""
    name: str
    icon_color: str
    tags: List[str] = field(default_factory=list)
    enabled: bool = True

    def to_dict(self) -> Dict[str, Any]:
        """Convert to Grafana JSON format."""
        return {
            "datasource": {
                "type": "datasource",
                "uid": "grafana"
            },
            "enable": self.enabled,
            "iconColor": self.icon_color,
            "name": self.name,
            "target": {
                "limit": 100,
                "matchAny": False,
                "tags": self.tags,
                "type": "tags"
            }
        }


class Dashboard:
    """Main dashboard container."""

    def __init__(self, title: str, datasource_uid: str,
                 description: str = "", uid: Optional[str] = None,
                 dashboard_id: Optional[int] = None,
                 version: int = 1, schema_version: int = 38,
                 annotation_tags: Optional[List[str]] = None,
                 datasource_type: str = "prometheus"):
        self.title = title
        self.datasource_uid = datasource_uid
        self.datasource_type = datasource_type
        self.description = description
        self.uid = uid
        self.dashboard_id = dashboard_id
        self.version = version
        self.schema_version = schema_version
        self.annotation_tags: Optional[List[str]] = annotation_tags
        self.rows: List[Row] = []
        self.panels: List[Panel] = []  # For panels not in rows
        self.annotations: List[Annotation] = []
        self._id_counter = 1
        self._panel_title_to_id: Dict[str, int] = {}  # Registry for panel title -> ID mapping

    def add_row(self, title: str, collapsed: bool = False) -> Row:
        """Add a row to the dashboard."""
        row = Row(title, collapsed)
        self.rows.append(row)
        return row

    def row(self, title: str, collapsed: bool = False) -> RowContext:
        """Context manager for adding panels to a row."""
        return RowContext(self, title, collapsed)

    def id_for_panel(self, panel_title: str) -> Optional[int]:
        """Get the panel ID for a given panel title.

        Args:
            panel_title: The exact title of the panel to look up

        Returns:
            The panel ID if found, None otherwise
        """
        return self._panel_title_to_id.get(panel_title)

    def _assign_ids_and_positions(self):
        """Assign IDs and calculate grid positions for all panels and rows."""
        current_y = 0

        # First pass: collect all panels with fixed IDs to avoid conflicts
        used_fixed_ids = set()
        all_panels = []

        for row in self.rows:
            all_panels.extend(row.panels)
        all_panels.extend(self.panels)

        for panel in all_panels:
            if panel.fixed_id is not None:
                used_fixed_ids.add(panel.fixed_id)

        # Propagate datasource_uid and datasource_type to panels that don't
        # have one set. A panel that named its own keeps it -- that is how a
        # single Loki panel sits on an otherwise Prometheus dashboard.
        for panel in all_panels:
            if panel.datasource_uid is None:
                panel.datasource_uid = self.datasource_uid
            if panel.datasource_type is None:
                panel.datasource_type = self.datasource_type

        # Adjust ID counter to avoid conflicts with fixed IDs
        while self._id_counter in used_fixed_ids:
            self._id_counter += 1

        for row in self.rows:
            row.id = self._id_counter
            self._id_counter += 1
            while self._id_counter in used_fixed_ids:
                self._id_counter += 1

            row.grid_pos = GridPosition(h=1, w=24, x=0, y=current_y)
            current_y += 1  # Move past the row header

            # Position panels in this row
            current_x = 0
            row_height = 0
            panels_start_y = current_y  # Panels start after the row header

            # Group panels by their intended grid row based on x position pattern
            panel_grid_rows = []
            current_grid_row = []

            for panel in row.panels:
                # Detect row breaks: when we see x=0 after having other panels, start new row
                if panel.grid_pos.x == 0 and len(current_grid_row) > 0:
                    panel_grid_rows.append(current_grid_row)
                    current_grid_row = []
                current_grid_row.append(panel)

            # Add the last row
            if current_grid_row:
                panel_grid_rows.append(current_grid_row)

            # Position each grid row
            for grid_row in panel_grid_rows:
                for panel in grid_row:
                    # Use fixed ID if specified, otherwise assign next available
                    if panel.fixed_id is not None:
                        panel.id = panel.fixed_id
                    else:
                        panel.id = self._id_counter
                        self._id_counter += 1
                        while self._id_counter in used_fixed_ids:
                            self._id_counter += 1

                    # Register panel title -> ID mapping
                    self._panel_title_to_id[panel.title] = panel.id

                    # Auto-position if y is not explicitly set (y=0 means auto-position)
                    if panel.grid_pos.y == 0:
                        panel.grid_pos.y = panels_start_y
                        row_height = max(row_height, panel.grid_pos.h)

                # Move to next row after processing all panels in current grid row
                panels_start_y += row_height
                row_height = 0

            # Move current_y to after all panels in this row
            current_y = panels_start_y

        # Handle standalone panels
        for panel in self.panels:
            if panel.fixed_id is not None:
                panel.id = panel.fixed_id
            else:
                panel.id = self._id_counter
                self._id_counter += 1
                while self._id_counter in used_fixed_ids:
                    self._id_counter += 1

            # Register panel title -> ID mapping
            self._panel_title_to_id[panel.title] = panel.id

            if panel.grid_pos.y == 0:
                panel.grid_pos.y = current_y
                current_y += panel.grid_pos.h

    def to_json(self, variables: Optional[Dict[str, str]] = None) -> str:
        """Generate Grafana JSON for the dashboard."""
        self._assign_ids_and_positions()

        # Build annotations list
        annotations_list = [
            {
                "builtIn": 1,
                "datasource": {
                    "type": "grafana",
                    "uid": "-- Grafana --"
                },
                "enable": True,
                "hide": True,
                "iconColor": "rgba(0, 211, 255, 1)",
                "name": "Annotations & Alerts",
                "type": "dashboard"
            },
            build_all_annotations_query(self.annotation_tags),
        ]

        for annotation in self.annotations:
            annotations_list.append(annotation.to_dict())

        # Build panels list (rows + their panels)
        panels_list = []
        for row in self.rows:
            panels_list.append(row.to_dict())
            if not row.collapsed:
                panels_list.extend([panel.to_dict() for panel in row.panels])

        # Add standalone panels
        panels_list.extend([panel.to_dict() for panel in self.panels])

        dashboard_dict = {
            "annotations": {"list": annotations_list},
            "description": self.description,
            "editable": True,
            "fiscalYearStartMonth": 0,
            "graphTooltip": 0,
            "id": self.dashboard_id,
            "links": [],
            "liveNow": False,
            "panels": panels_list,
            "refresh": "",
            "schemaVersion": self.schema_version,
            "style": "dark",
            "tags": [],
            "templating": {"list": []},
            "time": {"from": "now-24h", "to": "now"},
            "timepicker": {},
            "timezone": "",
            "title": self.title,
            "uid": self.uid,
            "version": self.version,
            "weekStart": ""
        }

        json_str = json.dumps(dashboard_dict, indent=2)

        # Apply variable substitution if provided
        if variables:
            for var_name, var_value in variables.items():
                json_str = json_str.replace(f"!!!{var_name}!!!", var_value)

        return json_str


# Factory functions for common panel types
def temperature_panel(title: str, entity_pattern: str,
                     unit: str = "fahrenheit",
                     **kwargs) -> TimeseriesPanel:
    """Factory for temperature panels with common configuration."""
    if unit == "fahrenheit":
        expr = f"(hass_sensor_temperature_celsius{{entity=~\"({entity_pattern})\"}} * (9/5)) + 32"
    else:
        expr = f"hass_sensor_temperature_celsius{{entity=~\"({entity_pattern})\"}}"

    targets = [Target(expr=expr)]
    field_config = FieldConfig(unit=unit)

    return TimeseriesPanel(title, targets, field_config, **kwargs)


def humidity_panel(title: str, entity_pattern: str, **kwargs) -> TimeseriesPanel:
    """Factory for humidity panels."""
    targets = [Target(expr=f"hass_sensor_humidity_percent{{entity=~\"({entity_pattern})\"}}")]
    field_config = FieldConfig(unit="humidity")
    return TimeseriesPanel(title, targets, field_config, **kwargs)


def radon_panel(title: str, entities: List[str],
                with_thresholds: bool = True, **kwargs) -> TimeseriesPanel:
    """Factory for radon panels."""
    targets = []
    ref_ids = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

    for i, entity in enumerate(entities):
        targets.append(Target(
            expr=f"hass_sensor_unit_pci_per_l{{entity=\"{entity}\"}}",
            ref_id=ref_ids[i]
        ))

    field_config = FieldConfig(unit="none", axis_label="pCi/L")

    if with_thresholds:
        field_config.thresholds = [
            ThresholdStep("green"),
            ThresholdStep("#EAB839", 2),
            ThresholdStep("orange", 3),
            ThresholdStep("red", 4)
        ]
        field_config.color_mode = "thresholds"
        field_config.fill_opacity = 30
        field_config.gradient_mode = "scheme"

    return TimeseriesPanel(title, targets, field_config, **kwargs)
