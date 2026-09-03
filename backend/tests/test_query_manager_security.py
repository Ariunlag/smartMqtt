import pytest

from services.query_manager import QueryManager, _flux_string_literal


class CapturingInfluxClient:
    def __init__(self):
        self.queries = []

    def query_raw(self, flux):
        self.queries.append(flux)
        return []


def test_flux_string_literal_keeps_injection_text_inside_one_literal():
    malicious = 'x" or true or r._measurement=="y'

    literal = _flux_string_literal(malicious)

    assert literal.startswith('"') and literal.endswith('"')
    assert '\\" or true or r._measurement==\\"' in literal
    assert literal == '"x\\" or true or r._measurement==\\"y"'


@pytest.mark.asyncio
async def test_timeseries_escapes_measurement_names_before_building_flux():
    client = CapturingInfluxClient()
    manager = QueryManager()
    manager.client = client
    malicious = 'x" or true or r._measurement=="y'

    result = await manager.get_timeseries([malicious], start="-30d")

    assert result[0].measurement == malicious
    flux = client.queries[-1]
    assert f"r._measurement == {_flux_string_literal(malicious)}" in flux
    assert 'r._measurement == "x" or true' not in flux


@pytest.mark.asyncio
async def test_last_points_escapes_untrusted_mqtt_topic():
    client = CapturingInfluxClient()
    manager = QueryManager()
    manager.client = client
    malicious = 'building/a/") |> yield(name: "owned") //'

    result = await manager.get_last_points(malicious)

    assert result == []
    flux = client.queries[-1]
    assert f"r._measurement == {_flux_string_literal(malicious)}" in flux
    assert 'r._measurement == "building/a/")' not in flux
