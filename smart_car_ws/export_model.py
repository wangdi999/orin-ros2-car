#!/usr/bin/env python3
"""
YOLOv8 → TensorRT FP16 模型导出脚本。

在 Jetson Orin Nano 主机上运行，将 YOLOv8-small COCO 预训练权重
导出为 TensorRT FP16 .engine 文件，并同时保留 ONNX 作为降级方案。

用法：
    python3 export_model.py                          # 默认导出 yolov8s.engine
    python3 export_model.py --model yolov8n.pt       # 导出 nano 版本
    python3 export_model.py --output ~/my_models/    # 指定输出目录

前置条件：
    pip install ultralytics
    (Jetson 上需有 TensorRT 8.5+ 和 CUDA)
"""

import argparse
import os
import sys
from pathlib import Path


def parse_args():
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        description="YOLOv8 → TensorRT FP16 模型导出"
    )
    parser.add_argument(
        "--model",
        default="yolov8s.pt",
        help="YOLOv8 模型名称或路径 (默认: yolov8s.pt)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="输出目录 (默认: ~/smart_car_ws/models/)",
    )
    parser.add_argument(
        "--imgsz",
        type=int,
        default=640,
        help="输入图像尺寸 (默认: 640)",
    )
    parser.add_argument(
        "--workspace",
        type=float,
        default=2.0,
        help="TensorRT workspace 大小 GB (默认: 2，适配 Jetson 4GB)",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # 输出目录
    if args.output is None:
        output_dir = os.path.join(
            str(Path.home()), "smart_car_ws", "models"
        )
    else:
        output_dir = os.path.expanduser(args.output)
    os.makedirs(output_dir, exist_ok=True)

    # 导入 ultralytics
    try:
        from ultralytics import YOLO
    except ImportError:
        print("错误: 请先安装 ultralytics: pip install ultralytics")
        sys.exit(1)

    model_name = os.path.splitext(os.path.basename(args.model))[0]
    engine_path = os.path.join(output_dir, f"{model_name}.engine")
    onnx_path = os.path.join(output_dir, f"{model_name}.onnx")

    print(f"=" * 60)
    print(f"YOLOv8 → TensorRT FP16 模型导出")
    print(f"=" * 60)
    print(f"  模型: {args.model}")
    print(f"  输出目录: {output_dir}")
    print(f"  图像尺寸: {args.imgsz}")
    print(f"  TensorRT workspace: {args.workspace} GB")
    print(f"=" * 60)

    # Step 1: 下载/加载模型
    print("\n[1/3] 加载模型...")
    try:
        model = YOLO(args.model)
        print(f"  模型加载成功: {args.model}")
    except Exception as e:
        print(f"  模型加载失败: {e}")
        print("  如果是首次运行，将自动从 Ultralytics 下载 COCO 预训练权重")
        sys.exit(1)

    # Step 2: 导出 ONNX（中间格式）
    print("\n[2/3] 导出 ONNX...")
    onnx_success = False
    try:
        model.export(
            format="onnx",
            imgsz=args.imgsz,
            opset=12,
            simplify=True,
        )
        # 检查导出的 ONNX 文件
        expected_onnx = args.model.replace(".pt", ".onnx")
        if os.path.exists(expected_onnx):
            import shutil
            shutil.move(expected_onnx, onnx_path)
        print(f"  ONNX 导出成功: {onnx_path}")
        onnx_success = True
    except Exception as e:
        print(f"  ONNX 导出失败: {e}")
        # 检查是否已有 ONNX 文件
        if os.path.exists(onnx_path):
            print(f"  使用已有 ONNX 文件: {onnx_path}")
            onnx_success = True
        else:
            print("  无法继续导出 TensorRT engine")
            sys.exit(1)

    # Step 3: 导出 TensorRT FP16（直接从PyTorch模型）
    print("\n[3/3] 导出 TensorRT FP16 engine...")
    try:
        # 直接从 PyTorch 模型导出 TensorRT（ultralytics 8.x 不支持 ONNX→Engine）
        model.export(
            format="engine",
            device=0,
            half=True,
            workspace=args.workspace,
            imgsz=args.imgsz,
        )
        # 移动导出的 engine 文件
        expected_engine = args.model.replace(".pt", ".engine")
        if os.path.exists(expected_engine):
            import shutil
            shutil.move(expected_engine, engine_path)
        print(f"  TensorRT engine 导出成功: {engine_path}")
    except Exception as e:
        print(f"  TensorRT engine 导出失败: {e}")
        print(f"  尝试继续：可能 engine 已在当前目录")
        # Ultralytics 可能将 engine 放在不同位置
        possible_engine = os.path.join(
            os.path.dirname(args.model) or ".",
            os.path.splitext(os.path.basename(args.model))[0] + ".engine"
        )
        if os.path.exists(possible_engine):
            import shutil
            shutil.move(possible_engine, engine_path)
            print(f"  TensorRT engine -> {engine_path}")
        elif onnx_success:
            print(f"  降级方案: 运行时可使用 ONNX 模型")
            print(f"  export YOLO_ONNX_PATH={onnx_path}")

    # 摘要
    print(f"\n{'=' * 60}")
    print(f"导出完成！")
    print(f"{'=' * 60}")
    print(f"  TensorRT engine: {engine_path}")
    print(f"  ONNX (降级):     {onnx_path}")
    print(f"")
    print(f"  部署到小车:")
    print(f"    scp {engine_path} jetson@192.168.160.196:~/smart_car_ws/models/")
    print(f"    scp {onnx_path} jetson@192.168.160.196:~/smart_car_ws/models/")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
