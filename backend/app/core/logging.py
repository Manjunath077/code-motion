import logging
import sys


def _utf8_stdout():
    """stdout that can print any character.

    On Windows, a redirected stdout (pipe, file, background process) defaults
    to cp1252, so log lines containing e.g. '→' or '—' raise UnicodeEncodeError
    inside logging and the line is lost. Switch the stream to UTF-8; anything
    still unencodable is escaped rather than dropped. Streams without
    reconfigure() (e.g. pytest's capture) are left as they are.
    """
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    except (AttributeError, ValueError):
        pass
    return sys.stdout


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(_utf8_stdout())
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger
