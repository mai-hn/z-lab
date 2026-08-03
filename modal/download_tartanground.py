#!/usr/bin/env python3
"""Download the complete TartanGround dataset except ROS bag data.

This script uses the official ``tartanairpy`` downloader. By default, archives
are kept compressed under ``modal/TartanGround``. Re-running the downloader is
safe: the official toolkit checks existing files before downloading.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


DEFAULT_DESTINATION = Path(__file__).resolve().parent / "TartanGround"

# Deliberately explicit: an empty modality list means "all", including rosbag.
MODALITIES_WITHOUT_ROSBAG = [
    "image",
    "meta",
    "depth",
    "seg",
    "lidar",
    "imu",
    "sem_pcd",
    "seg_labels",
    "rgb_pcd",
]

ROBOT_VERSIONS = ["omni", "diff", "anymal"]

CAMERA_NAMES = [
    "lcam_front",
    "lcam_right",
    "lcam_left",
    "lcam_back",
    "lcam_top",
    "lcam_bottom",
    "rcam_front",
    "rcam_right",
    "rcam_left",
    "rcam_back",
    "rcam_top",
    "rcam_bottom",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="下载完整 TartanGround 数据集，但排除 rosbag 模态。"
    )
    parser.add_argument(
        "--destination",
        type=Path,
        default=DEFAULT_DESTINATION,
        help=f"保存目录（默认：{DEFAULT_DESTINATION}）",
    )
    parser.add_argument(
        "--source",
        choices=("huggingface", "airlab"),
        default="huggingface",
        help="官方下载源（默认：huggingface）",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="下载 worker 数量（默认：4；Hugging Face 源可能自行管理并发）",
    )
    parser.add_argument(
        "--unzip",
        action="store_true",
        help="下载后解压 ZIP；默认只保留压缩包",
    )
    parser.add_argument(
        "--delete-zip",
        action="store_true",
        help="解压成功后删除 ZIP（必须与 --unzip 一起使用）",
    )
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers 必须大于 0")
    if args.delete_zip and not args.unzip:
        parser.error("--delete-zip 必须与 --unzip 一起使用")
    return args


def import_tartanair():
    try:
        import tartanair as ta
    except ImportError as error:
        print(
            "未安装官方 tartanairpy 工具。请先按照脚本说明安装依赖。",
            file=sys.stderr,
        )
        raise SystemExit(2) from error
    return ta


def main() -> int:
    args = parse_args()
    destination = args.destination.expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)

    print("TartanGround 全量下载配置")
    print(f"  保存目录: {destination}")
    print(f"  数据源: {args.source}")
    print(f"  机器人: {', '.join(ROBOT_VERSIONS)}")
    print(f"  模态: {', '.join(MODALITIES_WITHOUT_ROSBAG)}")
    print("  已排除: rosbag")
    print(f"  下载后解压: {'是' if args.unzip else '否'}")
    print("注意：完整数据集约 16 TB，请确认磁盘空间和网络配额充足。")

    ta = import_tartanair()
    ta.init(str(destination))
    ta.download_ground(
        env=[],  # 空列表表示全部环境。
        version=ROBOT_VERSIONS,
        traj=[],  # 空列表表示每个环境中的全部轨迹。
        modality=MODALITIES_WITHOUT_ROSBAG,
        camera_name=CAMERA_NAMES,
        unzip=args.unzip,
        delete_zip=args.delete_zip,
        num_workers=args.workers,
        data_source=args.source,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
