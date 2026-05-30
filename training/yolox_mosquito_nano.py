#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

from yolox.exp import Exp as BaseExp


REPO_ROOT = Path(__file__).resolve().parent.parent


class Exp(BaseExp):
    def __init__(self):
        super().__init__()
        self.num_classes = 1
        self.depth = 0.33
        self.width = 0.25
        self.input_size = (416, 416)
        self.test_size = (416, 416)
        self.random_size = (10, 16)
        self.data_dir = str(REPO_ROOT / "data" / "detector" / "generated")
        self.train_ann = "instances_train2017.json"
        self.val_ann = "instances_val2017.json"
        self.test_ann = "instances_reality2017.json"
        self.exp_name = "yolox_mosquito_nano"

        # Synthetic-to-real bridge: avoid overfitting to perfect composites.
        self.max_epoch = 6
        self.warmup_epochs = 1
        self.no_aug_epochs = 2
        self.eval_interval = 100
        self.print_interval = 20
        self.data_num_workers = 2
        self.basic_lr_per_img = 0.002 / 64.0
        self.min_lr_ratio = 0.10
        self.mosaic_prob = 0.55
        self.mixup_prob = 0.0
        self.enable_mixup = False
        self.hsv_prob = 0.8
        self.flip_prob = 0.5
        self.degrees = 4.0
        self.translate = 0.08
        self.mosaic_scale = (0.55, 1.35)
        self.shear = 1.0
        self.test_conf = 0.05
        self.nmsthre = 0.45

    def random_resize(self, data_loader, epoch, rank, is_distributed):
        return self.input_size
