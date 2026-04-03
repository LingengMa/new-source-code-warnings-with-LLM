"""
配置文件
"""
import os

# 路径配置
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR = os.path.join(BASE_DIR, "input")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
REPOSITORY_DIR = os.path.join(INPUT_DIR, "repository")

# 数据文件
DATA_JSON = os.path.join(INPUT_DIR, "data_filtered.json")
OUTPUT_JSON = os.path.join(OUTPUT_DIR, "slices.json")

# 切片参数
BACKWARD_DEPTH = 10  # 后向切片深度
FORWARD_DEPTH = 10   # 前向切片深度
MIN_SLICE_LINES = 5  # 最小切片行数（少于此数则包含整个函数）

# 按 rule_id 覆盖切片深度
# 格式：{ rule_id_前缀或全名: {"backward": int, "forward": int} }
# 对于"返回值未检查空指针"类规则，警告行本身就是关键，
# 后向只需追溯少量层（拿到控制流上下文即可），前向追踪变量使用即可。
RULE_SLICE_DEPTH_OVERRIDES: dict = {
    # 返回值空值一致性检查：只需看警告行及其返回值变量的后续使用
    "cpp/inconsistent-null-check":        {"backward": 3, "forward": 5},
    # 空指针解引用：同上，重点是解引用路径
    "cpp/nullptr-dereference":             {"backward": 3, "forward": 5},
    # 使用后释放：需要追溯定义和后续使用，适当放宽
    "cpp/use-after-free":                  {"backward": 5, "forward": 8},
    # 缓冲区溢出类：需要更多上下文
    "cpp/overflow-buffer":                 {"backward": 5, "forward": 5},
    # 整数溢出
    "cpp/integer-overflow-tainted":        {"backward": 5, "forward": 5},
}

# AST 修复配置
ENABLE_AST_FIX = True  # 是否启用 AST 语法修复
LANGUAGE = "c"  # 默认语言

# 返回值变量使用增强（def-use augmentation）
# 对警告行的赋值左值变量，追踪其在函数内的所有后续使用节点并纳入切片，
# 解决"变量被赋值后的解引用/使用上下文缺失"问题（如 fd = func() 后 fd->field 的使用）
ENABLE_DEF_USE_AUGMENTATION = True

# 输出配置
OUTPUT_FORMAT = "json"  # json 或 markdown
VERBOSE = True  # 是否输出详细日志

# PDG 边类型
DDG_LABEL = "DDG"  # 数据依赖边
CDG_LABEL = "CDG"  # 控制依赖边
CFG_LABEL = "CFG"  # 控制流边

# 占位符
PLACEHOLDER = "    /* PLACEHOLDER: Code omitted for brevity */"

# 分块保存和断点续传配置
CHUNK_SIZE = 100  # 每个chunk保存的任务数
ENABLE_CHECKPOINT = True  # 是否启用断点续传
CHECKPOINT_FILE = os.path.join(OUTPUT_DIR, "checkpoint.json")  # 断点文件
PROGRESS_FILE = os.path.join(OUTPUT_DIR, "progress.json")  # 进度文件

# 多进程配置
NUM_PROCESSES = 5  # 并行进程数
ENABLE_MULTIPROCESSING = True  # 是否启用多进程

# 空切片处理配置
EMPTY_SLICE_FALLBACK = True  # 空切片时是否使用上下文提取作为回退方案
CONTEXT_SIZE = 50  # 上下文提取的窗口大小(前后各取多少行)

# 函数调用提取配置
EXTRACT_FUNCTION_CALLS = True  # 是否提取切片中调用的函数的完整定义
INCLUDE_STDLIB_FUNCTIONS = False  # 是否包含标准库函数（通常不需要）
MAX_FUNCTION_DEFINITIONS = 10  # 最多提取多少个函数定义（避免结果过大）
