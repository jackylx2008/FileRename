import logging
import os
import re

import yaml  # 注意要先安装 pyyaml

from logging_config import setup_logger  # 如果你不需要日志，可以去掉相关逻辑

# 初始化日志（可调整级别和文件）
logger = setup_logger(log_level=logging.INFO, log_file="./logs/rename.log")


def read_config(config_path="./rename_rules.yml"):
    """读取 YAML 配置文件"""
    logger.info(f"读取配置文件: {config_path}")
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
        logger.info("配置文件加载成功")
        return config


def rename_files_in_folder(folder_path, config):
    """
    根据 config 里的正则配置，对 folder_path 下的文件名进行批量处理并重命名。
    1) remove_patterns: 用 re.sub(pattern, '', filename)
    2) replace_patterns: 用 re.sub(pattern, replacement, filename)
    """

    # 提取移除和替换规则
    remove_patterns = config.get("remove_patterns", [])
    replace_patterns = config.get("replace_patterns", [])

    logger.info(f"开始处理文件夹: {folder_path}")
    logger.debug(f"remove_patterns: {remove_patterns}")
    logger.debug(f"replace_patterns: {replace_patterns}")

    if not os.path.isdir(folder_path):
        logger.error(f"目标路径 {folder_path} 不是有效的文件夹。")
        return

    # 遍历目标文件夹下的所有文件
    for filename in os.listdir(folder_path):
        old_path = os.path.join(folder_path, filename)

        # 如果需要遍历子文件夹，可在此判断并递归
        if os.path.isdir(old_path):
            rename_files_in_folder(old_path, config)
            continue

        # 跳过非普通文件（如文件夹、链接等）
        if not os.path.isfile(old_path):
            logger.debug(f"跳过非普通文件: {old_path}")
            continue

        new_filename = filename

        # (1) 应用 remove_patterns（全部替换为空串）
        for pattern in remove_patterns:
            new_filename = re.sub(pattern, "", new_filename)

        # (2) 应用 replace_patterns（支持%d通配符）
        for rule in replace_patterns:
            pat = rule.get("pattern", "")
            rep = rule.get("replacement", "")
            if "%d" in pat:
                regex_pat, regex_rep = pattern_to_regex_and_replacement(pat, rep)
                new_filename = re.sub(regex_pat, regex_rep, new_filename)
            else:
                new_filename = re.sub(pat, rep, new_filename)

        # 去除首尾空白
        new_filename = new_filename.strip()

        if new_filename == filename:
            logger.debug(f"文件名无变化: {filename}")
            continue

        # 构造新文件路径
        new_path = os.path.join(folder_path, new_filename)

        if os.path.exists(new_path):
            logger.warning(f"新文件名已存在，跳过: {new_path}")
            continue

        # 执行重命名
        try:
            os.rename(old_path, new_path)
            logger.info(f"重命名成功: {filename} -> {new_filename}")
        except Exception as e:
            logger.error(f"重命名失败: {old_path} -> {new_path}, 原因: {e}")


def truncate_filename_after_char(folder_path, trunc_char):
    """
    遍历指定文件夹，将文件名中第一个出现的 trunc_char 及其后所有内容删除，保留扩展名。

    :param folder_path: 目标文件夹路径
    :param trunc_char: 需要截断的字符
    """
    if not os.path.isdir(folder_path):
        logging.error(f"目标路径 {folder_path} 不是有效的文件夹。")
        return

    for filename in os.listdir(folder_path):
        old_path = os.path.join(folder_path, filename)

        if not os.path.isfile(old_path):
            logging.debug(f"跳过非普通文件: {old_path}")
            continue

        name, ext = os.path.splitext(filename)

        if trunc_char in name:
            new_name = name.split(trunc_char, 1)[0].strip()  # 取第一个截断字符前的部分
            new_filename = f"{new_name}{ext}"

            if new_filename == filename:
                logging.debug(f"文件名无变化: {filename}")
                continue

            new_path = os.path.join(folder_path, new_filename)

            if os.path.exists(new_path):
                logging.warning(f"新文件名已存在，跳过: {new_path}")
                continue

            try:
                os.rename(old_path, new_path)
                logging.info(f"重命名成功: {filename} -> {new_filename}")
            except Exception as e:
                logging.error(f"重命名失败: {old_path} -> {new_path}, 原因: {e}")


def sort_files_in_folder(folder_path, ascending=True):
    """
    列出文件夹下所有文件（不含子文件夹），根据 ascending 参数决定按文件名升序或降序排序。
    返回排序后的文件列表。
    """
    if not os.path.isdir(folder_path):
        logger.error(f"错误：{folder_path} 不是有效的文件夹路径。")
        return []

    file_list = [
        f
        for f in os.listdir(folder_path)
        if os.path.isfile(os.path.join(folder_path, f))
    ]

    # ascending=False => 按降序排序
    file_list.sort(reverse=not ascending)
    return file_list


def rename_files_keep_name(folder_path, ascending=True, keep_suffix=""):
    """
    先对文件进行排序（默认降序），然后批量重命名。
    重命名规则： 序号(补零) + [可选后缀] + 原文件名(去掉原有的数字前缀)

    参数：
      folder_path: 文件夹路径
      ascending:   是否升序排序（默认 False = 降序）
      keep_suffix: 可选字符串，若不为空则加在序号后

    示例：
      - 原文件： 29两种文化(1).m4a / 27明信片(1).m4a
      - 排序： 默认降序
      - keep_suffix=""  -> 01两种文化(1).m4a / 02明信片(1).m4a
      - keep_suffix="suffix" -> 01_suffix两种文化(1).m4a / 02_suffix明信片(1).m4a
    """

    # 第一步：获取排序后的文件列表
    sorted_files = sort_files_in_folder(folder_path, ascending=ascending)

    if not sorted_files:
        logger.warning("没有找到任何文件。")
        return

    total_files = len(sorted_files)
    num_digits = len(str(total_files))  # 序号补零位数

    logger.info(
        f"准备在目录 {folder_path} 内重命名 {total_files} 个文件，"
        f"升序={ascending}, keep_suffix={keep_suffix}"
    )

    for i, old_filename in enumerate(sorted_files, start=1):
        old_path = os.path.join(folder_path, old_filename)

        if not os.path.isfile(old_path):
            logger.warning(f"跳过非文件或不存在的路径：{old_filename}")
            continue

        # 去掉开头的数字部分（只保留后面的名字）
        base_name = old_filename
        while base_name and base_name[0].isdigit():
            base_name = base_name[1:]

        # 新文件名： 序号 + [可选后缀] + 原名字
        seq_str = str(i).zfill(num_digits)
        if keep_suffix:
            new_filename = f"{seq_str}_{keep_suffix}{base_name}"
        else:
            new_filename = "苏菲的世界_" + f"{seq_str}{base_name}"

        new_path = os.path.join(folder_path, new_filename)

        # if os.path.exists(new_path):
        #     logger.warning(f"目标已存在，跳过重命名：{new_filename}")
        #     continue

        try:
            os.rename(old_path, new_path)
            logger.info(f"重命名成功：{old_filename} -> {new_filename}")
        except Exception as e:
            logger.error(f"重命名失败：{old_filename} -> {new_filename}，错误：{e}")


def rename_files_with_suffix(folder_path, suffix, ascending=False):
    """
    先对文件进行排序（默认降序），然后批量重命名。
    重命名规则： 序号(补零) + 下划线 + 后缀 + 原扩展名

    例如：
      - 原文件： 3file.jpg / 2file.png / 1file.txt
      - 排序： 默认降序
      - 结果： 001_suffix.jpg / 002_suffix.png / 003_suffix.txt

    说明：
      - 使用外部的 sort_files_in_folder(folder_path, ascending=...) 获取排序后的文件名列表
      - 所有日志通过 logger 输出，而非 print。
    """
    # 第一步：获取排序后的文件列表
    sorted_files = sort_files_in_folder(folder_path, ascending=ascending)

    if not sorted_files:
        logger.warning("没有找到任何文件。")
        return

    total_files = len(sorted_files)
    num_digits = len(str(total_files))  # 10~99 => 2位, 100~999 => 3位

    logger.info(
        f"准备在目录 {folder_path} 内重命名 {total_files} 个文件，"
        f"后缀={suffix}，升序={ascending}"
    )

    # 第二步：循环重命名
    for i, old_filename in enumerate(sorted_files, start=1):
        old_path = os.path.join(folder_path, old_filename)

        # 若包含目录名，或文件不存在则跳过
        if not os.path.isfile(old_path):
            logger.warning(f"跳过非文件或不存在的路径：{old_filename}")
            continue

        # 分离扩展名
        _, ext_part = os.path.splitext(old_filename)

        # 组装新文件名： 序号(补零) + '_' + 后缀 + 原扩展名
        seq_str = str(i).zfill(num_digits)

        # 若 suffix 为空，则不加下划线（更健壮）
        if suffix:
            new_filename = f"{seq_str}_{suffix}{ext_part}"
        else:
            new_filename = f"{seq_str}{ext_part}"

        new_path = os.path.join(folder_path, new_filename)

        # 若新文件名已存在，跳过
        if os.path.exists(new_path):
            logger.warning(f"目标已存在，跳过重命名：{new_filename}")
            continue

        try:
            os.rename(old_path, new_path)
            logger.info(f"重命名成功：{old_filename} -> {new_filename}")
        except Exception as e:
            logger.error(f"重命名失败：{old_filename} -> {new_filename}，错误：{e}")


def rename_files_with_prefix(folder_path, prefix, suffix, ascending=True):
    """
    先对文件进行排序（默认降序），然后批量重命名。
    重命名规则： 前缀 + 下划线 + 序号(补零) + 原扩展名
    例如：
      - 原文件： file3.jpg / file2.png / file1.txt
      - 排序： 默认降序
      - 结果： prefix_001.jpg / prefix_002.png / prefix_003.txt
    所有日志通过 logger 输出，而非 print。
    """
    # 第一步：获取排序后的文件列表
    sorted_files = sort_files_in_folder(folder_path, ascending=ascending)

    if not sorted_files:
        logger.warning("没有找到任何文件。")
        return

    total_files = len(sorted_files)
    # 动态计算需要的补零位数
    num_digits = len(str(total_files))  # 例如10~99 => 2位, 100~999 => 3位

    logger.info(
        f"准备在目录 {folder_path} 内重命名 {total_files} 个文件，前缀={prefix}, 后缀={suffix} 升序={ascending}"
    )

    # 第二步：循环重命名
    for i, old_filename in enumerate(sorted_files, start=1):
        # 分离文件名和扩展名
        name_part, ext_part = os.path.splitext(old_filename)
        seq_str = str(i).zfill(num_digits)  # 补零序号
        new_filename = f"{prefix}{seq_str}{suffix}{ext_part}"

        old_path = os.path.join(folder_path, old_filename)
        new_path = os.path.join(folder_path, new_filename)

        # 检测新文件名是否已存在，若存在则跳过
        if os.path.exists(new_path):
            logger.warning(f"目标已存在，跳过重命名：{new_filename}")
            continue

        try:
            os.rename(old_path, new_path)
            logger.info(f"重命名成功：{old_filename} -> {new_filename}")
        except Exception as e:
            logger.error(f"重命名失败：{old_filename} -> {new_filename}，错误：{e}")


def rename_files_by_regex(config, add_string, add_position="after"):
    """
    根据 config 中的 regex_pattern 规则，遍历指定扩展名的文件，符合正则匹配的文件按规则重命名。
    在匹配的文件名中指定位置增加指定的字符串。

    :param config: 配置字典，包含文件夹路径、正则匹配模式等
    :param add_string: 要增加的字符串
    :param add_position: 字符串插入位置，可以是 'before' 或 'after'，默认是 'after'
    """
    target_folder = config.get("target_folder")
    regex_pattern = config.get("regex_pattern")
    file_extension = config.get("file_extension", "")  # 默认为空，表示所有文件

    if not target_folder or not regex_pattern or not add_string:
        logger.error(
            "配置中缺少必需的字段: target_folder 或 regex_pattern 或 add_string"
        )
        return

    if not os.path.isdir(target_folder):
        logger.error(f"目标路径 {target_folder} 不是有效的文件夹。")
        return

    logger.info(f"开始处理文件夹: {target_folder}")

    # 如果 regex_pattern 是一个列表，则遍历每个正则表达式
    if isinstance(regex_pattern, list):
        regex_patterns = regex_pattern
    else:
        regex_patterns = [regex_pattern]  # 如果是字符串，则变成单元素列表

    # 遍历目标文件夹下的所有文件
    for filename in os.listdir(target_folder):
        old_path = os.path.join(target_folder, filename)

        if not os.path.isfile(old_path):
            logger.debug(f"跳过非普通文件: {old_path}")
            continue

        # 如果配置了扩展名，且文件名不以该扩展名结尾，则跳过
        if file_extension and not filename.lower().endswith(file_extension.lower()):
            continue

        # 检查文件名是否符合任何一个正则模式
        for pattern in regex_patterns:
            if re.search(pattern, filename):
                # 找到匹配，进行重命名
                match = re.search(pattern, filename)
                if match:
                    if add_position == "before":
                        # 在匹配位置前添加 add_string
                        new_filename = (
                            filename[: match.start()]
                            + add_string
                            + filename[match.start() :]
                        )
                    elif add_position == "after":
                        # 在匹配位置后添加 add_string
                        new_filename = (
                            filename[: match.end()]
                            + add_string
                            + filename[match.end() :]
                        )
                    else:
                        logger.error(
                            "无效的 add_position 参数，必须是 'before' 或 'after'"
                        )
                        continue

                    # 构造新文件路径
                    new_path = os.path.join(target_folder, new_filename)

                    # 如果新文件名已存在，则跳过
                    if os.path.exists(new_path):
                        logger.warning(f"新文件名已存在，跳过: {new_path}")
                        continue

                    # 执行重命名
                    try:
                        os.rename(old_path, new_path)
                        logger.info(f"重命名成功: {filename} -> {new_filename}")
                    except Exception as e:
                        logger.error(f"重命名失败: {old_path} -> {new_path}, 原因: {e}")
                break  # 只要找到第一个匹配的正则，就停止继续匹配其他的正则
        else:
            logger.debug(f"文件名不符合任何正则匹配: {filename}")


def rename_files_with_padded_numbers(folder_path, prefix="第", suffix="集"):
    """
    根据文件总数确定序号位数（如001、002），对符合模式的文件名进行批量重命名，支持递归子文件夹。

    :param folder_path: 目标文件夹路径
    :param prefix: 文件名前缀（如"第"）
    :param suffix: 文件名后缀（如"集"）
    """
    if not os.path.isdir(folder_path):
        logger.error(f"目标路径 {folder_path} 不是有效的文件夹。")
        return

    # 获取所有文件（包括子文件夹中的文件）
    files = []
    for root, _, filenames in os.walk(folder_path):
        for filename in filenames:
            files.append(os.path.join(root, filename))

    total_files = len(files)
    num_digits = len(str(total_files))  # 计算补零位数

    logger.info(f"开始批量重命名，文件总数: {total_files}，补零位数: {num_digits}")

    for file_path in files:
        filename = os.path.basename(file_path)

        # 跳过非普通文件
        if not os.path.isfile(file_path):
            logger.debug(f"跳过非普通文件: {file_path}")
            continue

        # 匹配文件名中的数字
        match = re.search(rf"{prefix}(\d+){suffix}", filename)
        if match:
            number = int(match.group(1))  # 提取集数
            padded_number = str(number).zfill(num_digits)  # 补零

            # 构造新的文件名
            new_filename = re.sub(
                rf"{prefix}(\d+){suffix}",
                f"{prefix}{padded_number}{suffix}",
                filename,
            )

            new_path = os.path.join(os.path.dirname(file_path), new_filename)

            # 检查新文件名是否存在
            if os.path.exists(new_path):
                logger.warning(f"目标已存在，跳过重命名：{new_filename}")
                continue

            try:
                os.rename(file_path, new_path)
                logger.info(f"重命名成功：{filename} -> {new_filename}")
            except Exception as e:
                logger.error(f"重命名失败：{file_path} -> {new_path}，原因：{e}")
        else:
            logger.debug(f"文件名不符合模式，跳过：{filename}")


def pattern_to_regex_and_replacement(pattern, replacement):
    # 将pattern中的%d转为(\d+)，其余部分re.escape
    parts = pattern.split("%d")
    regex_pat = ""
    for i, part in enumerate(parts):
        regex_pat += re.escape(part)
        if i < len(parts) - 1:
            regex_pat += r"(\d+)"  # 支持多位数字
    # replacement中每个%d依次替换为\1、\2...
    group_count = len(parts) - 1
    for i in range(1, group_count + 1):
        replacement = replacement.replace("%d", f"\\{i}", 1)
    return regex_pat, replacement


if __name__ == "__main__":
    # 指定 YAML 规则文件
    config = read_config(r"./rename_rules.yaml")

    # for i in range(1, 8):
    #     target_folder = f"C:/Users/bcjt_/OneDrive/Desktop/output1/《哈利·波特》1-7部精品中文有声书全集  J.K.罗琳原著，光合积木演播/第{i}部/"
    #
    #     rename_files_with_padded_numbers(target_folder)  # 文件名补零

    target_folder = r"D:\CloudStation\有声书\一句顶一万句   王明军演播   茅盾文学奖获奖作品   刘震云   中国人自己的《百年孤独》"
    rename_files_with_padded_numbers(target_folder, prefix=" ", suffix=" ")

    # truncate_filename_after_char(config.target_folder, "【")

    # rename_files_with_prefix(
    #     r"D:/CloudStation/Python/Project/Mp3_Processor/mp3_files/output",
    #     "《哈利·波特》第4部 第",
    #     "集",
    # )

    # 调用重命名函数并传入已加载的配置、要增加的字符串和插入位置
    # rename_files_by_regex(config, "审批单-", "before")
