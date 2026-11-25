"""Shared helper for talking to SEC EDGAR - every module that calls SEC
(directory.py's bulk ticker file, filings.py's per-company submissions
API) needs the same compliant session: SEC's fair-access policy requires
a real, reachable contact in the User-Agent on every single request.
"""

import os
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path.home() / ".stocklookup.env")
load_dotenv()


class SecConfigError(Exception):
    pass


def get_session() -> requests.Session:
    contact = os.environ.get("SEC_CONTACT_EMAIL", "").strip()
    if not contact:
        raise SecConfigError(
            "SEC_CONTACT_EMAIL is not set. SEC requires a real, reachable "
            "contact in the User-Agent for every request to their servers - "
            'set it in ~/.stocklookup.env, e.g.:\n  SEC_CONTACT_EMAIL="Your Name your@email.com"'
        )
    session = requests.Session()
    session.headers.update({"User-Agent": f"stock-hub-personal-project ({contact})"})
    return session
