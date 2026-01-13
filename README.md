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

## 文件结构

- `rename_files.py`: 主运行脚本，包含核心重命名逻辑。
- `rename_rules.yaml`: 定义重命名规则的配置文件。
- `logging_config.py`: 日志配置模块。
- `logs/`: 存放操作日志。

## 安装要求

1. 确保已安装 Python 3.x。
2. 安装依赖项 `PyYAML`：

```bash
pip install pyyaml
```

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
