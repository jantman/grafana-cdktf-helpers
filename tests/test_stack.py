"""Tests for grafana_cdktf_helpers.stack."""
import json
import urllib.error
from unittest.mock import patch, MagicMock

from grafana_cdktf_helpers.stack import fetch_annotation_tags


def _mock_response(body: bytes):
    """Create a mock urllib response context manager."""
    resp = MagicMock()
    resp.read.return_value = body
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


class TestFetchAnnotationTags:

    def test_successful_fetch(self):
        api_response = json.dumps({
            "result": {
                "tags": [
                    {"tag": "deploy", "count": 5},
                    {"tag": "maintenance", "count": 2},
                    {"tag": "alert", "count": 1},
                ]
            }
        }).encode()
        with patch('urllib.request.urlopen',
                   return_value=_mock_response(api_response)):
            tags = fetch_annotation_tags('http://grafana:3000')
        assert tags == ['alert', 'deploy', 'maintenance']

    def test_duplicate_tags_deduplicated(self):
        api_response = json.dumps({
            "result": {
                "tags": [
                    {"tag": "deploy", "count": 3},
                    {"tag": "deploy", "count": 1},
                ]
            }
        }).encode()
        with patch('urllib.request.urlopen',
                   return_value=_mock_response(api_response)):
            tags = fetch_annotation_tags('http://grafana:3000')
        assert tags == ['deploy']

    def test_empty_tags_list(self):
        api_response = json.dumps(
            {"result": {"tags": []}}
        ).encode()
        with patch('urllib.request.urlopen',
                   return_value=_mock_response(api_response)):
            tags = fetch_annotation_tags('http://grafana:3000')
        assert tags == []

    def test_url_error_returns_empty(self):
        with patch('urllib.request.urlopen',
                   side_effect=urllib.error.URLError('connection refused')):
            tags = fetch_annotation_tags('http://grafana:3000')
        assert tags == []

    def test_http_error_returns_empty(self):
        with patch('urllib.request.urlopen',
                   side_effect=urllib.error.HTTPError(
                       'http://x', 401, 'Unauthorized', {}, None)):
            tags = fetch_annotation_tags('http://grafana:3000')
        assert tags == []

    def test_json_decode_error_returns_empty(self):
        with patch('urllib.request.urlopen',
                   return_value=_mock_response(b'not json')):
            tags = fetch_annotation_tags('http://grafana:3000')
        assert tags == []

    def test_trailing_slash_stripped(self):
        api_response = json.dumps(
            {"result": {"tags": []}}
        ).encode()
        with patch('urllib.request.urlopen',
                   return_value=_mock_response(api_response)) as mock_open:
            fetch_annotation_tags('http://grafana:3000/')
        req = mock_open.call_args[0][0]
        assert req.full_url == 'http://grafana:3000/api/annotations/tags'

    def test_auth_header_set_when_auth_provided(self):
        api_response = json.dumps(
            {"result": {"tags": []}}
        ).encode()
        with patch('urllib.request.urlopen',
                   return_value=_mock_response(api_response)) as mock_open:
            fetch_annotation_tags('http://grafana:3000', auth='my-api-key')
        req = mock_open.call_args[0][0]
        assert req.get_header('Authorization') == 'Bearer my-api-key'

    def test_no_auth_header_when_auth_none(self):
        api_response = json.dumps(
            {"result": {"tags": []}}
        ).encode()
        with patch('urllib.request.urlopen',
                   return_value=_mock_response(api_response)) as mock_open:
            fetch_annotation_tags('http://grafana:3000')
        req = mock_open.call_args[0][0]
        assert not req.has_header('Authorization')
