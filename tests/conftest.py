from datetime import datetime
from pathlib import Path

import pytest

from _fixture_helpers import BHAV_DIR
from financials.db import apply_schema, connect
from financials.staging import stage_market_day
from financials.vault import Vault


def _share_cores_between_xdist_workers() -> None:
    """Under `pytest -n N`, each DuckDB connection gets cpu_count // N threads instead of one per core.

    DuckDB sizes its pool to every core per connection, so N workers ran N x cores threads on cores CPUs; the
    oversubscription cost ~30% more CPU and wall time (measured: 382 s -> 265 s CPU on the features-store and
    fast-path files with -n 4 on 4 cores). Results do not depend on the thread count. A serial run (and the benchmarks,
    which run alone) keep DuckDB's default; an explicit `threads` in a connect() config is kept."""
    import os

    workers = int(os.environ.get("PYTEST_XDIST_WORKER_COUNT") or 0)
    if workers < 2:
        return
    import duckdb

    threads = max(1, (os.cpu_count() or 1) // workers)
    real = duckdb.connect

    def connect(database=":memory:", read_only=False, config=None, **kw):
        return real(database, read_only=read_only, config={"threads": threads, **(config or {})}, **kw)

    duckdb.connect = connect


_share_cores_between_xdist_workers()

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


def _run_shared_dir(tmp_path_factory) -> Path:
    """A directory all xdist workers of this run share and no other run sees: the controller's base temp (a fresh
    `pytest-N`, or the --basetemp it wiped at start), whose `popen-gwK` children are the workers' base temps. Without
    xdist, this process's own base temp."""
    import os

    base = tmp_path_factory.getbasetemp()
    return (base.parent if os.environ.get("PYTEST_XDIST_WORKER") else base) / "shared_templates"


def shared_template(tmp_path_factory, key: str, build) -> tuple[Path, object]:
    """Build `build(root) -> extras` once per test run, for every xdist worker, and return (template root, extras).

    The template is a pure function of the code and fixtures of this run: it lives in this run's own temp tree
    (`_run_shared_dir`), so a later run (with changed src/ or fixtures) can never see it. A file lock makes one worker
    build while the others wait; a failed build leaves nothing behind, so the next caller builds (and fails) again.
    Callers must treat the template as read-only and work on a copy (`shared_market`)."""
    import fcntl
    import pickle
    import shutil

    shared = _run_shared_dir(tmp_path_factory)
    shared.mkdir(parents=True, exist_ok=True)
    final = shared / key
    with open(shared / f"{key}.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            if not (final / "extras.pickle").exists():
                work = shared / f"{key}.building"
                shutil.rmtree(work, ignore_errors=True)
                (work / "root").mkdir(parents=True)
                extras = build(work / "root")
                (work / "extras.pickle").write_bytes(pickle.dumps(extras))
                work.rename(final)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
    return final / "root", pickle.loads((final / "extras.pickle").read_bytes())


def market_template(tmp_path_factory, key: str, build) -> tuple[Path, dict]:
    """shared_template for a Market: `build(m: Market) -> dict | None` fills a fresh Market, whose connection is then
    closed. Returns (template root holding vault/, staging/ and market.duckdb; extras): the attributes the build set on
    the Market (e.g. `m.rows = ...`) plus the dict it returned, all picklable."""

    def run(root: Path) -> dict:
        m = Market(root)
        try:
            returned = build(m) or {}
        finally:
            m.con.close()
        return {k: v for k, v in vars(m).items() if k not in ("vault", "stage_root", "con")} | returned

    return shared_template(tmp_path_factory, key, run)


def shared_market(tmp_path_factory, key: str, build) -> "Market":
    """A Market on a private copy of the state market_template builds once per run (the dict's items become
    attributes of every copy)."""
    import shutil

    template, extras = market_template(tmp_path_factory, key, build)
    dest = tmp_path_factory.mktemp(key)
    shutil.copytree(template, dest, dirs_exist_ok=True)
    m = Market(dest)
    for name, value in extras.items():
        setattr(m, name, value)
    return m


@pytest.fixture
def market(tmp_path: Path) -> Market:
    m = Market(tmp_path)
    yield m
    m.con.close()


def build_full_market(root: Path) -> "Market":
    """Every real fixture through the real pipeline, in arrival order (shared by e2e/feature tests)."""
    m = Market(root)
    fill_full_market(m)
    return m


def full_market_copy(tmp_path_factory) -> "Market":
    """build_full_market on a private copy of the run's one build (shared_market)."""
    return shared_market(tmp_path_factory, "full_market", fill_full_market)


def full_market_db(tmp_path_factory, name: str) -> Path:
    """A private, closed copy of the run's one full-market database file (for modules that copy it per test)."""
    import shutil

    template, _ = market_template(tmp_path_factory, "full_market", fill_full_market)
    dest = tmp_path_factory.mktemp(name) / "market.duckdb"
    shutil.copy(template / "market.duckdb", dest)
    return dest


def fill_full_market(m: "Market") -> None:
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


@pytest.fixture(scope="session")
def full_market(tmp_path_factory) -> Market:
    m = full_market_copy(tmp_path_factory)
    yield m
    m.con.close()


def pytest_collection_modifyitems(config, items):
    """CI sharding: with TEST_SHARD="k/n" keep only shard k (1-based) of n. Whole files stay together (their
    module and session fixtures are built once per shard); files are assigned greedily by test count, heaviest
    first, so the split is deterministic for a given test set. Unset: every test runs."""
    import os

    spec = os.environ.get("TEST_SHARD")
    if not spec:
        return
    k, n = (int(x) for x in spec.split("/"))
    per_file: dict[str, int] = {}
    for it in items:
        per_file[it.nodeid.split("::")[0]] = per_file.get(it.nodeid.split("::")[0], 0) + 1
    load, owner = [0] * n, {}
    for f, c in sorted(per_file.items(), key=lambda x: (-x[1], x[0])):
        i = min(range(n), key=lambda j: (load[j], j))
        owner[f], load[i] = i, load[i] + c
    keep = [it for it in items if owner[it.nodeid.split("::")[0]] == k - 1]
    config.hook.pytest_deselected(items=[it for it in items if owner[it.nodeid.split("::")[0]] != k - 1])
    items[:] = keep
