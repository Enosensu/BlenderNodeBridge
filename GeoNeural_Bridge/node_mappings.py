import bpy
import difflib

# ==============================================================================
# 配置：V9.0 Final Core (存档点)
# ==============================================================================
# 纯内存反射架构，无文件依赖，无数据库文件。
# 实现了 ID 解析、属性适配、类型推导的实时化。

# ==============================================================================
# 1. 静态反射缓存
# ==============================================================================
_CLASS_ID_CACHE = {}
_SOCKET_TYPE_MAP = {}
_CACHE_BUILT = False

def _build_memory_cache():
    global _CACHE_BUILT, _CLASS_ID_CACHE, _SOCKET_TYPE_MAP
    if _CACHE_BUILT: return

    # A. 建立节点 ID 索引
    for cls in bpy.types.Node.__subclasses__():
        if hasattr(cls, "bl_idname"):
            bid = cls.bl_idname
            _CLASS_ID_CACHE[bid] = bid
            short = bid.replace("GeometryNode", "").replace("ShaderNode", "").replace("FunctionNode", "").replace("CompositorNode", "").replace("TextureNode", "")
            _CLASS_ID_CACHE[short] = bid
            _CLASS_ID_CACHE[short.upper()] = bid
            if hasattr(cls, "bl_label"):
                _CLASS_ID_CACHE[cls.bl_label] = bid
                _CLASS_ID_CACHE[cls.bl_label.upper()] = bid

    # B. Socket 类型映射 (递归全量)
    def get_subs(cls):
        return set(cls.__subclasses__()).union([s for c in cls.__subclasses__() for s in get_subs(c)])
    
    for cls in get_subs(bpy.types.NodeSocket):
        bid = getattr(cls, "bl_idname", None)
        if not bid: continue
        api = bid.replace("NodeSocket", "").upper()
        if api == "BOOL": api = "BOOLEAN"
        if api == "COLOR": api = "RGBA"
        _SOCKET_TYPE_MAP[bid] = api

    # 兜底补充
    _SOCKET_TYPE_MAP["NodeSocketGeometry"] = "GEOMETRY"
    _SOCKET_TYPE_MAP["NodeSocketShader"] = "SHADER"
    _SOCKET_TYPE_MAP["NodeSocketVirtual"] = "FLOAT" 
    
    _CACHE_BUILT = True

# ==============================================================================
# 2. 核心服务：ID 解析
# ==============================================================================
def resolve_node_id(raw_name):
    if not raw_name: return None
    _build_memory_cache()
    
    if raw_name in _CLASS_ID_CACHE: return _CLASS_ID_CACHE[raw_name]
    
    clean = raw_name.replace(" ", "").replace("_", "")
    if clean in _CLASS_ID_CACHE: return _CLASS_ID_CACHE[clean]
    
    upper = clean.upper()
    if upper in _CLASS_ID_CACHE: return _CLASS_ID_CACHE[upper]
    
    matches = difflib.get_close_matches(upper, _CLASS_ID_CACHE.keys(), n=1, cutoff=0.6)
    if matches: return _CLASS_ID_CACHE[matches[0]]
    
    return raw_name

# ==============================================================================
# 3. 核心服务：通用属性写入 (V9.0 强制策略)
# ==============================================================================
def universal_set_property(node, prop_name, value, schema_props=None):
    if not hasattr(node, prop_name): return False
    
    # 实时反射获取属性定义
    rna_prop = node.bl_rna.properties.get(prop_name)
    if not rna_prop: 
        try: setattr(node, prop_name, value); return True
        except: return False

    prop_type = rna_prop.type
    
    try:
        if prop_type == 'ENUM':
            enum_items = [i.identifier for i in rna_prop.enum_items]
            # 1. 精确
            if value in enum_items: 
                setattr(node, prop_name, value); return True
            # 2. 归一化
            norm_val = str(value).upper().replace(" ", "_")
            if norm_val in enum_items: 
                setattr(node, prop_name, norm_val); return True
            # 3. 模糊
            matches = difflib.get_close_matches(norm_val, enum_items, n=1, cutoff=0.6)
            if matches: 
                setattr(node, prop_name, matches[0]); return True
            # 4. 强写
            setattr(node, prop_name, value); return True

        elif prop_type == 'BOOLEAN':
            bval = str(value).lower() in ("true", "yes", "on", "1")
            setattr(node, prop_name, bval); return True

        elif prop_type in ('FLOAT', 'INT'):
            val = float(value)
            setattr(node, prop_name, val if prop_type == 'FLOAT' else int(val)); return True

        elif prop_type in ('FLOAT_VECTOR', 'FLOAT_COLOR', 'BOOLEAN_VECTOR', 'INT_VECTOR'):
            size = rna_prop.array_length
            val_list = list(value) if hasattr(value, "__iter__") and not isinstance(value, str) else [float(value)]
            if len(val_list) < size: val_list += [0.0] * (size - len(val_list))
            setattr(node, prop_name, val_list[:size]); return True

        elif prop_type == 'POINTER' and isinstance(value, str):
            target_type = rna_prop.fixed_type
            if target_type == 'Object' and value in bpy.data.objects: setattr(node, prop_name, bpy.data.objects[value]); return True
            elif target_type == 'Material' and value in bpy.data.materials: setattr(node, prop_name, bpy.data.materials[value]); return True
            elif target_type == 'Image' and value in bpy.data.images: setattr(node, prop_name, bpy.data.images[value]); return True
            elif target_type == 'Collection' and value in bpy.data.collections: setattr(node, prop_name, bpy.data.collections[value]); return True

        setattr(node, prop_name, value)
        return True
    except: return False

# ==============================================================================
# 4. API 代理
# ==============================================================================
def load_db():
    _build_memory_cache()
    return True

def get_node_info(bl_idname):
    # 不需要具体的 Schema，返回空即可，__init__ 已不再强依赖此函数做过滤
    return {}

def get_socket_type_map():
    _build_memory_cache()
    return _SOCKET_TYPE_MAP

def get_zone_api_type(bl_socket_type):
    _build_memory_cache()
    # 优先查表，查不到算法兜底
    return _SOCKET_TYPE_MAP.get(bl_socket_type, bl_socket_type.replace("NodeSocket", "").upper())