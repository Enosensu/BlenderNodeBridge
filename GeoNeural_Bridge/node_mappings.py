import bpy
import json
import os

# ==============================================================================
# 配置：数据库标准命名
# ==============================================================================
DB_FILENAME = "blender_node_schema.json"

# ==============================================================================
# 全局缓存 (运行时加载，避免重复IO)
# ==============================================================================
_DB_NODES = {}      # 节点详细信息库
_DB_ALIASES = {}    # 别名反向查找表 (UI名/旧名 -> 真实ID)
_DB_META = {}       # 元数据 (包含 socket_map 等)

def load_db():
    """
    加载标准数据库文件。
    该文件应由 extract_blender_nodes.py 生成并放入插件目录。
    """
    global _DB_NODES, _DB_ALIASES, _DB_META
    
    # 如果已加载，直接返回 True
    if _DB_NODES:
        return True

    # 获取当前脚本所在目录的 JSON 路径
    json_path = os.path.join(os.path.dirname(__file__), DB_FILENAME)
    
    if not os.path.exists(json_path):
        print(f"[GeoNeural] 严重错误: 找不到数据库文件 '{DB_FILENAME}'")
        print(f"[GeoNeural] 请运行提取脚本并将生成的 JSON 放入插件目录。")
        return False

    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
            # 1. 加载节点数据
            _DB_NODES = data.get("nodes", {})
            
            # 2. 加载别名映射 (UI Name -> bl_idname)
            _DB_ALIASES = data.get("alias_map", {})
            
            # 3. 加载元数据 (包含 Socket 类型映射表)
            _DB_META = data.get("meta", {})
            
            print(f"[GeoNeural] 数据库已加载: {_DB_META.get('version', '未知版本')}")
            print(f"   - 节点数量: {len(_DB_NODES)}")
            print(f"   - 索引条目: {len(_DB_ALIASES)}")
            return True
            
    except Exception as e:
        print(f"[GeoNeural] JSON 解析错误: {e}")
        return False

def resolve_node_id(name):
    """
    核心功能：将任意名称（UI名、旧枚举名、简化名）解析为真实的 bl_idname。
    完全依赖数据库中的 alias_map。
    """
    # 确保数据库已加载
    if not _DB_ALIASES: 
        if not load_db(): return name # 加载失败则原样返回
    
    # 1. 精确匹配 (最快)
    if name in _DB_ALIASES:
        return _DB_ALIASES[name]
    
    # 2. 容错匹配 (去空格，例如 "Join Geometry" -> "JoinGeometry")
    if name:
        no_space = name.replace(" ", "")
        if no_space in _DB_ALIASES:
            return _DB_ALIASES[no_space]
        
        # 3. 容错匹配 (全大写下划线，针对旧代码风格，如 "JOIN_GEOMETRY")
        upper_snake = name.upper().replace(" ", "_")
        if upper_snake in _DB_ALIASES:
            return _DB_ALIASES[upper_snake]
        
    # 查不到则原样返回，交由 Blender 尝试处理
    return name

def get_node_info(bl_idname):
    """
    获取节点的完整 Schema 信息 (包含 inputs, outputs, properties)。
    """
    if not _DB_NODES: load_db()
    return _DB_NODES.get(bl_idname, {})

def get_socket_type_map():
    """
    获取 C++ 类型到 Python 类型的映射表。
    例如: "Vector" -> "NodeSocketVector"
    """
    if not _DB_META: load_db()
    return _DB_META.get("socket_map", {})

def get_zone_api_type(bl_socket_type):
    """
    [新增] 将 Python Socket 类型转换为 Repeat/Simulation Zone API 需要的枚举。
    例如: "NodeSocketVector" -> "VECTOR"
    """
    # 移除前缀
    raw = bl_socket_type.replace("NodeSocket", "").upper()
    
    # 特殊映射表 (Blender API 特异性)
    MAPPING = {
        "BOOL": "BOOLEAN",
        "COLOR": "RGBA",       # Blender Zone API 中使用 RGBA 而非 COLOR
        "INT": "INT",
        "FLOAT": "FLOAT",
        "VECTOR": "VECTOR",
        "STRING": "STRING",
        "OBJECT": "OBJECT",
        "COLLECTION": "COLLECTION",
        "IMAGE": "IMAGE",
        "MATERIAL": "MATERIAL",
        "GEOMETRY": "GEOMETRY",
        "ROTATION": "ROTATION",
        "MATRIX": "MATRIX"
    }
    return MAPPING.get(raw, "FLOAT") # 默认安全回退到 FLOAT

def validate_enum(prop_name, value, prop_info):
    """
    校验枚举值是否合法。
    数据库 V10 已经将全局枚举展开到了 prop_info['options'] 中。
    """
    options = prop_info.get("options", [])
    
    # 如果 Schema 中没有定义选项（空列表），则默认不做限制，返回 True
    if not options: 
        return True 
    
    # 1. 精确匹配
    if value in options: 
        return True
    
    # 2. 大写匹配 (解决 AI 输出小写 "z_up" 但 Blender 需要 "Z_UP" 的情况)
    if isinstance(value, str) and value.upper() in options: 
        return True
    
    return False