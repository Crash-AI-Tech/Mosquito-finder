#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))

from yolox_mosquito_nano import Exp as BaseMosquitoExp


class Exp(BaseMosquitoExp):
    def __init__(self):
        super().__init__()
        self.data_dir = str(self.__class__.repo_root() / "data" / "detector" / "generated_dfine")
        self.exp_name = "yolox_mosquito_nano_reality"

        # Same data philosophy as the improved D-FINE run: more synthetic
        # variety, stronger hard negatives, and a reality split that punishes
        # false positives.
        self.max_epoch = 18
        self.warmup_epochs = 2
        self.no_aug_epochs = 4
        self.eval_interval = 2
        self.print_interval = 20
        self.data_num_workers = 6
        self.basic_lr_per_img = 0.0015 / 64.0
        self.min_lr_ratio = 0.05
        self.mosaic_prob = 0.45
        self.hsv_prob = 0.9
        self.flip_prob = 0.5
        self.degrees = 5.0
        self.translate = 0.10
        self.mosaic_scale = (0.50, 1.40)
        self.shear = 1.2
        self.test_conf = 0.04
        self.nmsthre = 0.42

    @staticmethod
    def repo_root():
        from pathlib import Path

        return Path(__file__).resolve().parent.parent
