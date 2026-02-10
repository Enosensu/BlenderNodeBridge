# operators/clipboard.py
# GeoNeural Bridge v5.13.30 - Clipboard Operator
# 修复: 日志系统未响应调试开关的问题
# 增强: 增加控制台日志格式化，输出详细追踪信息

import bpy
import sys
import json
import logging
import traceback
from bpy.types import Operator
from ..core.serializer import SerializationEngine
from ..core.deserializer import DeserializationEngine

# 获取父级 Logger
logger = logging.getLogger("GeoNeuralBridge")

# ==============================================================================
# 0. 日志配置辅助函数 (Log Configuration)
# ==============================================================================

def configure_logging(context):
    """
    根据场景属性动态配置日志级别和格式。
    在每次操作执行前调用，确保开关即时生效。
    """
    try:
        # 读取开关状态
        debug_mode = getattr(context.scene, "gn_debug_mode", False)
        target_level = logging.DEBUG if debug_mode else logging.INFO
        
        # 设置总记录器级别
        logger.setLevel(target_level)
        
        # 确保它的子记录器 (serializer/deserializer) 也继承该级别
        logging.getLogger("GeoNeuralBridge.serializer").setLevel(target_level)
        logging.getLogger("GeoNeuralBridge.deserializer").setLevel(target_level)
        logging.getLogger("GeoNeuralBridge.clipboard").setLevel(target_level)

        # 配置输出处理程序 (Handler)
        # 防止重复添加 Handler 导致日志重复打印
        if not logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            # 格式: [时间] [级别] [模块] 信息
            formatter = logging.Formatter('[GN-Bridge] %(levelname)s: %(message)s')
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        else:
            # 如果已有 Handler，确保级别同步
            for h in logger.handlers:
                h.setLevel(target_level)
        
        if debug_mode:
            logger.debug("Debug mode enabled. Verbose logging active.")
            
    except Exception as e:
        print(f"[GN-Bridge] Logging setup failed: {e}")

# ==============================================================================
# 1. 剪贴板管理器
# ==============================================================================

class ClipboardManager:
    _internal_storage = {}

    @staticmethod
    def set(data, context):
        ClipboardManager._internal_storage = data
        try:
            json_str = json.dumps(data, indent=2, ensure_ascii=False)
            context.window_manager.clipboard = json_str
            logger.debug(f"Synced to system clipboard ({len(json_str)} chars)")
        except Exception as e:
            logger.warning(f"System clipboard sync failed: {e}")

    @staticmethod
    def get(context):
        # 1. 优先内存
        mem_data = ClipboardManager._internal_storage
        if mem_data and mem_data.get('nodes'):
            logger.debug("Loaded data from Internal Memory")
            return mem_data
        
        # 2. 其次系统剪贴板
        try:
            sys_clip = context.window_manager.clipboard
            if sys_clip and sys_clip.strip().startswith('{'):
                data = json.loads(sys_clip)
                if isinstance(data, dict) and 'nodes' in data:
                    ClipboardManager._internal_storage = data
                    logger.debug("Loaded data from System Clipboard")
                    return data
        except json.JSONDecodeError:
            pass
        except Exception as e:
            logger.debug(f"Clipboard read exception: {e}")
            
        return None

# ==============================================================================
# 2. 复制操作符
# ==============================================================================

class GEONB_OT_CopyNodes(Operator):
    bl_idname = "geonb.copy_nodes"
    bl_label = "Copy Nodes"
    bl_description = "Serialize selected nodes to JSON"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        space = context.space_data
        return space and space.type == 'NODE_EDITOR' and space.edit_tree

    def execute(self, context):
        # [Fix] 初始化日志系统
        configure_logging(context)
        
        tree = context.space_data.edit_tree
        is_compact = getattr(context.scene, "gn_compact_mode", False)
        
        logger.info(f"Start Copy: Compact={is_compact}")

        try:
            engine = SerializationEngine(tree, context, selected_only=True, compact=is_compact)
            data = engine.execute()
            
            if not data['nodes']:
                self.report({'WARNING'}, "No nodes selected")
                return {'CANCELLED'}

            ClipboardManager.set(data, context)
            
            count = len(data['nodes'])
            mode_text = " (Compact)" if is_compact else ""
            self.report({'INFO'}, f"Copied {count} nodes{mode_text}")
            return {'FINISHED'}
            
        except Exception as e:
            # 捕获并打印完整堆栈，方便调试
            logger.error(f"Copy Operation Failed: {e}")
            if getattr(context.scene, "gn_debug_mode", False):
                traceback.print_exc()
            self.report({'ERROR'}, f"Copy Failed: {str(e)}")
            return {'CANCELLED'}

# ==============================================================================
# 3. 粘贴操作符
# ==============================================================================

class GEONB_OT_PasteNodes(Operator):
    bl_idname = "geonb.paste_nodes"
    bl_label = "Paste Nodes"
    bl_description = "Paste nodes from clipboard"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.space_data and context.space_data.type == 'NODE_EDITOR'

    def execute(self, context):
        # [Fix] 初始化日志系统
        configure_logging(context)
        
        tree = context.space_data.edit_tree
        
        try:
            data = ClipboardManager.get(context)
            if not data or not data.get('nodes'):
                self.report({'WARNING'}, "Clipboard empty")
                return {'CANCELLED'}

            logger.info(f"Start Paste: {len(data['nodes'])} nodes from version {data.get('version', 'unknown')}")

            # 粘贴前取消选中
            bpy.ops.node.select_all(action='DESELECT')

            offset = self._calculate_smart_offset(context, data['nodes'])
            logger.debug(f"Calculated paste offset: {offset}")
            
            engine = DeserializationEngine(tree, context)
            created_nodes = engine.deserialize_tree(data, offset=offset)

            self.report({'INFO'}, f"Pasted {len(created_nodes)} nodes")
            return {'FINISHED'}
            
        except Exception as e:
            logger.error(f"Paste Operation Failed: {e}")
            if getattr(context.scene, "gn_debug_mode", False):
                traceback.print_exc()
            self.report({'ERROR'}, f"Paste Failed: {str(e)}")
            return {'CANCELLED'}

    def _calculate_smart_offset(self, context, nodes_data):
        if not nodes_data: return (0, 0)
        
        # 提取坐标（Compact模式下可能没有）
        locs = [n.get('location', [0, 0]) for n in nodes_data]
        if not locs: 
            return (0,0)
        
        min_x = min(l[0] for l in locs)
        max_x = max(l[0] for l in locs)
        min_y = min(l[1] for l in locs)
        max_y = max(l[1] for l in locs)
        
        src_center_x = (min_x + max_x) / 2
        src_center_y = (min_y + max_y) / 2

        try:
            region = context.region
            # 确保我们在节点编辑器区域内
            if context.space_data.type == 'NODE_EDITOR':
                # region_to_view: 将屏幕像素坐标转换为节点图表坐标
                center_x, center_y = context.region.view2d.region_to_view(
                    region.width / 2, region.height / 2
                )
                return (center_x - src_center_x, center_y - src_center_y)
        except Exception as e:
            logger.debug(f"Smart offset calculation failed (using default): {e}")
        
        return (20, -20)

# ==============================================================================
# 4. 注册
# ==============================================================================

classes = (GEONB_OT_CopyNodes, GEONB_OT_PasteNodes)

def register():
    for cls in classes: bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes): bpy.utils.unregister_class(cls)