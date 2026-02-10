import bpy
import difflib
import mathutils

# ==============================================================================
# GeoNeural Core: Static Reflection & Mappings
# Version: v5.13.28 (Backported Fixes)
# ==============================================================================

_CLASS_ID_CACHE = {}
_DYNAMIC_TYPE_MAP = {}  # [NEW] 动态构建的映射表
_CACHE_BUILT = False

# [THE ROSETTA STONE] 捕捉属性类型翻译表 (保持静态以确保性能)
_CAPTURE_TYPE_MAP = {
    'FLOAT': 'FLOAT', 'INT': 'INT', 'FLOAT_VECTOR': 'FLOAT_VECTOR', 
    'FLOAT_COLOR': 'FLOAT_COLOR', 'BOOLEAN': 'BOOLEAN', 'ROTATION': 'ROTATION',
    'MATRIX': 'MATRIX', 'STRING': 'STRING',
    'VALUE': 'FLOAT', 'VECTOR': 'FLOAT_VECTOR', 'RGBA': 'FLOAT_COLOR', 'QUATERNION': 'ROTATION'
}

def _build_memory_cache():
    """
    [核心机制] 数据标准化通用化构建
    从 Blender API 动态提取合法的类型定义，建立 "Socket类名" -> "API枚举" 的映射。
    """
    global _CACHE_BUILT, _CLASS_ID_CACHE, _DYNAMIC_TYPE_MAP
    if _CACHE_BUILT: return

    # 1. 节点 ID 缓存
    for cls in bpy.types.Node.__subclasses__():
        if hasattr(cls, "bl_idname"):
            bid = cls.bl_idname
            _CLASS_ID_CACHE[bid] = bid
            short = bid.replace("GeometryNode", "").replace("ShaderNode", "").replace("FunctionNode", "").replace("CompositorNode", "").replace("TextureNode", "")
            _CLASS_ID_CACHE[short] = bid
            _CLASS_ID_CACHE[short.upper()] = bid

    # 2. [标准化] 获取官方定义的合法接口类型列表
    valid_api_types = set()
    try:
        # 尝试从 NodeTreeInterfaceSocket 获取 (Blender 4.0+)
        if hasattr(bpy.types, "NodeTreeInterfaceSocket"):
            rna_enum = bpy.types.NodeTreeInterfaceSocket.bl_rna.properties['socket_type'].enum_items
            for item in rna_enum:
                valid_api_types.add(item.identifier) # e.g. 'FLOAT', 'GEOMETRY'
    except:
        valid_api_types = {'FLOAT', 'INT', 'VECTOR', 'RGBA', 'BOOLEAN', 'ROTATION', 'MATRIX', 'GEOMETRY', 'STRING', 'OBJECT', 'COLLECTION', 'IMAGE', 'MATERIAL', 'TEXTURE', 'SHADER'}

    # 3. [通用化] 扫描所有 Socket 类并建立映射
    for cls in bpy.types.NodeSocket.__subclasses__():
        class_name = cls.__name__ # e.g. 'NodeSocketBundle'
        semantic_name = class_name.replace("NodeSocket", "").upper()
        
        # 规则 A: 直接匹配
        if semantic_name in valid_api_types:
            _DYNAMIC_TYPE_MAP[class_name] = semantic_name
            continue

        # 规则 B: [关键修复] 捆包与虚拟接口标准化 -> GEOMETRY
        # 这解决了 NodeSocketBundle 无法被识别导致回退成 Float 的问题
        if "BUNDLE" in semantic_name or "VIRTUAL" in semantic_name:
            _DYNAMIC_TYPE_MAP[class_name] = 'GEOMETRY'
            continue
            
        # 规则 C: 颜色与别名处理
        if "COLOR" in semantic_name:
            if 'RGBA' in valid_api_types: _DYNAMIC_TYPE_MAP[class_name] = 'RGBA'
        if "FLOAT" in semantic_name:
            stripped = semantic_name.replace("FLOAT", "")
            if stripped in valid_api_types: _DYNAMIC_TYPE_MAP[class_name] = stripped

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
    """
    [FIXED] 获取标准化的 API 类型定义。
    输入 'NodeSocketBundle' -> 返回 'GEOMETRY'
    """
    if not _CACHE_BUILT: _build_memory_cache()
    
    # 如果已经是合法的 API 字符串，直接返回
    if socket_idname in _DYNAMIC_TYPE_MAP.values():
        return socket_idname

    # 查表返回，默认 FLOAT
    return _DYNAMIC_TYPE_MAP.get(socket_idname, 'FLOAT')

def get_capture_socket_type(internal_data_type):
    return _CAPTURE_TYPE_MAP.get(internal_data_type, 'FLOAT')

# ==============================================================================
# [Universal Value Handler] 通用数值/资源处理器
# ==============================================================================

class ValueHandler:
    ID_DATA_MAP = {
        'OBJECT': 'objects', 'MATERIAL': 'materials',
        'COLLECTION': 'collections', 'IMAGE': 'images', 'TEXTURE': 'textures'
    }

    @staticmethod
    def apply(socket, value, context=None):
        if value is None: return

        try:
            # 1. 资源引用
            if socket.type in ValueHandler.ID_DATA_MAP and isinstance(value, str):
                data_attr = ValueHandler.ID_DATA_MAP[socket.type]
                collection = getattr(bpy.data, data_attr, None)
                if collection:
                    target_obj = collection.get(value)
                    if target_obj:
                        socket.default_value = target_obj
                        return 

            # 2. 复杂结构转换
            if isinstance(value, (list, tuple)):
                if socket.type == 'RGBA':
                    val = list(value)[:4]
                    if len(val) < 4: val += [1.0] * (4 - len(val))
                    try: socket.default_value = val
                    except: socket.default_value = mathutils.Color(val[:3]) 
                    return
                elif socket.type == 'VECTOR':
                    try: socket.default_value = value
                    except: socket.default_value = mathutils.Vector(value)
                    return
                elif socket.type == 'ROTATION':
                    try: socket.default_value = value
                    except: socket.default_value = mathutils.Euler(value[:3])
                    return
                elif socket.type == 'MATRIX':
                    try: socket.default_value = mathutils.Matrix(value)
                    except: pass
                    return

            socket.default_value = value
        except Exception as e:
            pass

def universal_set_property(node, prop_name, value):
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
                if prop_name == 'data_type' and node.bl_idname == 'GeometryNodeCaptureAttribute':
                    if val_upper in items: setattr(node, prop_name, val_upper); return True
                    mapped = get_capture_socket_type(val_upper)
                    if mapped in items: setattr(node, prop_name, mapped); return True

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