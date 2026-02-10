# core/node_mappings.py
# GeoNeural Bridge v5.14.0 (AI-Native Milestone)
# 修复: 恢复 SOCKET_TYPE_TO_IDNAME 静态映射 (Type Safety)
# 功能: 提供 API 枚举标准化与 AI 模糊匹配支持

import bpy
import difflib

# ==============================================================================
# 1. 静态 Socket 类型映射 (Type Safety)
# ==============================================================================
SOCKET_TYPE_TO_IDNAME = {
    'FLOAT': 'NodeSocketFloat', 'INT': 'NodeSocketInt', 'BOOLEAN': 'NodeSocketBool',
    'VECTOR': 'NodeSocketVector', 'RGBA': 'NodeSocketColor', 'ROTATION': 'NodeSocketRotation',
    'MATRIX': 'NodeSocketMatrix', 'STRING': 'NodeSocketString', 'GEOMETRY': 'NodeSocketGeometry',
    'COLLECTION': 'NodeSocketCollection', 'OBJECT': 'NodeSocketObject', 
    'IMAGE': 'NodeSocketImage', 'MATERIAL': 'NodeSocketMaterial', 'TEXTURE': 'NodeSocketTexture',
    'MENU': 'NodeSocketMenu', 'SHADER': 'NodeSocketShader',
    'BUNDLE': 'NodeSocketBundle', 'VIRTUAL': 'NodeSocketVirtual'
}

# 反向映射 (Class Name -> Enum)
IDNAME_TO_ENUM = {v: k for k, v in SOCKET_TYPE_TO_IDNAME.items()}

# 别名映射 (AI 容错)
ALIAS_MAP = {
    'VALUE': 'FLOAT', 'INTEGER': 'INT', 'BOOL': 'BOOLEAN',
    'QUATERNION': 'ROTATION', 'COLOR': 'RGBA',
    'FLOAT_VECTOR': 'VECTOR', 'FLOAT_COLOR': 'RGBA'
}

def get_socket_class_name(enum_type):
    """根据 API 枚举获取类名"""
    norm = str(enum_type).upper().replace(" ", "_")
    return SOCKET_TYPE_TO_IDNAME.get(norm, 'NodeSocketFloat')

def get_api_enum(class_name_or_type):
    """标准化 API 枚举"""
    raw = str(class_name_or_type).strip()
    if raw in IDNAME_TO_ENUM: return IDNAME_TO_ENUM[raw]
    upper = raw.upper().replace(" ", "_")
    if upper in ALIAS_MAP: return ALIAS_MAP[upper]
    if upper in SOCKET_TYPE_TO_IDNAME: return upper
    return 'FLOAT'

# ==============================================================================
# 2. 动态节点数据库与模糊匹配 (AI 兼容性核心)
# ==============================================================================

class NodeNameMatcher:
    _CLASS_ID_CACHE = {}  
    _CACHE_BUILT = False

    @classmethod
    def _build_cache(cls):
        if cls._CACHE_BUILT: return
        
        # 1. 注册所有 Blender 节点
        for node_cls in bpy.types.Node.__subclasses__():
            if hasattr(node_cls, "bl_idname"):
                bid = node_cls.bl_idname
                name = node_cls.__name__
                
                # 注册全名
                cls._CLASS_ID_CACHE[bid] = bid
                # 注册简写 (如 GeometryNodeMath -> Math)
                short = bid.replace("GeometryNode", "").replace("ShaderNode", "").replace("FunctionNode", "")
                cls._CLASS_ID_CACHE[short] = bid
                cls._CLASS_ID_CACHE[short.upper()] = bid
                cls._CLASS_ID_CACHE[name] = bid

        # 2. 手动补全 AI 常用别名
        cls._CLASS_ID_CACHE["NodeFrame"] = "NodeFrame"
        cls._CLASS_ID_CACHE["Frame"] = "NodeFrame"
        
        cls._CACHE_BUILT = True

    @classmethod
    def resolve_idname(cls, fuzzy_name):
        if not fuzzy_name: return "NodeFrame"
        if not cls._CACHE_BUILT: cls._build_cache()
        
        # 1. 精确匹配
        if fuzzy_name in cls._CLASS_ID_CACHE:
            return cls._CLASS_ID_CACHE[fuzzy_name]
        
        # 2. 模糊匹配 (拼写错误修正)
        keys = list(cls._CLASS_ID_CACHE.keys())
        matches = difflib.get_close_matches(fuzzy_name, keys, n=1, cutoff=0.6)
        if matches:
            return cls._CLASS_ID_CACHE[matches[0]]
            
        return fuzzy_name

def resolve_node_idname(fuzzy_name):
    return NodeNameMatcher.resolve_idname(fuzzy_name)

def load_db():
    NodeNameMatcher._build_cache()
    return True