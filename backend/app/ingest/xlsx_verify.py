"""Cross-check of stored Lotto draws against the official statistics file.

The page https://www.loterie-nationale.be/nos-jeux/lotto/resultats-tirage/statistiques
offers a monthly-updated Excel file (sheet "Résultats") listing every draw since
1978. It is an independent official publication, so a draw that matches both
the JSON API and this file is marked as *verified*.

The file name changes every month (e.g. `statistiques-lotto-10-26.xlsx`), so
the link is discovered on the page, then restricted to the official host and
to the expected path prefix.
"""
from __future__ import annotations

import io
import logging
import re
import zipfile
from datetime import date, datetime

import httpx

from .natlot import TIMEOUT, USER_AGENT, SourceError

log = logging.getLogger(__name__)

HOST = "https://www.loterie-nationale.be"
STATS_PAGE = HOST + "/nos-jeux/lotto/resultats-tirage/statistiques"
LINK_RE = re.compile(r"/content/dam/opp/draw-games/lotto/brand-assets/documents/fr/statistiques-lotto-[\w\-]+\.xlsx")
MAX_PAGE_BYTES = 4 * 1024 * 1024
MAX_XLSX_BYTES = 10 * 1024 * 1024
MAX_UNCOMPRESSED = 80 * 1024 * 1024  # zip-bomb guard


def _download(client: httpx.Client, url: str, limit: int) -> bytes:
    try:
        with client.stream("GET", url) as resp:
            if resp.status_code != 200:
                raise SourceError(f"site officiel: HTTP {resp.status_code}")
            buf, size = [], 0
            for chunk in resp.iter_bytes():
                size += len(chunk)
                if size > limit:
                    raise SourceError("site officiel: fichier trop volumineux")
                buf.append(chunk)
            return b"".join(buf)
    except httpx.HTTPError as exc:
        raise SourceError(f"site officiel injoignable ({exc.__class__.__name__})") from exc


def find_xlsx_url(page_html: str) -> str:
    m = LINK_RE.search(page_html)
    if not m:
        raise SourceError("lien du fichier de statistiques introuvable sur la page officielle")
    return HOST + m.group(0)


def parse_results_sheet(content: bytes) -> dict[date, tuple[list[int], int]]:
    """Parse the "Résultats" sheet: {draw date: (6 sorted numbers, bonus)}.

    Only the 45-number era (2011+) is kept, which is the current game.
    """
    import openpyxl  # imported lazily: heavy

    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        if sum(i.file_size for i in zf.infolist()) > MAX_UNCOMPRESSED:
            raise SourceError("fichier de statistiques suspect (taille décompressée)")
    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    if "Résultats" not in wb.sheetnames:
        raise SourceError("onglet 'Résultats' absent du fichier officiel")
    out: dict[date, tuple[list[int], int]] = {}
    for row in wb["Résultats"].iter_rows(values_only=True):
        if not row or not isinstance(row[0], datetime):
            continue
        vals = row[1:8]
        if any(not isinstance(v, (int, float)) for v in vals):
            continue
        nums = sorted(int(v) for v in vals[:6])
        if max(nums) > 45 or len(set(nums)) != 6:
            continue
        d = row[0].date()
        if d.year < 2011:
            continue
        out.setdefault(d, (nums, int(vals[6])))
    wb.close()
    return out


def fetch_official_results(client: httpx.Client | None = None) -> tuple[str, dict[date, tuple[list[int], int]]]:
    own = client is None
    client = client or httpx.Client(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=False)
    try:
        page = _download(client, STATS_PAGE, MAX_PAGE_BYTES).decode("utf-8", errors="replace")
        url = find_xlsx_url(page)
        return url, parse_results_sheet(_download(client, url, MAX_XLSX_BYTES))
    finally:
        if own:
            client.close()
