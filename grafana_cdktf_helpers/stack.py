"""Base CDKTF stack for Grafana-managed infrastructure."""
import importlib.metadata
import json
import logging
import ssl
import urllib.error
import urllib.request
from typing import Optional

from constructs import Construct
from cdktf import TerraformStack
from imports.grafana.provider import GrafanaProvider
from imports.grafana.data_grafana_data_source import DataGrafanaDataSource


REQUIRED_CDKTF_VERSION = '0.21.0'

logger = logging.getLogger(__name__)


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
        self.grafana_url: str = grafana_url
        self.auth: Optional[str] = auth
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
        self.annotation_tags: list[str] = fetch_annotation_tags(
            self.grafana_url, self.auth
        )


def fetch_annotation_tags(
    grafana_url: str,
    auth: Optional[str] = None,
) -> list[str]:
    """Fetch all annotation tags from the Grafana API.

    Args:
        grafana_url: Base URL of the Grafana instance.
        auth: Optional Bearer token for authentication.

    Returns:
        A sorted, deduplicated list of tag strings. On any error
        (network, HTTP, JSON), logs a warning and returns an empty list
        so that synth can proceed even if Grafana is temporarily
        unreachable.
    """
    url = f'{grafana_url.rstrip("/")}/api/annotations/tags'
    req = urllib.request.Request(url)
    if auth is not None:
        req.add_header('Authorization', f'Bearer {auth}')
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        tags = sorted(set(
            item['tag']
            for item in data['result']['tags']
            if 'tag' in item
        ))
        logger.info(f'Fetched {len(tags)} annotation tags from Grafana')
        return tags
    except (urllib.error.URLError, urllib.error.HTTPError,
            json.JSONDecodeError, KeyError, OSError) as e:
        logger.warning(
            f'Failed to fetch annotation tags from Grafana: {e}'
        )
        return []
