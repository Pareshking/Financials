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
