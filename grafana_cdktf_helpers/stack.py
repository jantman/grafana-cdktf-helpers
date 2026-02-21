"""Base CDKTF stack for Grafana-managed infrastructure."""
import importlib.metadata
from typing import Optional

from constructs import Construct
from cdktf import TerraformStack
from imports.grafana.provider import GrafanaProvider
from imports.grafana.data_grafana_data_source import DataGrafanaDataSource


REQUIRED_CDKTF_VERSION = '0.21.0'


class BaseStack(TerraformStack):
    """
    Base CDKTF stack that sets up the Grafana provider and Prometheus
    data source. Consuming projects should subclass this and add their
    site-specific components.
    """

    def __init__(
        self,
        scope: Construct,
        ns: str,
        grafana_url: str,
        org_id: int = 1,
        auth: Optional[str] = None,
        prometheus_ds_name: str = 'prometheus',
        check_cdktf_version: bool = True,
    ):
        if check_cdktf_version:
            cdktf_ver = importlib.metadata.version('cdktf')
            if cdktf_ver != REQUIRED_CDKTF_VERSION:
                raise RuntimeError(
                    f'Error: This project requires cdktf '
                    f'{REQUIRED_CDKTF_VERSION} but is being run with '
                    f'{cdktf_ver}'
                )
        super().__init__(scope, ns)
        self.org_id: int = org_id
        provider_kwargs = {
            'insecure_skip_verify': True,
            'url': grafana_url,
        }
        if auth is not None:
            provider_kwargs['auth'] = auth
        provider = GrafanaProvider(self, 'grafana', **provider_kwargs)
        # as of cdktf 0.15.5, specifying this on the provider will result in
        # the synthesized JSON having a `x_disable_provenance` header
        provider.add_override(
            'http_headers', {'X-Disable-Provenance': 'true'}
        )
        self.prom: DataGrafanaDataSource = DataGrafanaDataSource(
            self, 'prom', name=prometheus_ds_name
        )
