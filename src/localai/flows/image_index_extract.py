from __future__ import annotations

import base64
import csv
import json
import mimetypes
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from logging_config import get_logger
from localai.modules.image_files import iter_image_files
from localai.modules.llamacpp_client import LlamaCppClient, LlamaCppConfig

logger = get_logger(__name__)


@dataclass
class ImageIndexExtractOptions:
    input_dir: str
    output_dir: str = "output/image_index_extract"
    extensions: tuple[str, ...] = (".png",)
    recursive: bool = False
    max_tokens: int = 4096
    temperature: float = 0
    limit: int | None = None


def run(config: dict[str, Any], options: ImageIndexExtractOptions) -> dict[str, Any]:
    input_dir = Path(options.input_dir).expanduser()
    if not input_dir.is_dir():
        raise NotADirectoryError(f"Input directory does not exist: {input_dir}")

    images = iter_image_files(input_dir, options.extensions, options.recursive)
    if options.limit is not None:
        images = images[: options.limit]

    output_dir = Path(options.output_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    if not images:
        result = {
            "input_dir": str(input_dir),
            "image_count": 0,
            "item_count": 0,
            "error_count": 0,
            "json_path": str(output_dir / "image_index_results.json"),
            "csv_path": str(output_dir / "image_index_results.csv"),
            "mapping_path": str(output_dir / "sequence_name_map.json"),
            "items": [],
            "mapping": {},
            "dedupe": {
                "unique_sequence_count": 0,
                "duplicate_item_count": 0,
                "conflicts": [],
            },
        }
        _write_json(Path(result["json_path"]), result)
        _write_csv(Path(result["csv_path"]), [])
        _write_json(Path(result["mapping_path"]), {})
        return result

    llama_config = LlamaCppConfig.from_config(config)
    client = LlamaCppClient(llama_config)
    rows: list[dict[str, Any]] = []

    try:
        _, models = client.ensure_server()
        client.assert_model_available(models)
        for index, image_path in enumerate(images, start=1):
            logger.info("识别图片 %s/%s: %s", index, len(images), image_path)
            rows.extend(_extract_one_image(client, image_path, options))
    finally:
        client.shutdown_server()

    mapping, dedupe = _build_sequence_mapping(rows)
    result = {
        "input_dir": str(input_dir),
        "image_count": len(images),
        "item_count": len([row for row in rows if not row.get("error")]),
        "error_count": len([row for row in rows if row.get("error")]),
        "json_path": str(output_dir / "image_index_results.json"),
        "csv_path": str(output_dir / "image_index_results.csv"),
        "mapping_path": str(output_dir / "sequence_name_map.json"),
        "mapping": mapping,
        "dedupe": dedupe,
        "items": rows,
    }
    _write_json(Path(result["json_path"]), result)
    _write_json(Path(result["mapping_path"]), mapping)
    _write_csv(Path(result["csv_path"]), rows)
    return result


def _extract_one_image(
    client: LlamaCppClient,
    image_path: Path,
    options: ImageIndexExtractOptions,
) -> list[dict[str, Any]]:
    try:
        content = client.chat(
            messages=[_build_user_message(image_path)],
            max_tokens=options.max_tokens,
            temperature=options.temperature,
        )
        parsed_items = _parse_items(content)
        if not parsed_items:
            return [_error_row(image_path, "模型未返回可解析的条目", content)]
        return [_normalize_item(image_path, item, content) for item in parsed_items]
    except Exception as exc:
        logger.exception("图片识别失败: %s", image_path)
        return [_error_row(image_path, str(exc), "")]


def _build_user_message(image_path: Path) -> dict[str, Any]:
    mime_type = mimetypes.guess_type(image_path.name)[0] or "image/png"
    image_bytes = image_path.read_bytes()
    image_base64 = base64.b64encode(image_bytes).decode("ascii")
    prompt = (
        "请识别这张图片中的序号和对应文件名。"
        "如果图片里有多行，请返回所有行。"
        "只返回压缩 JSON，不要换行缩进，不要解释，不要使用 Markdown。"
        "JSON 格式必须为："
        '{"items":[{"sequence":"序号","file_name":"文件名","confidence":0.0,"notes":""}]}。'
        "如果看不清，字段保留为空字符串，并在 notes 说明。"
    )
    return {
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime_type};base64,{image_base64}"},
            },
        ],
    }


def _parse_items(content: str) -> list[dict[str, Any]]:
    data = _parse_json(content)
    if isinstance(data, dict):
        items = data.get("items")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
        return [data]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def _parse_json(content: str) -> Any:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"(\{.*\}|\[.*\])", text, flags=re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


def _normalize_item(image_path: Path, item: dict[str, Any], raw_response: str) -> dict[str, Any]:
    sequence = item.get("sequence", item.get("seq", item.get("index", item.get("number", ""))))
    file_name = item.get("file_name", item.get("filename", item.get("name", "")))
    normalized_sequence = _normalize_sequence(sequence)
    return {
        "image_path": str(image_path),
        "image_file": image_path.name,
        "sequence": normalized_sequence,
        "file_name": "" if file_name is None else str(file_name).strip(),
        "confidence": item.get("confidence", ""),
        "notes": "" if item.get("notes") is None else str(item.get("notes", "")).strip(),
        "error": "",
        "raw_response": "",
    }


def _error_row(image_path: Path, error: str, raw_response: str) -> dict[str, Any]:
    return {
        "image_path": str(image_path),
        "image_file": image_path.name,
        "sequence": "",
        "file_name": "",
        "confidence": "",
        "notes": "",
        "error": error,
        "raw_response": raw_response,
    }


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_sequence_mapping(rows: list[dict[str, Any]]) -> tuple[dict[str, str], dict[str, Any]]:
    candidates: dict[str, list[dict[str, Any]]] = defaultdict(list)
    skipped_count = 0
    for row in rows:
        if row.get("error"):
            skipped_count += 1
            continue
        sequence = _normalize_sequence(row.get("sequence", ""))
        file_name = _normalize_file_name(row.get("file_name", ""))
        if not sequence or not file_name:
            skipped_count += 1
            continue
        normalized_row = dict(row)
        normalized_row["sequence"] = sequence
        normalized_row["file_name"] = file_name
        candidates[sequence].append(normalized_row)

    mapping: dict[str, str] = {}
    conflicts: list[dict[str, Any]] = []
    duplicate_item_count = 0

    for sequence in sorted(candidates, key=_sequence_sort_key):
        rows_for_sequence = candidates[sequence]
        name_counts = Counter(row["file_name"] for row in rows_for_sequence)
        best_name = _select_best_name(rows_for_sequence, name_counts)
        mapping[sequence] = best_name
        duplicate_item_count += max(0, len(rows_for_sequence) - 1)

        if len(name_counts) > 1:
            conflicts.append(
                {
                    "sequence": sequence,
                    "selected_file_name": best_name,
                    "candidates": [
                        {"file_name": name, "count": count}
                        for name, count in name_counts.most_common()
                    ],
                    "source_images": sorted({row["image_file"] for row in rows_for_sequence}),
                }
            )

    dedupe = {
        "unique_sequence_count": len(mapping),
        "duplicate_item_count": duplicate_item_count,
        "skipped_item_count": skipped_count,
        "conflict_count": len(conflicts),
        "conflicts": conflicts,
    }
    return mapping, dedupe


def _select_best_name(rows: list[dict[str, Any]], name_counts: Counter[str]) -> str:
    most_common_count = name_counts.most_common(1)[0][1]
    tied_names = [
        name for name, count in name_counts.items() if count == most_common_count
    ]
    if len(tied_names) == 1:
        return tied_names[0]

    confidence_by_name: dict[str, float] = {}
    for name in tied_names:
        values = [_coerce_confidence(row.get("confidence")) for row in rows if row["file_name"] == name]
        confidence_by_name[name] = sum(values) / len(values) if values else 0
    return sorted(tied_names, key=lambda name: (-confidence_by_name[name], -len(name), name))[0]


def _normalize_sequence(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    match = re.search(r"\d+", text)
    if not match:
        return text
    return str(int(match.group(0)))


def _normalize_file_name(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).strip())


def _coerce_confidence(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0


def _sequence_sort_key(sequence: str) -> tuple[int, int | str]:
    if sequence.isdigit():
        return (0, int(sequence))
    return (1, sequence)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "image_path",
        "image_file",
        "sequence",
        "file_name",
        "confidence",
        "notes",
        "error",
        "raw_response",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
