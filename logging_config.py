# ./logging_config.py

import logging
import os
import sys

# 动态添加项目根目录到 sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def setup_logger(log_level=logging.DEBUG, log_file="./logs/app.log"):
    """
    设置日志记录器。

    :param log_level: 日志级别，默认为 DEBUG。
    :param log_file: 日志文件路径，默认为 ./logs/app.log。
    :return: 配置好的日志记录器。
    """
    # 创建日志文件夹
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    # 配置日志格式
    log_format = "%(asctime)s - %(levelname)s - %(module)s - %(message)s"

    # 设置日志级别
    logger = logging.getLogger()
    logger.setLevel(log_level)

    # 避免重复添加处理器
    if not logger.handlers:
        # 控制台日志处理器
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter(log_format))

        # 文件日志处理器
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(logging.Formatter(log_format))

        # 添加处理器
        logger.addHandler(console_handler)
        logger.addHandler(file_handler)

    return logger


# 单独运行时的测试代码
if __name__ == "__main__":
    # 示例日志文件路径
    log_file_path = "./logs/test_logger.log"

    # 初始化日志记录器
    logger = setup_logger(log_level=logging.INFO, log_file=log_file_path)

    # 测试日志输出
    logger.debug("This is a DEBUG message.")
    logger.info("This is an INFO message.")
    logger.warning("This is a WARNING message.")
    logger.error("This is an ERROR message.")
    logger.critical("This is a CRITICAL message.")
