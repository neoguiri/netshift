"""Met à jour assets/oui.tsv.gz (préfixes MAC → fabricant) depuis le registre public de l'IEEE.

Usage :  python scripts/update_oui.py [fichier_oui.csv]
Sans argument, télécharge https://standards-oui.ieee.org/oui/oui.csv (registre MA-L, préfixes 24 bits).
L'application n'accède jamais au réseau pour cela : elle lit uniquement le fichier embarqué.
"""
import csv
import gzip
import io
import sys
import urllib.request
from pathlib import Path

URL = "https://standards-oui.ieee.org/oui/oui.csv"
OUT = Path(__file__).resolve().parent.parent / "assets" / "oui.tsv.gz"


def clean(name: str) -> str:
    name = " ".join(name.split())
    for suffix in (", Inc.", " Inc.", ", Ltd.", " Ltd.", " Co.,Ltd.", " Co., Ltd.", " Corporation", " Corp.",
                   " GmbH", " S.A.", " AG", " LLC", " B.V.", " Limited"):
        if name.endswith(suffix) and len(name) > len(suffix) + 2:
            name = name[: -len(suffix)].rstrip(" ,")
    return name


def main():
    if len(sys.argv) > 1:
        text = Path(sys.argv[1]).read_text(encoding="utf-8")
    else:
        req = urllib.request.Request(URL, headers={"User-Agent": "NetShift OUI updater"})
        with urllib.request.urlopen(req, timeout=60) as r:
            text = r.read().decode("utf-8")
    rows = {}
    for row in csv.DictReader(io.StringIO(text)):
        prefix = (row.get("Assignment") or "").strip().upper()
        name = clean(row.get("Organization Name") or "")
        if len(prefix) == 6 and name:
            rows[prefix] = name
    data = "".join(f"{p}\t{n}\n" for p, n in sorted(rows.items())).encode("utf-8")
    OUT.write_bytes(gzip.compress(data, compresslevel=9, mtime=0))
    print(f"{len(rows)} préfixes -> {OUT} ({OUT.stat().st_size // 1024} Ko)")


if __name__ == "__main__":
    main()
