# core/node_mappings.py
# GeoNeural Bridge v5.14.99 (The Brain Protocol - Absolute Priority)
# 修复: 增加上下文优先级 (Shader > Geometry)，防止 CompositorNode 截胡导致创建失败。
# 修复: 适配 Blender 4.0 规范，get_api_enum 精确返回 FLOAT_VECTOR 等标准枚举。

import bpy
import difflib
import re

# ==============================================================================
# 0. 全局智能文本引擎 (The Brain)
# ==============================================================================

class TextSmartEngine:
    @staticmethod
    def strip_blender_api_prefix(text):
        """动态剥离 Blender 常见的底层 API 前缀/后缀，提取核心语义"""
        s = str(text).upper()
        prev = ""
        # 循环递归剥离，确保 NODE_SOCKET_ 这种多重前缀被彻底清理
        while s != prev:
            prev = s
            s = re.sub(r'^((NODE|SOCKET|GEOMETRY|SHADER|FUNCTION|COMPOSITOR|TEXTURE)_?)+', '', s)
            s = re.sub(r'_?(ITEMS|DATA|TYPE|MODE|OP|OPERATION)$', '', s)
        return s

    @staticmethod
    def clean_polymorphic(text):
        if not text: return ""
        val_str = str(text)
        camel_to_snake = re.sub(r'([a-z])([A-Z])', r'\1_\2', val_str)
        return camel_to_snake.upper().replace(" ", "_").replace("-", "_")

    @staticmethod
    def get_tokens(text):
        return set([t for t in text.split('_') if t])

    @staticmethod
    def match_strict(target, candidate):
        norm_target = TextSmartEngine.clean_polymorphic(target)
        norm_cand = TextSmartEngine.clean_polymorphic(candidate)
        if norm_target == norm_cand: return True
        target_tokens = TextSmartEngine.get_tokens(norm_target)
        cand_tokens = TextSmartEngine.get_tokens(norm_cand)
        if target_tokens and target_tokens == cand_tokens: return True
        return False

    @staticmethod
    def clean_for_loose(text):
        if not text: return ""
        s = TextSmartEngine.strip_blender_api_prefix(text)
        return re.sub(r'[\s_.]\d+$', '', str(s)).replace(" ", "").replace("_", "").lower()

    @staticmethod
    def match_loose(target, candidate):
        norm_target = TextSmartEngine.clean_for_loose(target)
        norm_cand = TextSmartEngine.clean_for_loose(candidate)
        if not norm_target or not norm_cand: return False
        if norm_target == norm_cand: return True
        if norm_target in norm_cand or norm_cand in norm_target: return True
        return False
        
    @staticmethod
    def match_subset(target, candidate):
        t_tokens = TextSmartEngine.get_tokens(TextSmartEngine.clean_polymorphic(target))
        c_tokens = TextSmartEngine.get_tokens(TextSmartEngine.clean_polymorphic(candidate))
        if not t_tokens or not c_tokens: return False
        return t_tokens.issubset(c_tokens) or c_tokens.issubset(t_tokens)


# ==============================================================================
# 1. 动态插槽反射器 (Type Safety via Reflection)
# ==============================================================================

class SocketTypeResolver:
    _SOCKET_CACHE = {}
    _CACHE_BUILT = False

    @classmethod
    def _build_cache(cls):
        if cls._CACHE_BUILT: return
        for type_name in dir(bpy.types):
            if type_name.startswith("NodeSocket") and "Interface" not in type_name:
                cls._SOCKET_CACHE[type_name.upper()] = type_name
        cls._CACHE_BUILT = True

    @classmethod
    def get_class_name(cls, enum_type):
        if not cls._CACHE_BUILT: cls._build_cache()
        enum_str = str(enum_type).strip().upper()
        
        # 1. Token 宽松匹配查找
        for bl_idname in cls._SOCKET_CACHE.values():
            if TextSmartEngine.match_loose(enum_str, bl_idname):
                return bl_idname
                
        # 2. 极端语义兜底
        fallback_map = {
            'VALUE': 'NodeSocketFloat', 'FLOAT': 'NodeSocketFloat',
            'FLOAT_VECTOR': 'NodeSocketVector', 'VECTOR': 'NodeSocketVector',
            'FLOAT_COLOR': 'NodeSocketColor', 'RGBA': 'NodeSocketColor', 'COLOR': 'NodeSocketColor',
            'BOOLEAN': 'NodeSocketBool', 'BOOL': 'NodeSocketBool',
            'INT': 'NodeSocketInt', 'GEOMETRY': 'NodeSocketGeometry',
            'QUATERNION': 'NodeSocketRotation', 'ROTATION': 'NodeSocketRotation'
        }
        return fallback_map.get(enum_str, 'NodeSocketFloat')

    @classmethod
    def get_api_enum(cls, class_name_or_type):
        """【歧义修正】精确返回 Blender 4.0 Zone/Capture 所需的特定短枚举"""
        raw = str(class_name_or_type).strip().upper()
        
        if "COLOR" in raw or "RGBA" in raw: return "FLOAT_COLOR"
        if "VECTOR" in raw: return "FLOAT_VECTOR"
        if "BOOL" in raw: return "BOOLEAN"
        if "INT" in raw: return "INT"
        if "ROT" in raw or "QUAT" in raw: return "ROTATION"
        if "STR" in raw: return "STRING"
        if "MAT" in raw: return "MATRIX"
        if "OBJ" in raw: return "OBJECT"
        if "COL" in raw: return "COLLECTION"
        if "IMG" in raw: return "IMAGE"
        if "GEO" in raw: return "GEOMETRY"
        
        core_str = TextSmartEngine.strip_blender_api_prefix(raw)
        return core_str if core_str else "FLOAT"


# ==============================================================================
# 2. 动态节点数据库与名称解析器 (Priority Architecture)
# ==============================================================================

class NodeNameMatcher:
    _CLASS_ID_CACHE = {}  
    _CACHE_BUILT = False

    @classmethod
    def _build_cache(cls):
        if cls._CACHE_BUILT: return
        for type_name in dir(bpy.types):
            if ("Node" in type_name or type_name.endswith("Node")) and not type_name.startswith("NodeSocket") and not type_name.startswith("NodeTree"):
                try:
                    cls_obj = getattr(bpy.types, type_name)
                    if hasattr(cls_obj, 'bl_idname'):
                        bid = cls_obj.bl_idname
                        cls._CLASS_ID_CACHE[bid] = bid
                except: pass
                
        # 预设骨干护城河，防止极少数情况下的类名加载异常
        cls._CLASS_ID_CACHE["ShaderNodeMath"] = "ShaderNodeMath"
        cls._CLASS_ID_CACHE["ShaderNodeVectorMath"] = "ShaderNodeVectorMath"
        cls._CLASS_ID_CACHE["ShaderNodeMix"] = "ShaderNodeMix"
        cls._CLASS_ID_CACHE["FunctionNodeBooleanMath"] = "FunctionNodeBooleanMath"
        cls._CLASS_ID_CACHE["NodeFrame"] = "NodeFrame"
        cls._CACHE_BUILT = True

    @classmethod
    def _prioritize(cls, matches):
        """【核心防御】解决 CompositorNode 截胡导致在 GeoNode 创建失败的致命问题"""
        # ShaderNode 优先级最高，因为 GeoNode 的核心 Math 实际上借用了 ShaderNode
        for prefix in ['ShaderNode', 'GeometryNode', 'FunctionNode']:
            for m in matches:
                if m.startswith(prefix): return m
        return matches[0]

    @classmethod
    def resolve_idname(cls, fuzzy_name):
        if not fuzzy_name: return "NodeFrame"
        if not cls._CACHE_BUILT: cls._build_cache()
        
        # 0. 极速通道 (最常见的 AI 别名直接放行，O(1) 效率)
        fast_path = {
            "MATH": "ShaderNodeMath", "VECTOR_MATH": "ShaderNodeVectorMath",
            "MIX": "ShaderNodeMix", "BOOLEAN_MATH": "FunctionNodeBooleanMath"
        }
        clean_name = TextSmartEngine.clean_polymorphic(fuzzy_name)
        if clean_name in fast_path: return fast_path[clean_name]
        
        # 1. 精确匹配
        if fuzzy_name in cls._CLASS_ID_CACHE:
            return cls._CLASS_ID_CACHE[fuzzy_name]
            
        # 2. 核心语义精确匹配 (无视前缀)
        norm_fuzzy = TextSmartEngine.strip_blender_api_prefix(fuzzy_name)
        matches_exact = [bid for bid in cls._CLASS_ID_CACHE.keys() if norm_fuzzy == TextSmartEngine.strip_blender_api_prefix(bid)]
        if matches_exact: return cls._prioritize(matches_exact)
        
        # 3. Token 子集匹配
        matches_sub = [bid for bid in cls._CLASS_ID_CACHE.keys() if TextSmartEngine.match_subset(fuzzy_name, bid)]
        if matches_sub: return cls._prioritize(matches_sub)
        
        # 4. 容错拼写纠正
        keys = list(cls._CLASS_ID_CACHE.keys())
        matches_diff = difflib.get_close_matches(fuzzy_name, keys, n=1, cutoff=0.6)
        if matches_diff: return cls._CLASS_ID_CACHE[matches_diff[0]]
            
        return fuzzy_name


# ==============================================================================
# 3. 模块级公开 API
# ==============================================================================

def get_socket_class_name(enum_type):
    return SocketTypeResolver.get_class_name(enum_type)

def get_api_enum(class_name_or_type):
    return SocketTypeResolver.get_api_enum(class_name_or_type)

def resolve_node_idname(fuzzy_name):
    return NodeNameMatcher.resolve_idname(fuzzy_name)

def load_db():
    SocketTypeResolver._build_cache()
    NodeNameMatcher._build_cache()
    return True