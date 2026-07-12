"""批量文件重命名 CLI 工具

用途：
  提供一组明确的命令行子命令来执行批量重命名，避免在源码里手动切换不同
  重命名函数导致误调用。支持 YAML 规则替换、集数补零、按字符截断、
  按正则插入字符串、按序号重新命名等常见文件整理场景。

配置文件：
  rules 子命令默认读取 rename_rules.yaml。该文件用于配置 remove_patterns、
  replace_patterns、regex_pattern、file_extension/file_extensions 等规则。
  其他子命令主要通过 CLI 参数传入目标目录和重命名参数。

必填参数：
  每个子命令都必须通过 --folder 指定目标目录。
  不同子命令还会要求对应参数，例如 truncate 的 --char、regex-add 的
  --add-string 等。

可选参数：
  --dry-run        仅预览，不真正重命名。
  --recursive     递归处理子目录。
  --log-level     日志级别，默认 INFO。
  --log-file      日志文件，默认 logs/rename.log。

示例：
  python rename_files.py rules --folder C:\\path\\to\\files --config rename_rules.yaml --dry-run
  python rename_files.py pad --folder C:\\path\\to\\files --prefix 第 --suffix 集
  python rename_files.py truncate --folder C:\\path\\to\\files --char 【 --dry-run
  python rename_files.py regex-add --folder C:\\path\\to\\files --pattern "第\\d集" --add-string "审批单-" --position before

输出：
  控制台输出执行摘要，详细重命名计划和结果写入 logs/rename.log。
"""

from __future__ import annotations

import argparse
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

from logging_config import configure_utf8_stdio, get_logger, setup_logger

USAGE = __doc__ or ""
DEFAULT_LOG_FILE = "logs/rename.log"
DEFAULT_CONFIG_FILE = "rename_rules.yaml"

logger = get_logger(__name__)


@dataclass(frozen=True)
class RenameOperation:
    old_path: Path
    new_path: Path


@dataclass
class RenameSummary:
    planned: int = 0
    renamed: int = 0
    skipped: int = 0
    conflicts: int = 0
    errors: int = 0


def read_config(config_path: str | os.PathLike[str] = DEFAULT_CONFIG_FILE) -> dict[str, Any]:
    """读取 YAML 配置文件。"""
    path = Path(config_path)
    logger.info("读取配置文件: %s", path)
    with path.open("r", encoding="utf-8") as file_obj:
        config = yaml.safe_load(file_obj) or {}
    if not isinstance(config, dict):
        raise ValueError(f"配置文件必须是 YAML mapping: {path}")
    logger.info("配置文件加载成功")
    return config


def rename_files_in_folder(
    folder_path: str | os.PathLike[str],
    config: dict[str, Any],
    recursive: bool = True,
    dry_run: bool = False,
) -> RenameSummary:
    """根据 YAML 中的 remove_patterns 和 replace_patterns 批量重命名。"""
    folder = require_folder(folder_path)
    remove_patterns = config.get("remove_patterns", []) or []
    replace_patterns = config.get("replace_patterns", []) or []
    extensions = normalize_extensions(
        config.get("file_extensions", config.get("file_extension", ""))
    )

    logger.info("开始按 YAML 规则处理目录: %s", folder)
    logger.debug("remove_patterns: %s", remove_patterns)
    logger.debug("replace_patterns: %s", replace_patterns)
    logger.debug("extensions: %s", sorted(extensions))

    operations: list[RenameOperation] = []
    for path in iter_files(folder, recursive=recursive, extensions=extensions):
        new_name = path.name
        for pattern in remove_patterns:
            new_name = re.sub(str(pattern), "", new_name)
        for rule in replace_patterns:
            pattern = str(rule.get("pattern", ""))
            replacement = str(rule.get("replacement", ""))
            if "%d" in pattern:
                regex_pattern, regex_replacement = pattern_to_regex_and_replacement(
                    pattern, replacement
                )
                new_name = re.sub(regex_pattern, regex_replacement, new_name)
            else:
                new_name = re.sub(pattern, replacement, new_name)
        new_name = new_name.strip()
        if new_name and new_name != path.name:
            operations.append(RenameOperation(path, path.with_name(new_name)))

    return apply_rename_plan(operations, dry_run=dry_run)


def truncate_filename_after_char(
    folder_path: str | os.PathLike[str],
    trunc_char: str,
    recursive: bool = False,
    dry_run: bool = False,
) -> RenameSummary:
    """删除文件名中指定字符及其后的内容，保留扩展名。"""
    if not trunc_char:
        raise ValueError("--char 不能为空")

    folder = require_folder(folder_path)
    operations: list[RenameOperation] = []
    for path in iter_files(folder, recursive=recursive):
        if trunc_char not in path.stem:
            continue
        new_stem = path.stem.split(trunc_char, 1)[0].strip()
        if not new_stem:
            logger.warning("截断后文件名为空，跳过: %s", path)
            continue
        operations.append(RenameOperation(path, path.with_name(f"{new_stem}{path.suffix}")))

    return apply_rename_plan(operations, dry_run=dry_run)


def rename_files_with_padded_numbers(
    folder_path: str | os.PathLike[str],
    prefix: str = "第",
    suffix: str = "集",
    recursive: bool = True,
    width: int | None = None,
    dry_run: bool = False,
) -> RenameSummary:
    """将 prefix 和 suffix 之间的数字按文件总数或指定宽度补零。"""
    folder = require_folder(folder_path)
    files = list(iter_files(folder, recursive=recursive))
    number_width = width or len(str(len(files)))
    pattern = re.compile(f"{re.escape(prefix)}(\\d+){re.escape(suffix)}")

    logger.info(
        "开始集数补零: folder=%s, files=%s, width=%s, prefix=%r, suffix=%r",
        folder,
        len(files),
        number_width,
        prefix,
        suffix,
    )

    operations: list[RenameOperation] = []
    for path in files:
        new_name = pattern.sub(
            lambda match: f"{prefix}{int(match.group(1)):0{number_width}d}{suffix}",
            path.name,
        )
        if new_name != path.name:
            operations.append(RenameOperation(path, path.with_name(new_name)))

    return apply_rename_plan(operations, dry_run=dry_run)


def rename_files_by_regex(
    folder_path: str | os.PathLike[str],
    regex_patterns: str | list[str],
    add_string: str,
    add_position: str = "after",
    file_extensions: str | Iterable[str] = "",
    recursive: bool = False,
    dry_run: bool = False,
) -> RenameSummary:
    """匹配正则后，在匹配文本前或后插入指定字符串。"""
    if add_position not in {"before", "after"}:
        raise ValueError("--position 必须是 before 或 after")
    if not add_string:
        raise ValueError("--add-string 不能为空")

    folder = require_folder(folder_path)
    patterns = [regex_patterns] if isinstance(regex_patterns, str) else regex_patterns
    compiled_patterns = [re.compile(pattern) for pattern in patterns]
    extensions = normalize_extensions(file_extensions)

    operations: list[RenameOperation] = []
    for path in iter_files(folder, recursive=recursive, extensions=extensions):
        for pattern in compiled_patterns:
            match = pattern.search(path.name)
            if not match:
                continue
            if add_position == "before":
                new_name = path.name[: match.start()] + add_string + path.name[match.start() :]
            else:
                new_name = path.name[: match.end()] + add_string + path.name[match.end() :]
            operations.append(RenameOperation(path, path.with_name(new_name)))
            break

    return apply_rename_plan(operations, dry_run=dry_run)


def rename_files_with_suffix(
    folder_path: str | os.PathLike[str],
    suffix: str,
    ascending: bool = False,
    dry_run: bool = False,
) -> RenameSummary:
    """按排序序号重命名为 001_suffix.ext 形式。"""
    folder = require_folder(folder_path)
    files = sorted(iter_files(folder, recursive=False), reverse=not ascending)
    number_width = len(str(len(files)))
    operations = [
        RenameOperation(path, path.with_name(f"{index:0{number_width}d}_{suffix}{path.suffix}"))
        for index, path in enumerate(files, start=1)
    ]
    return apply_rename_plan(operations, dry_run=dry_run)


def rename_files_with_prefix(
    folder_path: str | os.PathLike[str],
    prefix: str,
    suffix: str = "",
    ascending: bool = True,
    dry_run: bool = False,
) -> RenameSummary:
    """按排序序号重命名为 prefix001suffix.ext 形式。"""
    folder = require_folder(folder_path)
    files = sorted(iter_files(folder, recursive=False), reverse=not ascending)
    number_width = len(str(len(files)))
    operations = [
        RenameOperation(
            path,
            path.with_name(f"{prefix}{index:0{number_width}d}{suffix}{path.suffix}"),
        )
        for index, path in enumerate(files, start=1)
    ]
    return apply_rename_plan(operations, dry_run=dry_run)


def rename_files_keep_name(
    folder_path: str | os.PathLike[str],
    name_prefix: str = "",
    keep_suffix: str = "",
    ascending: bool = True,
    dry_run: bool = False,
) -> RenameSummary:
    """按排序序号加在原文件名前，保留去掉开头数字后的原名。"""
    folder = require_folder(folder_path)
    files = sorted(iter_files(folder, recursive=False), reverse=not ascending)
    number_width = len(str(len(files)))
    operations: list[RenameOperation] = []
    for index, path in enumerate(files, start=1):
        base_name = path.name
        while base_name and base_name[0].isdigit():
            base_name = base_name[1:]
        separator = "_" if keep_suffix else ""
        new_name = f"{name_prefix}{index:0{number_width}d}{separator}{keep_suffix}{base_name}"
        operations.append(RenameOperation(path, path.with_name(new_name)))
    return apply_rename_plan(operations, dry_run=dry_run)


def apply_rename_plan(
    operations: list[RenameOperation],
    dry_run: bool = False,
) -> RenameSummary:
    """Validate and apply a rename plan."""
    summary = RenameSummary(planned=len(operations))
    seen_targets: set[Path] = set()
    valid_operations: list[RenameOperation] = []

    for operation in operations:
        old_path = operation.old_path
        new_path = operation.new_path
        if old_path == new_path:
            summary.skipped += 1
            continue
        if not old_path.exists():
            logger.warning("源文件不存在，跳过: %s", old_path)
            summary.skipped += 1
            continue
        if new_path in seen_targets:
            logger.warning("多个文件指向同一目标，跳过: %s", new_path)
            summary.conflicts += 1
            continue
        seen_targets.add(new_path)
        if new_path.exists():
            logger.warning("目标已存在，跳过: %s -> %s", old_path, new_path)
            summary.conflicts += 1
            continue
        valid_operations.append(operation)

    logger.info(
        "重命名计划: planned=%s, valid=%s, skipped=%s, conflicts=%s, dry_run=%s",
        summary.planned,
        len(valid_operations),
        summary.skipped,
        summary.conflicts,
        dry_run,
    )

    for operation in valid_operations:
        if dry_run:
            logger.info("预览重命名: %s -> %s", operation.old_path, operation.new_path)
            continue
        try:
            operation.old_path.rename(operation.new_path)
            summary.renamed += 1
            logger.info("重命名成功: %s -> %s", operation.old_path, operation.new_path)
        except OSError as exc:
            summary.errors += 1
            logger.error("重命名失败: %s -> %s, 原因: %s", operation.old_path, operation.new_path, exc)

    return summary


def iter_files(
    folder: Path,
    recursive: bool = False,
    extensions: set[str] | None = None,
) -> Iterable[Path]:
    """Iterate files under a folder with optional recursion and extension filtering."""
    pattern = "**/*" if recursive else "*"
    for path in folder.glob(pattern):
        if not path.is_file():
            continue
        if extensions and path.suffix.lower() not in extensions:
            continue
        yield path


def normalize_extensions(value: str | Iterable[str]) -> set[str]:
    """Normalize extension config into a lowercase set like {'.m4a'}."""
    if not value:
        return set()
    if isinstance(value, str):
        raw_items = [item.strip() for item in re.split(r"[,;]", value) if item.strip()]
    else:
        raw_items = [str(item).strip() for item in value if str(item).strip()]
    return {
        item.lower() if item.startswith(".") else f".{item.lower()}"
        for item in raw_items
    }


def require_folder(folder_path: str | os.PathLike[str]) -> Path:
    folder = Path(folder_path).expanduser()
    if not folder.is_dir():
        raise NotADirectoryError(f"目标路径不是有效文件夹: {folder}")
    return folder


def pattern_to_regex_and_replacement(pattern: str, replacement: str) -> tuple[str, str]:
    """Convert a pattern containing %d into a regex pattern and replacement."""
    parts = pattern.split("%d")
    regex_pattern = ""
    for index, part in enumerate(parts):
        regex_pattern += re.escape(part)
        if index < len(parts) - 1:
            regex_pattern += r"(\d+)"
    for group_index in range(1, len(parts)):
        replacement = replacement.replace("%d", f"\\{group_index}", 1)
    return regex_pattern, replacement


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="批量文件重命名 CLI 工具。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=USAGE,
    )
    parser.add_argument("--log-level", default="INFO", help="日志级别，默认 INFO。")
    parser.add_argument("--log-file", default=DEFAULT_LOG_FILE, help="日志文件路径。")

    subparsers = parser.add_subparsers(dest="command", required=True)

    rules_parser = add_common_folder_args(
        subparsers.add_parser("rules", help="按 YAML remove/replace 规则重命名。"),
        recursive_default=True,
    )
    rules_parser.add_argument("--config", default=DEFAULT_CONFIG_FILE, help="YAML 规则文件。")
    rules_parser.set_defaults(handler=handle_rules)

    pad_parser = add_common_folder_args(
        subparsers.add_parser("pad", help="将集数字补零，例如 第1集 -> 第001集。"),
        recursive_default=True,
    )
    pad_parser.add_argument("--prefix", default="第", help="数字前缀，默认 第。")
    pad_parser.add_argument("--suffix", default="集", help="数字后缀，默认 集。")
    pad_parser.add_argument("--width", type=int, help="补零宽度；默认按文件总数计算。")
    pad_parser.set_defaults(handler=handle_pad)

    truncate_parser = add_common_folder_args(
        subparsers.add_parser("truncate", help="按指定字符截断文件名。"),
        recursive_default=False,
    )
    truncate_parser.add_argument("--char", required=True, help="截断字符。")
    truncate_parser.set_defaults(handler=handle_truncate)

    regex_parser = add_common_folder_args(
        subparsers.add_parser("regex-add", help="匹配正则后插入指定字符串。"),
        recursive_default=False,
    )
    regex_parser.add_argument("--pattern", action="append", help="正则表达式，可重复。")
    regex_parser.add_argument("--config", help="从 YAML 读取 regex_pattern 和扩展名。")
    regex_parser.add_argument("--add-string", required=True, help="要插入的字符串。")
    regex_parser.add_argument(
        "--position",
        choices=("before", "after"),
        default="after",
        help="插入位置，默认 after。",
    )
    regex_parser.add_argument("--extension", action="append", help="只处理指定扩展名，可重复。")
    regex_parser.set_defaults(handler=handle_regex_add)

    suffix_parser = add_common_folder_args(
        subparsers.add_parser("sequence-suffix", help="按排序序号重命名为 001_suffix.ext。"),
        recursive_default=False,
    )
    suffix_parser.add_argument("--suffix", required=True, help="文件名后缀。")
    suffix_parser.add_argument("--descending", action="store_true", help="按文件名降序。")
    suffix_parser.set_defaults(handler=handle_sequence_suffix)

    prefix_parser = add_common_folder_args(
        subparsers.add_parser("sequence-prefix", help="按排序序号重命名为 prefix001suffix.ext。"),
        recursive_default=False,
    )
    prefix_parser.add_argument("--prefix", required=True, help="文件名前缀。")
    prefix_parser.add_argument("--suffix", default="", help="序号后的后缀。")
    prefix_parser.add_argument("--descending", action="store_true", help="按文件名降序。")
    prefix_parser.set_defaults(handler=handle_sequence_prefix)

    keep_parser = add_common_folder_args(
        subparsers.add_parser("keep-name", help="按排序序号加前缀，同时保留原文件名。"),
        recursive_default=False,
    )
    keep_parser.add_argument("--name-prefix", default="", help="序号前固定前缀。")
    keep_parser.add_argument("--keep-suffix", default="", help="序号后固定后缀。")
    keep_parser.add_argument("--descending", action="store_true", help="按文件名降序。")
    keep_parser.set_defaults(handler=handle_keep_name)

    return parser


def add_common_folder_args(
    parser: argparse.ArgumentParser,
    recursive_default: bool,
) -> argparse.ArgumentParser:
    parser.add_argument("--folder", required=True, help="目标文件夹。")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不真正重命名。")
    if recursive_default:
        parser.add_argument(
            "--no-recursive",
            action="store_true",
            help="不递归处理子目录。",
        )
    else:
        parser.add_argument("--recursive", action="store_true", help="递归处理子目录。")
    return parser


def should_recurse(args: argparse.Namespace, default: bool) -> bool:
    if default:
        return not getattr(args, "no_recursive", False)
    return bool(getattr(args, "recursive", False))


def handle_rules(args: argparse.Namespace) -> RenameSummary:
    config = read_config(args.config)
    return rename_files_in_folder(
        args.folder,
        config,
        recursive=should_recurse(args, default=True),
        dry_run=args.dry_run,
    )


def handle_pad(args: argparse.Namespace) -> RenameSummary:
    return rename_files_with_padded_numbers(
        args.folder,
        prefix=args.prefix,
        suffix=args.suffix,
        recursive=should_recurse(args, default=True),
        width=args.width,
        dry_run=args.dry_run,
    )


def handle_truncate(args: argparse.Namespace) -> RenameSummary:
    return truncate_filename_after_char(
        args.folder,
        trunc_char=args.char,
        recursive=should_recurse(args, default=False),
        dry_run=args.dry_run,
    )


def handle_regex_add(args: argparse.Namespace) -> RenameSummary:
    config: dict[str, Any] = {}
    if args.config:
        config = read_config(args.config)
    patterns = args.pattern or config.get("regex_pattern")
    if not patterns:
        raise ValueError("请通过 --pattern 或 --config 提供 regex_pattern")
    extensions = args.extension or config.get("file_extensions", config.get("file_extension", ""))
    return rename_files_by_regex(
        args.folder,
        regex_patterns=patterns,
        add_string=args.add_string,
        add_position=args.position,
        file_extensions=extensions,
        recursive=should_recurse(args, default=False),
        dry_run=args.dry_run,
    )


def handle_sequence_suffix(args: argparse.Namespace) -> RenameSummary:
    return rename_files_with_suffix(
        args.folder,
        suffix=args.suffix,
        ascending=not args.descending,
        dry_run=args.dry_run,
    )


def handle_sequence_prefix(args: argparse.Namespace) -> RenameSummary:
    return rename_files_with_prefix(
        args.folder,
        prefix=args.prefix,
        suffix=args.suffix,
        ascending=not args.descending,
        dry_run=args.dry_run,
    )


def handle_keep_name(args: argparse.Namespace) -> RenameSummary:
    return rename_files_keep_name(
        args.folder,
        name_prefix=args.name_prefix,
        keep_suffix=args.keep_suffix,
        ascending=not args.descending,
        dry_run=args.dry_run,
    )


def print_summary(summary: RenameSummary) -> None:
    print(
        "完成: "
        f"planned={summary.planned}, "
        f"renamed={summary.renamed}, "
        f"skipped={summary.skipped}, "
        f"conflicts={summary.conflicts}, "
        f"errors={summary.errors}"
    )


def main() -> int:
    configure_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args()
    setup_logger(log_level=args.log_level, log_file=args.log_file)

    try:
        summary = args.handler(args)
    except Exception as exc:
        logger.exception("执行失败: %s", exc)
        return 1

    print_summary(summary)
    return 1 if summary.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
