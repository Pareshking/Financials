"""X354: owner decision 2026-11-20 on exchange request rates, from a measured probe with no refusals."""

from types import SimpleNamespace

from financials.cli import ARCHIVE_RPS, archive_limits, build_parser


def test_default_rates_are_the_probed_owner_decision():
    args = build_parser().parse_args(["run-day"])
    assert args.archive_rps == ARCHIVE_RPS == 12.0
    limits = archive_limits(args)
    assert limits["nsearchives.nseindia.com"] == (12.0, 12)
    assert limits["www.nseindia.in"] == (2.0, 3)


def test_api_limit_holds_even_when_the_archive_runs_at_the_base_rate():
    assert archive_limits(SimpleNamespace(archive_rps=1.0)) == {"www.nseindia.in": (2.0, 3)}
