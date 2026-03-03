# core/node_mappings.py
# GeoNeural Bridge v5.14.140 (Omega Armor - Core Node Injection)
# 修复: 引入递归子类扫描 _get_all_subclasses，彻底解决 dir(bpy.types) 带来的类名漏算问题。
# 终极架构: 废弃外部补丁，将“命名空间幻觉救援 (Namespace Rescue)”原生融入智能匹配引擎。
# 核心修复: 针对 Blender C++ 底层节点 (如 NodeGroupInput) 不暴露类级 bl_idname 的暗坑，引入【核心节点硬注入】与快速通道映射，彻底解决组输入/输出节点的复制粘贴崩溃。

import bpy
import difflib
import re

# ==============================================================================
# 0. 底层工具：递归反射引擎 (Deep Reflection Engine)
# ==============================================================================

def _get_all_subclasses(cls):
    """递归获取所有深层子类，无死角扫描 Blender 内存，替代不可靠的 dir()"""
    all_sub = set()
    stack = [cls]
    while stack:
        current = stack.pop()
        for sub in current.__subclasses__():
            if sub not in all_sub:
                all_sub.add(sub)
                stack.append(sub)
    return all_sub


# ==============================================================================
# 1. 全局智能文本引擎 (The Brain)
# ==============================================================================

class TextSmartEngine:
    @staticmethod
    def strip_blender_api_prefix(text):
        """动态剥离 Blender 常见的底层 API 前缀/后缀，提取核心语义"""
        s = str(text).upper()
        prev = ""
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
# 2. 动态插槽反射器 (Type Safety via Deep Reflection)
# ==============================================================================

class SocketTypeResolver:
    _SOCKET_CACHE = {}
    _CACHE_BUILT = False

    @classmethod
    def _build_cache(cls):
        if cls._CACHE_BUILT: return
        for socket_cls in _get_all_subclasses(bpy.types.NodeSocket):
            if hasattr(socket_cls, "bl_idname") and socket_cls.bl_idname:
                cls._SOCKET_CACHE[socket_cls.bl_idname.upper()] = socket_cls.bl_idname
        cls._CACHE_BUILT = True

    @classmethod
    def get_class_name(cls, enum_type):
        if not cls._CACHE_BUILT: cls._build_cache()
        enum_str = str(enum_type).strip().upper()
        
        for bl_idname in cls._SOCKET_CACHE.values():
            if TextSmartEngine.match_loose(enum_str, bl_idname):
                return bl_idname
                
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
# 3. 动态节点数据库与名称解析器 (Semantic Candidates Engine)
# ==============================================================================

class NodeNameMatcher:
    _CLASS_ID_CACHE = {}  
    _CACHE_BUILT = False

    @classmethod
    def _build_cache(cls):
        if cls._CACHE_BUILT: return
        for node_cls in _get_all_subclasses(bpy.types.Node):
            if hasattr(node_cls, "bl_idname") and node_cls.bl_idname:
                cls._CLASS_ID_CACHE[node_cls.bl_idname] = node_cls.bl_idname
                
        # 【核心漏洞修复】强制注入 Blender C++ 底层静默节点
        # 这些节点在类定义上没有暴露 bl_idname，导致反射机制漏抓。
        core_nodes = ["NodeGroupInput", "NodeGroupOutput", "NodeFrame", "NodeReroute", "NodeCustomGroup"]
        for cn in core_nodes:
            cls._CLASS_ID_CACHE[cn] = cn
            
        cls._CACHE_BUILT = True

    @classmethod
    def resolve_idname_candidates(cls, fuzzy_name):
        """
        【Omega 核心】返回所有可能的节点合法 ID 候选队列。
        从最精确的语义匹配到最极端的盲猜前缀拼接，确保执行器绝对有足够的备选子弹。
        """
        if not fuzzy_name: return ["NodeFrame"]
        if not cls._CACHE_BUILT: cls._build_cache()
        
        candidates = []
        
        # 0. 极速通道 (常见别名与高频核心节点)
        fast_path = {
            "MATH": "ShaderNodeMath", "VECTOR_MATH": "ShaderNodeVectorMath",
            "MIX": "ShaderNodeMix", "BOOLEAN_MATH": "FunctionNodeBooleanMath",
            "COMPARE": "FunctionNodeCompare",
            "GROUP_INPUT": "NodeGroupInput", "GROUP_OUTPUT": "NodeGroupOutput",
            "REROUTE": "NodeReroute"
        }
        clean_name = TextSmartEngine.clean_polymorphic(fuzzy_name)
        if clean_name in fast_path:
            candidates.append(fast_path[clean_name])
            
        # 1. 严格精确匹配
        if fuzzy_name in cls._CLASS_ID_CACHE and fuzzy_name not in candidates:
            candidates.append(fuzzy_name)
            
        norm_fuzzy = TextSmartEngine.strip_blender_api_prefix(fuzzy_name)
        prefixes = ['ShaderNode', 'GeometryNode', 'FunctionNode', 'TextureNode', 'CompositorNode']
        
        # 2. 核心语义精确匹配 (跨域前缀扩展)
        matches_exact = [bid for bid in cls._CLASS_ID_CACHE.keys() if norm_fuzzy == TextSmartEngine.strip_blender_api_prefix(bid)]
        for p in prefixes:
            for m in matches_exact:
                if m.startswith(p) and m not in candidates: candidates.append(m)
        for m in matches_exact:
            if m not in candidates: candidates.append(m)
            
        # 3. Token 子集包含匹配
        matches_sub = [bid for bid in cls._CLASS_ID_CACHE.keys() if TextSmartEngine.match_subset(fuzzy_name, bid)]
        for p in prefixes:
            for m in matches_sub:
                if m.startswith(p) and m not in candidates: candidates.append(m)
        for m in matches_sub:
            if m not in candidates: candidates.append(m)
            
        # 4. Difflib 纠错匹配
        core_dict = {}
        for bid in cls._CLASS_ID_CACHE.keys():
            stripped = TextSmartEngine.strip_blender_api_prefix(bid)
            if stripped not in core_dict:
                core_dict[stripped] = []
            core_dict[stripped].append(bid)
            
        matches_diff = difflib.get_close_matches(norm_fuzzy, list(core_dict.keys()), n=2, cutoff=0.70)
        for diff_val in matches_diff:
            bids = core_dict[diff_val]
            for p in prefixes:
                for m in bids:
                    if m.startswith(p) and m not in candidates: candidates.append(m)
            for m in bids:
                if m not in candidates: candidates.append(m)
                
        # 5. 终极盲区救援 (应对未在缓存中显现的未来版本 API)
        core_name_raw = re.sub(r'^(ShaderNode|GeometryNode|FunctionNode|TextureNode|CompositorNode|Node)', '', fuzzy_name, flags=re.IGNORECASE)
        for p in prefixes:
            blind = p + core_name_raw
            if blind not in candidates: candidates.append(blind)
            
        if fuzzy_name not in candidates:
            candidates.append(fuzzy_name)
            
        return candidates


# ==============================================================================
# 4. 模块级公开 API
# ==============================================================================

def get_socket_class_name(enum_type):
    return SocketTypeResolver.get_class_name(enum_type)

def get_api_enum(class_name_or_type):
    return SocketTypeResolver.get_api_enum(class_name_or_type)

def resolve_node_idname_candidates(fuzzy_name):
    """返回最优备选队列 (List)"""
    return NodeNameMatcher.resolve_idname_candidates(fuzzy_name)

def resolve_node_idname(fuzzy_name):
    """向下兼容旧版接口，仅返回置信度最高的一个"""
    cands = NodeNameMatcher.resolve_idname_candidates(fuzzy_name)
    return cands[0] if cands else "NodeFrame"

def load_db():
    SocketTypeResolver._build_cache()
    NodeNameMatcher._build_cache()
    return True