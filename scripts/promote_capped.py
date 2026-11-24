"""Run the financials CLI with DuckDB capped at 6 GB of memory (container has ~8 GB; full promote/materialize OOM otherwise)."""
import sys, duckdb
_orig = duckdb.connect
def _connect(*a, **kw):
    con = _orig(*a, **kw)
    con.execute("SET memory_limit='6GB'")
    return con
duckdb.connect = _connect
from financials.cli import main
sys.exit(main(sys.argv[1:]))
