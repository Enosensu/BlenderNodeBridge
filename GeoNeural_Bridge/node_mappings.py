import bpy
import json
import os
import difflib

# ==============================================================================
# 配置
# ==============================================================================
DB_FILENAME = "blender_node_schema.json"

# ==============================================================================
# 数据库服务 (Database Service)
# ==============================================================================
class NodeSchemaDatabase:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(NodeSchemaDatabase, cls).__new__(cls)
            cls._instance._reset()
        return cls._instance

    def _reset(self):
        self.nodes = {}
        self.aliases = {}
        self.meta = {}
        self.loaded = False

    def load(self):
        if self.loaded: return True
        
        json_path = os.path.join(os.path.dirname(__file__), DB_FILENAME)
        if not os.path.exists(json_path):
            # print(f"[GeoNeural] ⚠️ 数据库未找到: {DB_FILENAME}")
            return False

        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.nodes = data.get("nodes", {})
                self.aliases = data.get("alias_map", {})
                self.meta = data.get("meta", {})
                self.loaded = True
                return True
        except Exception as e:
            print(f"[GeoNeural] ❌ 数据库损坏: {e}")
            return False

    def get_alias(self, name):
        self.load()
        return self.aliases.get(name)

    def get_node_info(self, bl_idname):
        self.load()
        return self.nodes.get(bl_idname, {})

    def get_socket_map(self):
        self.load()
        return self.meta.get("socket_map", {})

db = NodeSchemaDatabase()

# ==============================================================================
# 节点解析服务 (Resolver Service)
# ==============================================================================
class NodeResolver:
    _dynamic_cache = {}

    @classmethod
    def _ensure_dynamic_cache(cls):
        if cls._dynamic_cache: return
        for node_cls in bpy.types.Node.__subclasses__():
            if hasattr(node_cls, "bl_idname"):
                bid = node_cls.bl_idname
                cls._dynamic_cache[bid] = bid
                # 注册简写 (GeometryNodeMath -> Math)
                short = bid.replace("GeometryNode", "").replace("ShaderNode", "").replace("FunctionNode", "").replace("CompositorNode", "")
                cls._dynamic_cache[short] = bid
                cls._dynamic_cache[short.upper()] = bid

    @classmethod
    def resolve_id(cls, raw_name):
        if not raw_name: return None
        
        # 1. 数据库查找
        db_match = db.get_alias(raw_name)
        if db_match: return db_match
        
        clean_name = raw_name.replace(" ", "").replace("_", "")
        db_match_clean = db.get_alias(clean_name)
        if db_match_clean: return db_match_clean
        
        # 2. 动态反射查找
        cls._ensure_dynamic_cache()
        if raw_name in cls._dynamic_cache: return cls._dynamic_cache[raw_name]
        
        # 3. 模糊搜救
        matches = difflib.get_close_matches(clean_name, cls._dynamic_cache.keys(), n=1, cutoff=0.6)
        if matches:
            found = cls._dynamic_cache[matches[0]]
            print(f"[GeoNeural] 🔧 自动纠错: {raw_name} -> {found}")
            return found
            
        return raw_name

# ==============================================================================
# 属性适配服务 (Property Adapter Service)
# ==============================================================================
class PropertyAdapter:
    
    @staticmethod
    def _safe_vector(value, size=3):
        if not hasattr(value, "__len__") or isinstance(value, str):
            try: return [float(value)] * size
            except: return None
        val_list = list(value)
        if len(val_list) >= size: return val_list[:size]
        return val_list + [0.0] * (size - len(val_list))

    @classmethod
    def set_property(cls, node, prop_name, value):
        """
        全能属性设置器：包含强制写入策略，修复 Enum 失效问题。
        """
        if not hasattr(node, prop_name): return False
        
        # 1. 获取类型信息 (优先 DB，次选反射)
        schema = db.get_node_info(node.bl_idname).get("properties", {}).get(prop_name, {})
        prop_type = schema.get("type")
        enum_opts = schema.get("options", [])

        if not prop_type:
            try:
                rna = node.bl_rna.properties.get(prop_name)
                if rna:
                    prop_type = rna.type
                    if rna.type == 'ENUM':
                        enum_opts = [i.identifier for i in rna.enum_items]
            except: pass

        # 2. 执行赋值
        try:
            # === 策略 A: 枚举智能匹配 ===
            if prop_type == 'ENUM':
                # (1) 精确匹配
                if value in enum_opts:
                    setattr(node, prop_name, value)
                    return True
                
                # (2) 归一化匹配 (Add -> ADD, Z_up -> Z_UP)
                norm_val = str(value).upper().replace(" ", "_")
                if norm_val in enum_opts:
                    setattr(node, prop_name, norm_val)
                    return True
                    
                # (3) 模糊匹配
                if enum_opts:
                    matches = difflib.get_close_matches(norm_val, enum_opts, n=1, cutoff=0.6)
                    if matches:
                        setattr(node, prop_name, matches[0])
                        return True
                
                # [关键修复] 如果上面都失败了，不要放弃！
                # 很多时候 value 本身就是对的，只是 enum_opts 列表获取不全
                # 继续向下执行到 "策略 F: 强制盲写"

            # === 策略 B: 指针引用 ===
            elif prop_type == 'POINTER' and isinstance(value, str):
                if value in bpy.data.objects: setattr(node, prop_name, bpy.data.objects[value]); return True
                if value in bpy.data.materials: setattr(node, prop_name, bpy.data.materials[value]); return True
                if value in bpy.data.images: setattr(node, prop_name, bpy.data.images[value]); return True
                if value in bpy.data.collections: setattr(node, prop_name, bpy.data.collections[value]); return True

            # === 策略 C: 基础类型 ===
            elif prop_type == 'BOOLEAN':
                bval = str(value).lower() in ("true", "yes", "on", "1")
                setattr(node, prop_name, bval); return True

            elif prop_type == 'FLOAT':
                setattr(node, prop_name, float(value)); return True
                
            elif prop_type == 'INT':
                setattr(node, prop_name, int(float(value))); return True

            elif prop_type in ('FLOAT_VECTOR', 'FLOAT_COLOR', 'BOOLEAN_VECTOR', 'INT_VECTOR'):
                size = 4 if 'COLOR' in str(prop_type) else 3
                vec = cls._safe_vector(value, size)
                if vec: setattr(node, prop_name, vec); return True

            # === 策略 F: 强制盲写 (Blind Force) ===
            # 如果上面所有特定类型的尝试都失败（或被跳过），执行此行。
            # 这解决了 "Z_UP" 正确但不在 enum_opts 列表里的情况。
            setattr(node, prop_name, value)
            return True

        except Exception as e:
            # print(f"[GeoNeural] 设置属性失败 {prop_name}={value}: {e}")
            return False

# ==============================================================================
# API 代理 (保持函数签名兼容性)
# ==============================================================================
def load_db(): return db.load()
def resolve_node_id(name): return NodeResolver.resolve_id(name)
def get_node_info(bid): return db.get_node_info(bid)
def get_socket_type_map(): return db.get_socket_map()
def universal_set_property(node, k, v, schema=None): return PropertyAdapter.set_property(node, k, v)
def get_zone_api_type(t): 
    return {"BOOL":"BOOLEAN","COLOR":"RGBA","INT":"INT","FLOAT":"FLOAT","VECTOR":"VECTOR"}.get(t.replace("NodeSocket","").upper(), "FLOAT")