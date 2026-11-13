"""Pure parsers: bytes in, typed rows out. No I/O, no database access."""


class ParseError(ValueError):
    """The file is not in the expected format. Caller quarantines it."""
