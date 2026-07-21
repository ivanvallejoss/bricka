from unittest.mock import patch, MagicMock

import httpx
import pytest
from django.core.cache import cache

from apps.common.geocoding import (
    geocode_address, GeocodeResult, GeocodeUnavailable, _RATE_LIMIT_KEY,
)


@pytest.fixture(autouse=True)
def _reset_gate():
    # el gate corre real contra la cache; se resetea el slot por test para
    # determinismo. Único mock del suite: el borde HTTP (httpx).
    cache.delete(_RATE_LIMIT_KEY)
    yield
    cache.delete(_RATE_LIMIT_KEY)


class TestGeocodeAddress:
    @patch("apps.common.geocoding.httpx.get")
    def test_returns_result_on_match(self, mock_get):
        resp = MagicMock()
        resp.json.return_value = [{
            "lat": "-27.4512", "lon": "-58.9866", "display_name": "Resistencia, Chaco",
        }]
        mock_get.return_value = resp
        assert geocode_address("Av. Sarmiento 100, Resistencia") == GeocodeResult(
            lat=-27.4512, lon=-58.9866, display_name="Resistencia, Chaco",
        )

    @patch("apps.common.geocoding.httpx.get")
    def test_returns_none_on_no_match(self, mock_get):
        resp = MagicMock()
        resp.json.return_value = []
        mock_get.return_value = resp
        assert geocode_address("dirección inexistente xyz") is None

    @patch("apps.common.geocoding.httpx.get", side_effect=httpx.TimeoutException("timeout"))
    def test_unavailable_on_timeout(self, mock_get):
        with pytest.raises(GeocodeUnavailable):
            geocode_address("Resistencia")

    @patch("apps.common.geocoding.httpx.get")
    def test_unavailable_on_http_error(self, mock_get):
        resp = MagicMock()
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500", request=MagicMock(), response=MagicMock())
        mock_get.return_value = resp
        with pytest.raises(GeocodeUnavailable):
            geocode_address("Resistencia")


class TestRateGate:
    @patch("apps.common.geocoding.httpx.get")
    def test_second_call_in_window_is_rejected(self, mock_get):
        # gate real: la 1ª entra; la 2ª choca contra el slot vivo y no llega a httpx.
        resp = MagicMock()
        resp.json.return_value = [{"lat": "-27.4", "lon": "-58.9", "display_name": "x"}]
        mock_get.return_value = resp

        assert geocode_address("Resistencia") is not None
        with pytest.raises(GeocodeUnavailable):
            geocode_address("Resistencia")
        assert mock_get.call_count == 1