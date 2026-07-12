"""图片序号和文件名识别工具

用途：
  批量读取目标目录下的 PNG 图片，调用本地 Qwen 多模态模型识别图片中的序号和对应文件名。
  入口层只负责读取配置、初始化日志和调用图片识别工作流。

配置文件：
  默认读取 common.env 和 config.yaml。
  common.env 放本机路径和本地 llama.cpp/Qwen 服务配置，其中 INPUT_PICTURES 是默认图片目录。
  config.yaml 放工作流默认参数、输出目录和 OpenAI 兼容 API 配置。

可选参数：
  --input-dir     覆盖 common.env 中的 INPUT_PICTURES。
  --config-file   配置文件路径，默认 config.yaml。
  --output-dir    覆盖识别结果输出目录。
  --recursive     递归扫描子目录中的 PNG 图片。
  --limit         仅处理前 N 张图片，便于调试。
  --max-tokens    覆盖单张图片识别的最大输出 token 数。

示例：
  python image_index_extract.py
  python image_index_extract.py --input-dir C:\\path\\to\\pictures --limit 3

输出：
  默认写入 output/image_index_extract/image_index_results.json
  output/image_index_extract/image_index_results.csv
  和最终去重映射 output/image_index_extract/sequence_name_map.json，并在控制台输出汇总 JSON。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from logging_config import get_logger, setup_logger

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from localai.flows.image_index_extract import ImageIndexExtractOptions, run  # noqa: E402
from localai.modules.config_loader import load_runtime_config  # noqa: E402

USAGE = __doc__ or ""


def main() -> int:
    configure_utf8_stdio()
    args = parse_args()
    config = load_runtime_config(args.config_file)
    app_config = config.get("app", {})
    setup_logger(
        log_level=app_config.get("log_level", "INFO"),
        log_file=str(PROJECT_ROOT / "logs" / "image_index_extract.log"),
    )
    logger = get_logger(__name__)

    flow_config = config.get("flows", {}).get("image_index_extract", {})
    input_dir = args.input_dir or flow_config.get("input_dir") or os.getenv("INPUT_PICTURES")
    if not input_dir:
        logger.error("未配置图片目录，请在 common.env 中设置 INPUT_PICTURES，或传入 --input-dir。")
        print(USAGE)
        return 2

    extensions = tuple(flow_config.get("image_extensions") or [".png"])
    options = ImageIndexExtractOptions(
        input_dir=input_dir,
        output_dir=args.output_dir or flow_config.get("output_dir", "output/image_index_extract"),
        extensions=extensions,
        recursive=bool(args.recursive or flow_config.get("recursive", False)),
        max_tokens=int(args.max_tokens or flow_config.get("max_tokens", 4096)),
        temperature=float(flow_config.get("temperature", 0)),
        limit=args.limit,
    )

    result = run(config, options)
    print_json(_summary(result))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="用本地 Qwen 模型批量识别 PNG 图片中的序号和文件名。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=USAGE,
    )
    parser.add_argument("--input-dir", help="覆盖 common.env 中的 INPUT_PICTURES。")
    parser.add_argument("--config-file", default="config.yaml", help="配置文件路径。")
    parser.add_argument("--output-dir", help="识别结果输出目录。")
    parser.add_argument("--recursive", action="store_true", help="递归扫描子目录。")
    parser.add_argument("--limit", type=int, help="仅处理前 N 张图片。")
    parser.add_argument("--max-tokens", type=int, help="覆盖单张图片识别的最大输出 token 数。")
    return parser.parse_args()


def print_json(data: dict[str, Any]) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def _summary(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "input_dir": result["input_dir"],
        "image_count": result["image_count"],
        "item_count": result["item_count"],
        "error_count": result["error_count"],
        "json_path": result["json_path"],
        "csv_path": result["csv_path"],
        "mapping_path": result["mapping_path"],
        "unique_sequence_count": result.get("dedupe", {}).get("unique_sequence_count", 0),
        "duplicate_item_count": result.get("dedupe", {}).get("duplicate_item_count", 0),
        "conflict_count": result.get("dedupe", {}).get("conflict_count", 0),
    }


if __name__ == "__main__":
    raise SystemExit(main())
