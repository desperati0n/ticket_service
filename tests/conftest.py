"""测试配置强制使用可重复运行的内存仓储。"""

import os


# 单元测试使用内存仓储，集成运行仍可选择真实双库。
os.environ["STORAGE_BACKEND"] = "memory"

