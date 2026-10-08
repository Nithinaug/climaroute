import pytest

from api import reports
from routing import heat_factor


@pytest.mark.parametrize(
    "temp, cloud, expected",
    [(25, 0, 0.0), (30, 0, 0.5), (34, 0, 1.0), (40, 0, 1.5), (34, 100, 0.2)],
)
def test_heat_factor(temp, cloud, expected):
    assert heat_factor(temp, cloud) == pytest.approx(expected)


def test_report_fades_after_first_hour():
    r = {"created_at": 0}
    assert reports.strength(r, 30 * 60) == 1.0
    assert reports.strength(r, 2 * 3600) == pytest.approx(0.5)
    assert reports.strength(r, 3 * 3600) == 0.0


def test_strengths_keep_strongest_report_per_street():
    rs = [{"edge_id": "e1", "created_at": 0}, {"edge_id": "e1", "created_at": 7200}]
    assert reports.strengths(rs, now=7200) == {"e1": 1.0}
