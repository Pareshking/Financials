"""Pure parsers: bytes in, typed rows out. No I/O, no database access."""


class ParseError(ValueError):
    """The file is not in the expected format. Caller quarantines it."""


_ARCHIVE_ALIASES = ("https://nsearchives.nseindia.in/", "http://nsearchives.nseindia.in/")


def canonical_archive_url(url: str) -> str:
    """NSE serves the same archive under nsearchives.nseindia.in and .com: byte-identical files (sha256 checked on
    two XBRLs, 2026-11-15). From 15 Nov 2026 the listing APIs return the .in host. Filing ids and the fetch ledger
    key on the URL, so a host change would duplicate every filing and re-download vaulted files; one host is kept."""
    for alias in _ARCHIVE_ALIASES:
        if url.startswith(alias):
            return "https://nsearchives.nseindia.com/" + url[len(alias) :]
    return url
