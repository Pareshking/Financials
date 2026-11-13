from datetime import datetime
from pathlib import Path

import pytest

from _fixture_helpers import BHAV_DIR
from financials.db import apply_schema, connect
from financials.staging import stage_market_day
from financials.vault import Vault

FETCHED_AT = datetime(2026, 11, 13, 9, 0, 0)
ARCHIVE = "https://nsearchives.nseindia.com"


def bhav_bytes(yyyymmdd: str) -> bytes:
    return (BHAV_DIR / f"BhavCopy_NSE_CM_0_0_0_{yyyymmdd}_F_0000.csv.zip").read_bytes()


def bhav_url(yyyymmdd: str) -> str:
    return f"{ARCHIVE}/content/cm/BhavCopy_NSE_CM_0_0_0_{yyyymmdd}_F_0000.csv.zip"


class Market:
    """A throwaway vault + staging area + market database under tmp_path."""

    def __init__(self, root: Path) -> None:
        self.vault = Vault(root / "vault")
        self.stage_root = root / "staging"
        self.con = connect(root / "market.duckdb")
        apply_schema(self.con)

    def stage_day(self, yyyymmdd: str, *, with_delivery: bool = False) -> Path:
        delivery = delivery_url = None
        if with_delivery:
            ddmmyyyy = yyyymmdd[6:] + yyyymmdd[4:6] + yyyymmdd[:4]
            delivery = (BHAV_DIR / f"sec_bhavdata_full_{ddmmyyyy}.csv").read_bytes()
            delivery_url = f"{ARCHIVE}/products/content/sec_bhavdata_full_{ddmmyyyy}.csv"
        return stage_market_day(
            self.vault,
            self.stage_root,
            bhavcopy=bhav_bytes(yyyymmdd),
            bhavcopy_url=bhav_url(yyyymmdd),
            delivery=delivery,
            delivery_url=delivery_url,
            fetched_at=FETCHED_AT,
        )

    def security_id(self, symbol: str) -> str:
        row = self.con.execute(
            "SELECT DISTINCT security_id FROM security_identifier_history WHERE symbol = ?", [symbol]
        ).fetchall()
        assert len(row) == 1, row
        return row[0][0]


@pytest.fixture
def market(tmp_path: Path) -> Market:
    m = Market(tmp_path)
    yield m
    m.con.close()


def build_full_market(root: Path) -> "Market":
    """Every real fixture through the real pipeline, in arrival order (shared by e2e/feature tests)."""
    from datetime import UTC

    from _fixture_helpers import CORP, FIXTURES, XBRL_DIR
    from financials.parsers.shareholding import parse_shp_master
    from financials.promoter import promote
    from financials.staging import (
        stage_corp_actions,
        stage_holidays,
        stage_index_snapshot,
        stage_results_xbrl,
        stage_shareholding,
    )

    m = Market(root)

    def ok(stage):
        r = promote(m.con, stage)
        assert r.status in ("PROMOTED", "QUARANTINED"), r
        return r

    ok(m.stage_day("20250919"))
    ca = FIXTURES / "corp_actions" / "nse_corporateActions_equities_15-09-2025_17-10-2025.json"
    ok(stage_corp_actions(m.vault, m.stage_root, data=ca.read_bytes(), source_url="nse-ca", fetched_at=FETCHED_AT))
    for d in ("20250922", "20250923", "20251013"):
        ok(m.stage_day(d))
    ok(m.stage_day("20251014", with_delivery=True))
    ok(m.stage_day("20261112", with_delivery=True))
    hol = FIXTURES / "calendar" / "nse_holiday-master_trading_20261113.json"
    ok(stage_holidays(m.vault, m.stage_root, data=hol.read_bytes(), source_url="nse-hol", fetched_at=FETCHED_AT))
    idx = FIXTURES / "indices" / "ind_nifty500list_20261113.csv"
    from datetime import date

    ok(
        stage_index_snapshot(
            m.vault,
            m.stage_root,
            data=idx.read_bytes(),
            source_url="nse-idx",
            index_name="NIFTY 500",
            snapshot_date=date(2026, 11, 12),
            fetched_at=FETCHED_AT,
        )
    )
    ok(
        stage_results_xbrl(
            m.vault, m.stage_root, data=CORP.read_bytes(), source_url="nse-xbrl-corp", fetched_at=FETCHED_AT
        )
    )
    master = parse_shp_master(
        (FIXTURES / "shareholding" / "nse_corporate-share-holdings-master_ELIN_20261113.json").read_bytes()
    )[0]
    ok(
        stage_shareholding(
            m.vault,
            m.stage_root,
            data=(XBRL_DIR / "SHP_1739151_15102026054406_WEB.xml").read_bytes(),
            source_url=master.xbrl_url,
            fetched_at=FETCHED_AT,
            broadcast_ts=master.broadcast_ts_ist.astimezone(UTC).replace(tzinfo=None),
            broadcast_ts_source="API_FIELD",
        )
    )
    return m


@pytest.fixture(scope="session")
def full_market(tmp_path_factory) -> Market:
    m = build_full_market(tmp_path_factory.mktemp("full_market"))
    yield m
    m.con.close()
