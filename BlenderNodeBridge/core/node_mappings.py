# core/node_mappings.py
# BlenderNodeBridge v5.14.151 (Omega Armor - Adaptive Variant Generator)
# 机制重置: 回滚至 v5.14.141 的纯净活体探测架构，摒弃侵入式的懒加载唤醒与硬编码字典。
# 文本修复: 修复 strip_blender_api_prefix 中导致驼峰边界丢失的 Bug。
# 终极架构: [Adaptive Variant Generator] 引入“经验变体生成器”。针对 AI 的命名幻觉与 Blender API 的跨版本分裂，不再依赖字典匹配，而是基于领域经验（噪音词）生成命名变体组合，交由反序列化器的 `nodes.new()` 进行物理验证。实现无视懒加载、无视版本差异的终极兼容。

import bpy
import difflib
import re

# ==============================================================================
# 0. 底层工具：递归反射引擎 (Deep Reflection Engine)
# ==============================================================================

def _get_all_subclasses(cls):
    """递归获取所有深层子类，扫描已加载进内存的 Blender 节点类"""
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
    def clean_polymorphic(text):
        """提取词边界，统一转化为 UPPER_SNAKE_CASE，绝不破坏信息熵"""
        if not text: return ""
        val_str = str(text)
        # 正确解析驼峰命名 (e.g. CurveStar -> CURVE_STAR)
        camel_to_snake = re.sub(r'([a-z])([A-Z])', r'\1_\2', val_str)
        return camel_to_snake.upper().replace(" ", "_").replace("-", "_")

    @staticmethod
    def strip_blender_api_prefix(text):
        """基于标准化后的字符串，安全剥离无用的 API 前后缀"""
        s = TextSmartEngine.clean_polymorphic(text)
        prev = ""
        while s != prev:
            prev = s
            s = re.sub(r'^((NODE|SOCKET|GEOMETRY|SHADER|FUNCTION|COMPOSITOR|TEXTURE)_?)+', '', s)
            s = re.sub(r'_?(ITEMS|DATA|TYPE|MODE|OP|OPERATION)$', '', s)
        return s if s else TextSmartEngine.clean_polymorphic(text)

    @staticmethod
    def get_tokens(text):
        """利用下划线切分，获取核心语义 Token 集合"""
        cleaned = TextSmartEngine.strip_blender_api_prefix(text)
        return set([t for t in cleaned.split('_') if t])

    @staticmethod
    def match_strict(target, candidate):
        norm_target = TextSmartEngine.clean_polymorphic(target)
        norm_cand = TextSmartEngine.clean_polymorphic(candidate)
        if norm_target == norm_cand: return True
        target_tokens = TextSmartEngine.get_tokens(target)
        cand_tokens = TextSmartEngine.get_tokens(candidate)
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
        t_tokens = TextSmartEngine.get_tokens(target)
        c_tokens = TextSmartEngine.get_tokens(candidate)
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
                
        # 强制注入 Blender C++ 底层静默节点
        core_nodes = ["NodeGroupInput", "NodeGroupOutput", "NodeFrame", "NodeReroute", "NodeCustomGroup"]
        for cn in core_nodes:
            cls._CLASS_ID_CACHE[cn] = cn
            
        cls._CACHE_BUILT = True

    @classmethod
    def resolve_idname_candidates(cls, fuzzy_name):
        """
        【Omega 终极架构】返回高优先级候选队列，交由 deserializer 的 `nodes.new()` 物理验证。
        权重顺序：极速通道 -> 精确实体匹配 -> Difflib纠错 -> 【经验变体生成 (盲区救援)】
        """
        if not fuzzy_name: return ["NodeFrame"]
        if not cls._CACHE_BUILT: cls._build_cache()
        
        candidates = []
        
        # 1. 极速通道 (常见别名与高频核心节点)
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
            
        # 2. 严格精确匹配 (内存字典中已存在的)
        if fuzzy_name in cls._CLASS_ID_CACHE and fuzzy_name not in candidates:
            candidates.append(fuzzy_name)
            
        norm_fuzzy = TextSmartEngine.strip_blender_api_prefix(fuzzy_name)
        
        # 3. 核心语义精确匹配
        matches_exact = [bid for bid in cls._CLASS_ID_CACHE.keys() if norm_fuzzy == TextSmartEngine.strip_blender_api_prefix(bid)]
        for m in matches_exact:
            if m not in candidates: candidates.append(m)
            
        # 4. Difflib 拼写纠错 (针对已缓存的节点)
        core_dict = {}
        for bid in cls._CLASS_ID_CACHE.keys():
            stripped = TextSmartEngine.strip_blender_api_prefix(bid)
            if stripped not in core_dict:
                core_dict[stripped] = []
            core_dict[stripped].append(bid)
            
        matches_diff = difflib.get_close_matches(norm_fuzzy, list(core_dict.keys()), n=3, cutoff=0.65)
        for diff_val in matches_diff:
            bids = core_dict[diff_val]
            for m in bids:
                if m not in candidates: candidates.append(m)
                
        # 5. Token 子集包含匹配
        matches_sub = [bid for bid in cls._CLASS_ID_CACHE.keys() if TextSmartEngine.match_subset(fuzzy_name, bid)]
        for m in matches_sub:
            if m not in candidates: candidates.append(m)
            
        # =========================================================================
        # 6. 【终极盲区救援：经验变体生成器 (Adaptive Variant Generator)】
        # 当上述字典匹配全部失效（因为节点懒加载，或 API 命名不一致）时启动。
        # 抛弃查字典，基于行业经验生成可能的名称变体组合，交由 Blender 底层 API 判决。
        # =========================================================================
        
        prefixes = ['GeometryNode', 'ShaderNode', 'FunctionNode', 'TextureNode', 'CompositorNode']
        
        # 提取最纯粹的核心词 (例如 GeometryNodeCurvePrimitiveStar -> CurvePrimitiveStar)
        core_name_raw = re.sub(r'^(ShaderNode|GeometryNode|FunctionNode|TextureNode|CompositorNode|Node)', '', fuzzy_name, flags=re.IGNORECASE)
        
        # 建立领域经验噪音词库 (Blender 历代版本中经常被添加或删除的冗余词)
        noise_words = ['Primitive', 'Legacy', 'Simple', 'Advanced', 'Base', 'Core', 'Math']
        
        # 生成变体维度矩阵
        variants = [core_name_raw]  # 变体1: 原汁原味 (可能 AI 就是对的，比如 CurvePrimitiveCircle)
        
        for noise in noise_words:
            # 变体2: 剔除噪音词 (例如 CurvePrimitiveStar -> CurveStar)
            # 使用正则忽略大小写，确保不破坏其他大小写结构
            stripped = re.sub(noise, '', core_name_raw, flags=re.IGNORECASE)
            if stripped != core_name_raw and stripped not in variants:
                variants.append(stripped)
                
        # 矩阵相乘：变体库 x 前缀库
        # 将生成的数十种可能性全部压入候选队列。deserializer 会依次执行 tree.nodes.new()
        # 只要有一条能被 Blender 物理创建成功，就会瞬间完成复原！
        for v in variants:
            for p in prefixes:
                blind_guess = p + v
                if blind_guess not in candidates: 
                    candidates.append(blind_guess)
            
        # 兜底：AI 的原词
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
    """返回最优备选队列 (List)，包含变体组合"""
    return NodeNameMatcher.resolve_idname_candidates(fuzzy_name)

def resolve_node_idname(fuzzy_name):
    """向下兼容旧版接口，仅返回置信度最高的一个"""
    cands = NodeNameMatcher.resolve_idname_candidates(fuzzy_name)
    return cands[0] if cands else "NodeFrame"

def load_db():
    SocketTypeResolver._build_cache()
    NodeNameMatcher._build_cache()
    return True