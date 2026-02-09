import bpy
import difflib

# ==============================================================================
# GeoNeural Core: Static Reflection & Mappings
# Version: v5.13.19 (Stable Data Layer)
# ==============================================================================

_CLASS_ID_CACHE = {}
_SOCKET_TYPE_MAP = {}
_CACHE_BUILT = False

# [THE ROSETTA STONE] 捕捉属性类型翻译表
# 修正依据：Blender API 报错提示 ('FLOAT', 'INT', 'BOOLEAN', 'VECTOR', 'RGBA'...)
_CAPTURE_TYPE_MAP = {
    'FLOAT': 'FLOAT',       # 修正：API 要求必须是 FLOAT
    'INT': 'INT',
    'FLOAT_VECTOR': 'VECTOR', 
    'FLOAT_COLOR': 'RGBA', 
    'BOOLEAN': 'BOOLEAN', 
    'ROTATION': 'ROTATION',
    'MATRIX': 'MATRIX',
    'STRING': 'STRING',
    
    # 兼容性冗余映射
    'VALUE': 'FLOAT',
    'VECTOR': 'VECTOR',
    'RGBA': 'RGBA'
}

def _build_memory_cache():
    global _CACHE_BUILT, _CLASS_ID_CACHE, _SOCKET_TYPE_MAP
    if _CACHE_BUILT: return

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

    _SOCKET_TYPE_MAP = {
        'VALUE': 'NodeSocketFloat', 'INT': 'NodeSocketInt', 
        'VECTOR': 'NodeSocketVector', 'RGBA': 'NodeSocketColor', 
        'BOOLEAN': 'NodeSocketBool', 'ROTATION': 'NodeSocketRotation', 
        'MATRIX': 'NodeSocketMatrix', 'GEOMETRY': 'NodeSocketGeometry',
        'STRING': 'NodeSocketString', 'OBJECT': 'NodeSocketObject',
        'COLLECTION': 'NodeSocketCollection', 'IMAGE': 'NodeSocketImage',
        'MATERIAL': 'NodeSocketMaterial', 'TEXTURE': 'NodeSocketTexture'
    }
    _CACHE_BUILT = True

def resolve_node_id(fuzzy_name):
    if not _CACHE_BUILT: _build_memory_cache()
    if not fuzzy_name: return "NodeFrame"
    
    if fuzzy_name in _CLASS_ID_CACHE: return _CLASS_ID_CACHE[fuzzy_name]
    
    norm = fuzzy_name.replace(" ", "").replace("_", "").upper()
    if norm in _CLASS_ID_CACHE: return _CLASS_ID_CACHE[norm]
    
    matches = difflib.get_close_matches(fuzzy_name, list(_CLASS_ID_CACHE.keys()), n=1, cutoff=0.6)
    if matches: return _CLASS_ID_CACHE[matches[0]]
    
    return fuzzy_name

def get_zone_api_type(socket_idname):
    mapping = {
        'NodeSocketFloat': 'FLOAT', 'NodeSocketInt': 'INT',
        'NodeSocketVector': 'VECTOR', 'NodeSocketColor': 'RGBA',
        'NodeSocketBool': 'BOOLEAN', 'NodeSocketRotation': 'ROTATION',
        'NodeSocketMatrix': 'MATRIX', 'NodeSocketString': 'STRING',
        'NodeSocketGeometry': 'GEOMETRY'
    }
    return mapping.get(socket_idname, 'FLOAT')

def get_capture_socket_type(internal_data_type):
    """将内部数据类型转换为 capture_items.new() 所需的类型参数"""
    return _CAPTURE_TYPE_MAP.get(internal_data_type, 'FLOAT')

def universal_set_property(node, prop_name, value):
    """
    [v5.13.6 Native Logic]
    宽容模式的属性设置器，支持模糊匹配和强制写入。
    这对 Math/Mix 等节点的枚举属性至关重要。
    """
    try:
        if not hasattr(node, prop_name): return False
        
        try: rna_prop = node.bl_rna.properties.get(prop_name)
        except: setattr(node, prop_name, value); return True

        if not rna_prop:
            setattr(node, prop_name, value); return True

        prop_type = rna_prop.type
        
        if prop_type == 'ENUM':
            if isinstance(value, str):
                items = [i.identifier for i in rna_prop.enum_items]
                val_upper = value.upper().replace(" ", "_")
                if val_upper in items: setattr(node, prop_name, val_upper); return True
                matches = difflib.get_close_matches(val_upper, items, n=1, cutoff=0.8)
                if matches: setattr(node, prop_name, matches[0]); return True

        elif prop_type == 'BOOLEAN':
            setattr(node, prop_name, bool(value))
            return True

        elif prop_type in {'FLOAT', 'INT'} and rna_prop.is_array:
            if not hasattr(value, "__len__"): return False
            vec = getattr(node, prop_name)
            size = len(vec)
            val_list = list(value)
            if len(val_list) > size: val_list = val_list[:size]
            while len(val_list) < size: val_list.append(0.0)
            setattr(node, prop_name, val_list)
            return True

        setattr(node, prop_name, value)
        return True
    except: return False

def load_db():
    _build_memory_cache()
    return True