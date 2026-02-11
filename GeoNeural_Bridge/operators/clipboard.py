# operators/clipboard.py
# GeoNeural Bridge v5.14.3
# 修复: 增加智能解包功能 (Unwrap)，解决被 "root" 或 "data" 等键包裹的嵌套 JSON 无法读取的问题
# 基础: v5.14.0 (AI-Native Milestone) / v5.13.39 (RobustLoader)

import bpy
import sys
import json
import re
import logging
import traceback
from bpy.types import Operator
from ..core.serializer import SerializationEngine
from ..core.deserializer import DeserializationEngine
try:
    from ..core import node_mappings
except ImportError:
    node_mappings = None

logger = logging.getLogger("GeoNeuralBridge.clipboard")

# ==============================================================================
# 0. 日志配置
# ==============================================================================

def configure_logging(context):
    try:
        debug_mode = getattr(context.scene, "gn_debug_mode", False)
        target_level = logging.DEBUG if debug_mode else logging.INFO
        logger.setLevel(target_level)
        logging.getLogger("GeoNeuralBridge.serializer").setLevel(target_level)
        logging.getLogger("GeoNeuralBridge.deserializer").setLevel(target_level)
        logging.getLogger("GeoNeuralBridge.clipboard").setLevel(target_level)
        
        if not logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(logging.Formatter('[GN-Bridge] %(levelname)s: %(message)s'))
            logger.addHandler(handler)
        else:
            for h in logger.handlers: h.setLevel(target_level)
    except: pass

# ==============================================================================
# 1. 强力数据加载器 (Robust Loader)
# ==============================================================================

class RobustLoader:
    @staticmethod
    def load_json(text):
        """
        [Core] 处理 Markdown、C风格注释、尾部逗号等非标准 JSON 格式
        """
        if not text: return None
        
        # 1. 去除 Markdown 包裹
        if "```" in text:
            pattern = r"```json(.*?)```|```(.*?)```"
            match = re.search(pattern, text, re.DOTALL)
            if match: 
                text = match.group(1) if match.group(1) else match.group(2)
        
        # 2. 去除注释 (同时保留 URL 中的 //)
        pattern = r'("[^"\\]*(?:\\.[^"\\]*)*")|(\/\/.*|\/\*[\s\S]*?\*\/)'
        text = re.sub(pattern, lambda m: m.group(1) if m.group(1) else "", text)
        
        # 3. 修复尾部逗号
        text = re.sub(r',(\s*[}\]])', r'\1', text)
        
        try: 
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.debug(f"JSON Parse Error: {e}")
            return None

# ==============================================================================
# 2. 数据清洗器 (AI 适配层)
# ==============================================================================

class DataSanitizer:
    @staticmethod
    def _guess_socket_type(value):
        if isinstance(value, bool): return "NodeSocketBool"
        if isinstance(value, int): return "NodeSocketInt"
        if isinstance(value, float): return "NodeSocketFloat"
        if isinstance(value, (list, tuple)):
            if len(value) == 3: return "NodeSocketVector"
            if len(value) == 4: return "NodeSocketColor"
        if isinstance(value, str): return "NodeSocketString"
        return "NodeSocketFloat"

    @staticmethod
    def _unwrap_payload(data):
        """
        [v5.14.3 新增] 智能解包：递归查找核心数据负载
        解决 {"root": {...}} 或 {"data": {...}} 导致的结构不匹配问题
        """
        # 如果当前层级就是核心数据，直接返回
        if 'nodes' in data or 'tree_type' in data:
            return data
        
        # 尝试遍历第一层子项，寻找包含节点数据的字典
        # 这可以处理 {"root": ...}, {"json": ...}, {"result": ...} 等各种包裹
        for key, val in data.items():
            if isinstance(val, dict):
                if 'nodes' in val or 'tree_type' in val:
                    logger.info(f"Unwrapped nested JSON from key: '{key}'")
                    return val
        
        # 如果没找到，原样返回，交由后续逻辑处理（可能会失败）
        return data

    @staticmethod
    def sanitize(data):
        if not isinstance(data, dict): return data
        
        # [Step 0] 智能解包 (Handle Nested Structures)
        data = DataSanitizer._unwrap_payload(data)

        if node_mappings: node_mappings.load_db()

        # [Step 1] 标准化节点
        nodes = data.get('nodes', [])
        sanitized_nodes = []
        for n in nodes:
            # 类型映射
            raw_type = n.get('bl_idname') or n.get('type')
            if raw_type and node_mappings:
                n['bl_idname'] = node_mappings.resolve_node_idname(raw_type)
            else:
                n['bl_idname'] = raw_type

            # 属性映射
            if 'properties' not in n and 'params' in n:
                n['properties'] = n['params']
            
            # 输入映射 (Dict -> List + 类型推断)
            if 'inputs' in n and isinstance(n['inputs'], dict):
                new_inputs = []
                for name, val in n['inputs'].items():
                    guessed_type = DataSanitizer._guess_socket_type(val)
                    new_inputs.append({
                        "name": name, "identifier": name, "default_value": val,
                        "bl_socket_idname": guessed_type
                    })
                n['inputs'] = new_inputs
                
            sanitized_nodes.append(n)
        data['nodes'] = sanitized_nodes

        # [Step 2] 标准化连接
        links = data.get('links', [])
        sanitized_links = []
        for l in links:
            new_link = l.copy()
            if 'src' in l: new_link['from_node'] = l['src']
            if 'src_sock' in l: new_link['from_socket'] = l['src_sock']
            if 'dst' in l: new_link['to_node'] = l['dst']
            if 'dst_sock' in l: new_link['to_socket'] = l['dst_sock']
            sanitized_links.append(new_link)
        data['links'] = sanitized_links
        
        return data

# ==============================================================================
# 3. 剪贴板管理器
# ==============================================================================

class ClipboardManager:
    _internal_storage = {}

    @staticmethod
    def set(data, context):
        ClipboardManager._internal_storage = data
        try:
            json_str = json.dumps(data, indent=2, ensure_ascii=False)
            context.window_manager.clipboard = json_str
        except: pass

    @staticmethod
    def get(context):
        # 1. 优先解析系统剪贴板
        try:
            sys_clip = context.window_manager.clipboard
            if sys_clip:
                # 使用强力加载器解析文本
                raw_data = RobustLoader.load_json(sys_clip)
                
                if isinstance(raw_data, dict):
                    # [v5.14.3 修改] 先清洗/解包，再验证
                    # 这样可以让 {"root": ...} 这样的数据在验证前被解包成标准格式
                    sanitized_data = DataSanitizer.sanitize(raw_data)
                    
                    if sanitized_data and ('nodes' in sanitized_data or 'tree_type' in sanitized_data):
                        logger.info("Detected AI JSON (Sanitized & Unwrapped) -> Using System Clipboard")
                        return sanitized_data
        except Exception as e:
            logger.debug(f"Clipboard processing error: {e}")

        # 2. 回退到内部存储
        if ClipboardManager._internal_storage:
            logger.info("Using Internal Memory")
            return ClipboardManager._internal_storage
        return None

# ==============================================================================
# 4. 操作符定义
# ==============================================================================

class GEONB_OT_CopyNodes(Operator):
    bl_idname = "geonb.copy_nodes"
    bl_label = "Copy Nodes"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return context.space_data and context.space_data.type == 'NODE_EDITOR' and context.space_data.edit_tree

    def execute(self, context):
        configure_logging(context)
        tree = context.space_data.edit_tree
        is_compact = getattr(context.scene, "gn_compact_mode", False)
        try:
            engine = SerializationEngine(tree, context, selected_only=True, compact=is_compact)
            data = engine.execute()
            if not data['nodes']:
                self.report({'WARNING'}, "No nodes selected"); return {'CANCELLED'}
            ClipboardManager.set(data, context)
            self.report({'INFO'}, f"Copied {len(data['nodes'])} nodes")
            return {'FINISHED'}
        except Exception as e:
            logger.error(f"Copy Failed: {e}"); return {'CANCELLED'}

class GEONB_OT_PasteNodes(Operator):
    bl_idname = "geonb.paste_nodes"
    bl_label = "Paste Nodes"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.space_data and context.space_data.type == 'NODE_EDITOR'

    def execute(self, context):
        configure_logging(context)
        tree = context.space_data.edit_tree
        try:
            data = ClipboardManager.get(context)
            if not data or not data.get('nodes'):
                self.report({'WARNING'}, "Clipboard empty or invalid format"); return {'CANCELLED'}

            bpy.ops.node.select_all(action='DESELECT')
            offset = self._calculate_smart_offset(context, data['nodes'])
            
            engine = DeserializationEngine(tree, context)
            created_nodes = engine.deserialize_tree(data, offset=offset)

            self.report({'INFO'}, f"Pasted {len(created_nodes)} nodes")
            return {'FINISHED'}
        except Exception as e:
            logger.error(f"Paste Failed: {e}"); self.report({'ERROR'}, str(e)); return {'CANCELLED'}

    def _calculate_smart_offset(self, context, nodes_data):
        locs = [n.get('location', [0, 0]) for n in nodes_data]
        if not locs: return (0,0)
        min_x = min(l[0] for l in locs); max_x = max(l[0] for l in locs)
        min_y = min(l[1] for l in locs); max_y = max(l[1] for l in locs)
        src_center_x = (min_x + max_x) / 2; src_center_y = (min_y + max_y) / 2
        try:
            if context.space_data.type == 'NODE_EDITOR':
                cx, cy = context.region.view2d.region_to_view(context.region.width / 2, context.region.height / 2)
                return (cx - src_center_x, cy - src_center_y)
        except: pass
        return (20, -20)

classes = (GEONB_OT_CopyNodes, GEONB_OT_PasteNodes)
def register():
    for c in classes: bpy.utils.register_class(c)
def unregister():
    for c in reversed(classes): bpy.utils.unregister_class(c)