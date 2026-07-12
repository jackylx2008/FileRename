# FileRename

一个简单而强大的 Python 批量文件重命名工具，支持通过 YAML 配置文件定义移除和替换规则，并支持正则表达式和数字补全。

## 功能特性

- **基于配置文件的规则**：通过 `rename_rules.yaml` 轻松管理重命名逻辑。
- **批量移除图案**：从文件名中删除指定的字符串或正则表达式模式。
- **批量替换图案**：将文件名中的特定部分替换为新内容。
- **数字补全 (Padded Numbers)**：支持将文件名中的集数/卷数自动补零（如 `1` 变为 `01`）。
- **正则表达式支持**：复杂的重命名逻辑可通过正则轻松实现。
- **自动日志记录**：所有重命名操作都会记录在 `logs/` 目录下，方便追踪和回放。
- **截断功能**：支持在指定字符处截断文件名（保留扩展名）。
- **本地 AI 图片识别**：通过本地 Qwen/llama.cpp 多模态模型批量识别 PNG 图片中的序号和对应文件名。

## 文件结构

- `rename_files.py`: 主运行脚本，包含核心重命名逻辑。
- `image_index_extract.py`: 本地 AI 图片序号和文件名识别入口脚本。
- `rename_rules.yaml`: 定义重命名规则的配置文件。
- `config.yaml`: 本地 AI 工作流配置文件。
- `logging_config.py`: 日志配置模块。
- `src/localai/`: 本地 AI 基础模块和编排层。
- `logs/`: 存放操作日志。

## 安装要求

1. 确保已安装 Python 3.x。
2. 安装依赖项 `PyYAML`：

```bash
pip install pyyaml
```

## 本地 AI 图片识别工作流

### 1. 配置 common.env

图片目录从 `common.env` 的 `INPUT_PICTURES` 读取，默认只处理该目录下的 `.png` 文件：

```dotenv
INPUT_PICTURES=C:\Users\your_name\Pictures\input
LLAMACPP_BASE_URL=http://127.0.0.1:8080/v1
LLAMACPP_MODEL=Qwen3.6-27B-Q4_K_M
LLAMACPP_AUTOSTART=false
LLAMACPP_EXTRA_DLL_DIRS=D:\CloudStation\Python\Project\vendor
```

如果本地 `llama-server` 已经启动，保持 `LLAMACPP_AUTOSTART=false` 即可。若要由脚本自动启动，还需要在 `common.env` 中补充 `LLAMACPP_SERVER_PATH`、`LLAMACPP_MODEL_PATH` 和多模态模型需要的 `LLAMACPP_MMPROJ_PATH`。

### 2. 运行识别

```bash
python image_index_extract.py
```

调试时可只识别前几张：

```bash
python image_index_extract.py --limit 3
```

如果单张图片中条目很多，可提高模型输出上限：

```bash
python image_index_extract.py --limit 1 --max-tokens 4096
```

也可以临时覆盖图片目录：

```bash
python image_index_extract.py --input-dir C:\path\to\pngs
```

### 3. 输出结果

默认输出到：

- `output/image_index_extract/image_index_results.json`
- `output/image_index_extract/image_index_results.csv`
- `output/image_index_extract/sequence_name_map.json`

每条结果包含：原图片路径、图片文件名、识别出的序号、识别出的文件名、置信度、备注、错误信息和模型原始响应。
`sequence_name_map.json` 是最终去重后的“序号 -> 文件名”映射，可直接用于后续重命名或校验。

## 使用说明

### 1. 配置规则

在 `rename_rules.yaml` 中定义你的规则：

```yaml
remove_patterns:
  - "苏菲的世界 "      # 移除指定的字符串
  - "【预告】"          # 更多需要移除的内容

replace_patterns:
  - pattern: "十一"
    replacement: "11"   # 将 "十一" 替换为 "11"
  - pattern: "一"
    replacement: "01"
```

### 2. 运行脚本

修改 `rename_files.py` 中 `if __name__ == "__main__":` 部分的 `target_folder` 路径，然后运行：

```bash
python rename_files.py
```

### 3. 主要函数说明

- `rename_files_in_folder(folder_path, config)`: 根据 YAML 配置进行通用替换和移除。
- `rename_files_with_padded_numbers(folder_path, prefix, suffix)`: 对文件名中的数字进行补零，例如将 ` 第1集 ` 补零为 ` 第01集 `。
- `rename_files_by_regex(config, add_string, position)`: 匹配 `regex_pattern` 并在其前面（before）或后面（after）插入指定的字符串。
- `truncate_filename_after_char(folder_path, trunc_char)`: 删除文件名中指定字符及其后的所有内容。

## 注意事项

- **备份数据**：在对大量重要文件执行批量操作前，建议先在备份文件夹中进行测试。
- **日志查看**：如果重命名结果不如预期，请检查 `logs/rename.log` 查看详细的操作输出和错误信息。
