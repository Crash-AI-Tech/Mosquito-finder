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
        self.data_dir = str(REPO_ROOT / "data" / "processed" / "real_synthetic_phone_detector_mix_coco")
        self.train_ann = "instances_train2017.json"
        self.val_ann = "instances_val2017.json"
        self.test_ann = "instances_val2017.json"
        self.exp_name = "yolox_real_synthetic_phone"

        self.max_epoch = 1
        self.warmup_epochs = 0
        self.no_aug_epochs = 1
        self.eval_interval = 1
        self.print_interval = 20
        self.data_num_workers = 2
        self.basic_lr_per_img = 0.001 / 64.0
        self.min_lr_ratio = 0.10
        self.mosaic_prob = 0.14
        self.mixup_prob = 0.0
        self.enable_mixup = False
        self.hsv_prob = 0.55
        self.flip_prob = 0.5
        self.degrees = 3.0
        self.translate = 0.06
        self.mosaic_scale = (0.75, 1.25)
        self.shear = 0.5
        self.test_conf = 0.04
        self.nmsthre = 0.42

    def random_resize(self, data_loader, epoch, rank, is_distributed):
        return self.input_size
