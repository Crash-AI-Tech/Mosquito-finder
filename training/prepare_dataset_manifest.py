#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from baseline_common import (
    DEFAULT_DATASET_DIR,
    DEFAULT_OUTPUT_DIR,
    assign_group_folds,
    build_dataset_summary,
    dump_json,
    scan_dataset,
    write_manifest,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build manifest for Mosquito Finder synthetic samples.")
    parser.add_argument(
        "--dataset-dir",
        type=Path,
        default=DEFAULT_DATASET_DIR,
        help="Directory containing synthetic .jpg samples.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where manifest and summary files will be written.",
    )
    parser.add_argument(
        "--fold-count",
        type=int,
        default=3,
        help="Number of deterministic group folds to assign.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    records = assign_group_folds(scan_dataset(args.dataset_dir), fold_count=args.fold_count)
    summary = build_dataset_summary(records)

    manifest_path = args.output_dir / "manifest.csv"
    summary_path = args.output_dir / "dataset_summary.json"

    write_manifest(records, manifest_path)
    dump_json(summary_path, summary)

    print(f"Manifest written to: {manifest_path}")
    print(f"Summary written to: {summary_path}")
    print(f"Total images: {summary['total_images']}")
    print(f"Total base groups: {summary['total_base_groups']}")
    print(f"Image label counts: {summary['image_label_counts']}")
    print(f"Base label counts: {summary['base_label_counts']}")


if __name__ == "__main__":
    main()
