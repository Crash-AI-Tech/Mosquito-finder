#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FILE_LIST = REPO_ROOT / "data" / "external" / "mosquito_alert_tigapics" / "labels" / "File_List.json"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "external" / "mosquito_alert_tigapics" / "images"
DEFAULT_FAILED_OUTPUT = REPO_ROOT / "data" / "external" / "mosquito_alert_tigapics" / "failed_downloads.jsonl"
BASE_URL = "https://www.ebi.ac.uk/biostudies/files/S-BIAD249"


@dataclass(frozen=True)
class DownloadResult:
    status: str
    path: str
    error: str = ""
    expected_size: int = 0
    actual_size: int = 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Download Mosquito Alert Tigapics images with resume support.")
    parser.add_argument("--file-list", type=Path, default=DEFAULT_FILE_LIST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--failed-output", type=Path, default=DEFAULT_FAILED_OUTPUT)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--retries", type=int, default=6)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--progress-every", type=int, default=100)
    parser.add_argument("--limit", type=int, default=0, help="Optional max item count for smoke tests.")
    return parser


def load_items(path: Path, limit: int) -> list[dict[str, object]]:
    items = json.loads(path.read_text(encoding="utf-8"))
    files = [item for item in items if item.get("type") == "file" and item.get("path")]
    return files[:limit] if limit > 0 else files


def expected_size(item: dict[str, object]) -> int:
    try:
        return int(item.get("size") or 0)
    except (TypeError, ValueError):
        return 0


def download_one(item: dict[str, object], output_dir: Path, retries: int, timeout: int) -> DownloadResult:
    relative_path = str(item["path"])
    target = output_dir / relative_path
    size = expected_size(item)

    if target.exists() and (size == 0 or target.stat().st_size == size):
        return DownloadResult("skipped", relative_path, expected_size=size, actual_size=target.stat().st_size)

    target.parent.mkdir(parents=True, exist_ok=True)
    url = f"{BASE_URL}/{relative_path}"
    temp = target.with_suffix(target.suffix + ".part")
    last_error = "unknown"

    for attempt in range(1, retries + 1):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "MosquitoFinderDatasetRebuild/1.0"})
            with urllib.request.urlopen(request, timeout=timeout) as response, temp.open("wb") as handle:
                while True:
                    chunk = response.read(1024 * 512)
                    if not chunk:
                        break
                    handle.write(chunk)
            actual_size = temp.stat().st_size
            if size > 0 and actual_size != size:
                last_error = f"size mismatch expected={size} actual={actual_size}"
                temp.unlink(missing_ok=True)
                if attempt == retries:
                    return DownloadResult("failed", relative_path, last_error, size, actual_size)
                time.sleep(backoff_seconds(attempt))
                continue
            temp.replace(target)
            return DownloadResult("downloaded", relative_path, expected_size=size, actual_size=target.stat().st_size)
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            last_error = str(error)
            if attempt == retries:
                temp.unlink(missing_ok=True)
                return DownloadResult("failed", relative_path, last_error, size, temp.stat().st_size if temp.exists() else 0)
            time.sleep(backoff_seconds(attempt))

    return DownloadResult("failed", relative_path, last_error, size)


def backoff_seconds(attempt: int) -> float:
    return min(60.0, (2 ** attempt) + random.uniform(0.0, 1.5))


def append_failure(path: Path, result: DownloadResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "path": result.path,
        "error": result.error,
        "expected_size": result.expected_size,
        "actual_size": result.actual_size,
        "ts": int(time.time()),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def main() -> None:
    args = build_parser().parse_args()
    items = load_items(args.file_list, args.limit)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.failed_output.unlink(missing_ok=True)

    counts: dict[str, int] = {"downloaded": 0, "skipped": 0, "failed": 0}
    start = time.time()

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = [pool.submit(download_one, item, args.output_dir, args.retries, args.timeout) for item in items]
        for index, future in enumerate(as_completed(futures), 1):
            result = future.result()
            counts[result.status] = counts.get(result.status, 0) + 1
            if result.status == "failed":
                append_failure(args.failed_output, result)
                print(f"failed:{result.path}:{result.error}", flush=True)

            if index % max(1, args.progress_every) == 0 or index == len(futures):
                elapsed = max(1.0, time.time() - start)
                rate = index / elapsed
                print(
                    f"progress={index}/{len(futures)} "
                    f"downloaded={counts.get('downloaded', 0)} "
                    f"skipped={counts.get('skipped', 0)} "
                    f"failed={counts.get('failed', 0)} "
                    f"rate={rate:.2f}/s",
                    flush=True,
                )


if __name__ == "__main__":
    main()
