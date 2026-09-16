"""
Loading and cleaning the master contact list.

The name cleaning here is not incidental. Every rule below traces to a real
defect in a real batch: credential suffixes sent as part of the greeting,
trailing commas, rows where First Name and Last Name are the same string,
bare initials, and name/address pairs that don't match.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import openpyxl

from .store import person_key

HEADER_ROW = 4          # row 4 holds the column names
FIRST_DATA_ROW = 5

# Credential and honorific noise that must never reach a greeting.
_SUFFIX = re.compile(
    r"\b(ccim|sior|cpm|mai|ccem|cre|rpa|fma|leed|ap|crs|gri|abr|sres|epro|"
    r"realtor|broker|esq|mba|phd|cfa|cpa|jd|md|clhms|ali|cbr|psa|rene|"
    r"jr|sr|ii|iii|iv|v)\b\.?",
    re.I,
)
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


@dataclass
class Contact:
    email: str
    first_raw: str | None
    last: str | None
    title: str | None
    company: str | None
    send_day: str | None
    city: str | None = None
    state: str | None = None
    row: int | None = None
    greeting_name: str | None = field(default=None, init=False)
    person_key: str = field(default="", init=False)
    warnings: list[str] = field(default_factory=list, init=False)

    def __post_init__(self):
        self.greeting_name = clean_first_name(self.first_raw, self.last)
        self.person_key = person_key(self.greeting_name or self.first_raw,
                                     self.last, self.email)
        self._audit()

    @property
    def greeting(self) -> str:
        return f"Hey {self.greeting_name}," if self.greeting_name else "Hey there,"

    @property
    def domain(self) -> str:
        return self.email.split("@")[-1].lower()

    def _audit(self):
        f = (self.first_raw or "").strip().lower()
        l = (self.last or "").strip().lower()
        if f and l and f == l:
            self.warnings.append("first name equals last name (corrupted row)")
        if not self.greeting_name:
            self.warnings.append("no usable first name; will send 'Hey there,'")
        # Name/address mismatch: neither name fragment appears in the local part.
        local = self.email.split("@")[0].lower()
        stripped = re.sub(r"[^a-z]", "", local)
        if f and l and len(stripped) > 3:
            if f[:3] not in stripped and l[:3] not in stripped:
                self.warnings.append(
                    f"name/address mismatch: '{self.first_raw} {self.last}' vs {self.email}")


def clean_first_name(first: str | None, last: str | None) -> str | None:
    """
    Reduce a messy First Name cell to something you can put after "Hey ".

    Returns None when there is nothing usable, which the caller turns into
    "Hey there,". Never returns a placeholder or an empty string.
    """
    if not first:
        return None
    s = str(first).strip()
    if not s or s.lower() in {"none", "n/a", "na", "-", "--"}:
        return None

    # "Sid Bhatt, CCIM" -> "Sid Bhatt";  "Debbie," -> "Debbie"
    s = s.split(",")[0]
    s = _SUFFIX.sub("", s)
    s = s.strip(" .,\t\r\n")
    if not s:
        return None

    parts = [p for p in re.split(r"\s+", s) if p]
    if not parts:
        return None

    cand = parts[0].strip(" .,")
    # "J. Peter" -> "Peter": a one- or two-character leading token is an initial.
    if len(cand.rstrip(".")) <= 2 and len(parts) > 1:
        nxt = parts[1].strip(" .,")
        if len(nxt) > 2:
            cand = nxt

    cand = cand.strip(" .,")
    if len(cand) < 2 or not re.search(r"[A-Za-z]", cand):
        return None

    # Normalize shouty or lowercase source data: "ROBERT"/"robert" -> "Robert".
    # Leave mixed case alone so "McKee" and "DiOrio" survive intact.
    if cand.isupper() or cand.islower():
        cand = cand[0].upper() + cand[1:].lower()
    return cand


def load_contacts(xlsx_path: str | Path, sheet: str = "Master List") -> list[Contact]:
    """Read the workbook and return every row with a syntactically valid email."""
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb[sheet]

    headers = {}
    for idx, cell in enumerate(next(ws.iter_rows(min_row=HEADER_ROW,
                                                 max_row=HEADER_ROW,
                                                 values_only=True))):
        if cell:
            headers[str(cell).strip().lower()] = idx

    def col(*names):
        for n in names:
            if n in headers:
                return headers[n]
        return None

    c_first = col("first name")
    c_last = col("last name")
    c_email = col("email")
    c_title = col("title")
    c_co = col("company")
    c_day = col("send day")
    c_city = col("city")
    c_state = col("state")

    if c_email is None:
        raise ValueError("No 'Email' column found in the header row")

    out: list[Contact] = []
    seen: set[str] = set()
    for n, row in enumerate(ws.iter_rows(min_row=FIRST_DATA_ROW, values_only=True),
                            start=FIRST_DATA_ROW):
        raw = row[c_email] if c_email < len(row) else None
        if not raw:
            continue
        email = str(raw).strip().lower()
        if not _EMAIL_RE.match(email) or email in seen:
            continue
        seen.add(email)

        def g(i):
            if i is None or i >= len(row) or row[i] is None:
                return None
            v = str(row[i]).strip()
            return v or None

        out.append(Contact(
            email=email,
            first_raw=g(c_first),
            last=g(c_last),
            title=g(c_title),
            company=g(c_co),
            send_day=g(c_day),
            city=g(c_city),
            state=g(c_state),
            row=n,
        ))
    wb.close()
    return out
