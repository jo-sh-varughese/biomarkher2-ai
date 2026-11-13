"""Fetch individual HER2match IHC slides from Zenodo's 15.5 GB IHC_slides.zip without downloading the whole archive.

    python scripts/fetch_her2match_slides.py [--ids 1 8 ...] [--out data/slides_source/HER2match_mrxs]

Reads the zip's central directory with HTTP range requests, then downloads only the members of the requested slides
(<id>.mrxs and <id>/Data*.dat, Index.dat, Slidedat.ini). Files already present with the right size are skipped, so
a rerun completes partial downloads. Slides go to <out>/score_<grade>/ using HER2match_scores.csv.
HER2match: Zenodo 10.5281/zenodo.15797050, CC BY-NC-SA 4.0.
"""
from __future__ import annotations

import argparse
import csv
import io
import struct
import sys
import time
import zlib
import zipfile
from pathlib import Path

import requests

URL = "https://zenodo.org/api/records/15797050/files/IHC_slides.zip/content"
SCORES = "https://zenodo.org/api/records/15797050/files/HER2match_scores.csv/content"


class HttpRangeFile(io.RawIOBase):
    """A seekable read-only file over HTTP range requests, enough for zipfile."""

    def __init__(self, url: str):
        self.session = requests.Session()
        r = self.session.head(url, allow_redirects=True, timeout=60)
        r.raise_for_status()
        self.url, self.size, self.pos = r.url, int(r.headers["Content-Length"]), 0

    def seekable(self):
        return True

    def readable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=io.SEEK_SET):
        self.pos = {io.SEEK_SET: 0, io.SEEK_CUR: self.pos, io.SEEK_END: self.size}[whence] + offset
        return self.pos

    def read(self, n=-1):
        if n is None or n < 0:
            n = self.size - self.pos
        if n == 0 or self.pos >= self.size:
            return b""
        end = min(self.pos + n, self.size) - 1
        for attempt in range(8):  # Zenodo drops long range reads now and then
            try:
                r = self.session.get(self.url, headers={"Range": f"bytes={self.pos}-{end}"}, timeout=300)
                r.raise_for_status()
                if len(r.content) == end - self.pos + 1:
                    break
            except (requests.RequestException, OSError):
                pass
            time.sleep(min(60, 2 ** attempt))
        else:
            raise IOError(f"range {self.pos}-{end} failed after 8 attempts")
        self.pos += len(r.content)
        return r.content

    def readinto(self, b):
        data = self.read(len(b))
        b[:len(data)] = data
        return len(data)


class Buffered(io.BufferedReader):
    pass


def fetch_member(raw: HttpRangeFile, m: zipfile.ZipInfo, dest: Path) -> None:
    """Stream one member's compressed bytes with a single resumable range request, then inflate and CRC-check.

    Many small range reads trip Zenodo's rate limit (133 requests/min) and stall; one long stream per file, resumed
    from the bytes already on disk after a dropped connection, does not.
    """
    raw.seek(m.header_offset)
    head = raw.read(30)
    start = m.header_offset + 30 + struct.unpack("<H", head[26:28])[0] + struct.unpack("<H", head[28:30])[0]
    end = start + m.compress_size - 1
    z = dest.with_suffix(dest.suffix + ".z")
    for attempt in range(30):
        have = z.stat().st_size if z.exists() else 0
        if have >= m.compress_size:
            break
        try:
            with raw.session.get(raw.url, headers={"Range": f"bytes={start + have}-{end}"}, stream=True, timeout=120) as r:
                if r.status_code == 429:
                    time.sleep(int(r.headers.get("Retry-After", 60)))
                    continue
                r.raise_for_status()
                with open(z, "ab") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
        except (requests.RequestException, OSError):
            time.sleep(min(60, 2 ** min(attempt, 6)))
    else:
        raise IOError(f"{m.filename}: download did not complete")
    tmp = dest.with_suffix(dest.suffix + ".part")
    crc = 0
    inflate = zlib.decompressobj(-15) if m.compress_type == zipfile.ZIP_DEFLATED else None
    with open(z, "rb") as src, open(tmp, "wb") as dst:
        while block := src.read(8 << 20):
            out = inflate.decompress(block) if inflate else block
            crc = zlib.crc32(out, crc)
            dst.write(out)
        if inflate:
            out = inflate.flush()
            crc = zlib.crc32(out, crc)
            dst.write(out)
    if crc != m.CRC or tmp.stat().st_size != m.file_size:
        tmp.unlink()
        z.unlink()
        raise IOError(f"{m.filename}: CRC/size mismatch, removed; rerun to fetch again")
    tmp.replace(dest)
    z.unlink()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--ids", nargs="*", type=int, help="slide IDs (default: all in HER2match_scores.csv)")
    p.add_argument("--out", default="data/slides_source/HER2match_mrxs")
    args = p.parse_args()

    text = requests.get(SCORES, timeout=60).content.decode("utf-8-sig")
    grades = {int(r["slide ID"]): r["HER score"] for r in csv.DictReader(io.StringIO(text), delimiter=";")}
    ids = args.ids or sorted(grades)

    raw = HttpRangeFile(URL)
    zf = zipfile.ZipFile(io.BufferedReader(raw, buffer_size=8 << 20))
    names = [m for m in zf.infolist() if not m.filename.startswith("__MACOSX/")]
    out = Path(args.out)
    for sid in ids:
        stem = f"{sid:03d}"
        members = [m for m in names if not m.is_dir() and (Path(m.filename).name == f"{stem}.mrxs" or f"/{stem}/" in "/" + m.filename)]
        if not members:
            print(f"{stem}: not found in the archive", flush=True)
            continue
        dest_root = out / f"score_{grades[sid].replace('+', 'plus')}"
        total = sum(m.file_size for m in members)
        print(f"{stem} ({grades[sid]}): {len(members)} files, {total / 1e6:.0f} MB", flush=True)
        for m in members:
            rel = Path(m.filename)
            # keep "<stem>.mrxs" and "<stem>/..." relative to the folder that holds them
            parts = rel.parts
            i = next(k for k, s in enumerate(parts) if s in (stem, f"{stem}.mrxs"))
            dest = dest_root.joinpath(*parts[i:])
            if dest.exists() and dest.stat().st_size == m.file_size:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            fetch_member(raw, m, dest)
        print(f"{stem}: done", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
