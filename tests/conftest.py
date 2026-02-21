"""Test configuration - mock the cdktf-generated grafana imports."""
import sys
from unittest.mock import MagicMock


def create_mock_module(name):
    """Create a mock module and register it in sys.modules."""
    mock = MagicMock()
    sys.modules[name] = mock
    return mock


# Mock the cdktf-generated imports that live in each consuming project's
# imports/ directory. These are not available when testing the package
# standalone, so we mock them out.
_grafana_modules = [
    'imports',
    'imports.grafana',
    'imports.grafana.rule_group',
    'imports.grafana.folder',
    'imports.grafana.dashboard',
    'imports.grafana.provider',
    'imports.grafana.data_grafana_data_source',
]

for mod in _grafana_modules:
    create_mock_module(mod)

# Also mock cdktf and constructs if not installed
for mod in ['cdktf', 'constructs']:
    if mod not in sys.modules:
        create_mock_module(mod)
