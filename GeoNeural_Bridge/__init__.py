# __init__.py
# GeoNeural Bridge v5.14.1 - Precision Update
# 更新内容: 
# 1. Serializer: 智能剔除 unavailable 插槽，解决 AI 上下文冗余问题
# 2. Deserializer: 强制优先 Identifier 匹配，解决同名插槽数值错配问题
# 基础: v5.14.0 (AI-Native Milestone)

bl_info = {
    "name": "GeoNeural Bridge (v5.14.1 Precision)",
    "author": "Dev_Nodes_V5 & Dev_Analyst",
    "version": (5, 14, 1),
    "blender": (4, 0, 0),
    "location": "Node Editor > Sidebar > GeoNeural",
    "description": "热修复：剔除冗余插槽数据，修复同名插槽数值注入错误。",
    "category": "Node",
}

import bpy
import importlib
from .core import node_mappings

# 导入子模块
from .operators import clipboard

modules_to_reload = [
    node_mappings,
    clipboard,
]

for m in modules_to_reload:
    importlib.reload(m)

# ==============================================================================
# 1. UI 面板
# ==============================================================================

class GN_PT_MainPanel(bpy.types.Panel):
    """GeoNeural Bridge 主面板"""
    bl_label = "GeoNeural Bridge"
    bl_idname = "GN_PT_main"
    bl_space_type = "NODE_EDITOR"
    bl_region_type = "UI"
    bl_category = "GeoNeural"

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        try: 
            db_ok = node_mappings.load_db()
            if db_ok:
                layout.label(text="AI 核心已就绪", icon='CHECKMARK')
            else:
                layout.label(text="映射库未加载", icon='INFO')
        except: 
            layout.label(text="系统异常", icon='ERROR')

        layout.separator()

        box = layout.box()
        box.label(text="发送给 AI (复制):")
        
        row = box.row()
        row.prop(scene, "gn_compact_mode", text="精简模式 (AI)")
        
        r = box.row()
        r.operator("geonb.copy_nodes", text="复制选中节点", icon='COPYDOWN')

        layout.separator()

        col2 = layout.column(align=True)
        col2.scale_y = 1.4
        col2.operator("geonb.paste_nodes", text="智能粘贴 (Paste)", icon='PASTEDOWN')
        
        layout.separator()
        row = layout.row()
        row.prop(scene, "gn_debug_mode", text="调试日志")

# ==============================================================================
# 2. 注册逻辑
# ==============================================================================

def register():
    bpy.types.Scene.gn_debug_mode = bpy.props.BoolProperty(default=False)
    bpy.types.Scene.gn_compact_mode = bpy.props.BoolProperty(
        name="Compact Mode",
        description="去除 UI 数据以节省 Token，适合发送给 AI",
        default=True
    )

    clipboard.register()
    bpy.utils.register_class(GN_PT_MainPanel)
    
    if hasattr(node_mappings, 'load_db'):
        node_mappings.load_db()

def unregister():
    if hasattr(node_mappings, 'unload_db'): 
        pass
        
    bpy.utils.unregister_class(GN_PT_MainPanel)
    clipboard.unregister()
    
    del bpy.types.Scene.gn_compact_mode
    del bpy.types.Scene.gn_debug_mode

if __name__ == "__main__":
    register()