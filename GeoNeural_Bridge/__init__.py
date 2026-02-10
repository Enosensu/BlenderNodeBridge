# __init__.py
# GeoNeural Bridge v5.13.30 - UX Restoration
# 恢复 AI 精简模式开关与极简 UI 布局

bl_info = {
    "name": "GeoNeural Bridge (v5.13.30 Strict+UX)",
    "author": "Dev_Nodes_V5 & Dev_Analyst",
    "version": (5, 13, 30),
    "blender": (4, 0, 0),
    "location": "Node Editor > Sidebar > GeoNeural",
    "description": "模块化版本：含AI精简模式，Zone自动配对修复。",
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
# 1. UI 面板 (极简设计)
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
        
        # --- 状态指示 ---
        if node_mappings:
            layout.label(text="核心库: 正常", icon='CHECKMARK')
        else:
            layout.label(text="核心库: 丢失", icon='ERROR')

        layout.separator()

        # --- 发送区 (Copy) ---
        # 恢复 AI 精简模式开关
        layout.prop(scene, "gn_compact_mode", text="AI 精简模式 (省Token)")
        
        col = layout.column(align=True)
        col.scale_y = 1.4
        # 只保留 "复制选中"
        col.operator("geonb.copy_nodes", text="复制选中节点 (Copy)", icon='COPYDOWN')
        
        layout.separator()

        # --- 接收区 (Paste) ---
        col2 = layout.column(align=True)
        col2.scale_y = 1.4
        # 只保留 "插入粘贴" (Append)
        col2.operator("geonb.paste_nodes", text="插入粘贴 (Paste)", icon='PASTEDOWN')
        
        # 调试选项折叠
        layout.separator()
        row = layout.row()
        row.prop(scene, "gn_debug_mode", text="调试日志")

# ==============================================================================
# 2. 注册逻辑
# ==============================================================================

def register():
    # 1. 注册属性
    bpy.types.Scene.gn_debug_mode = bpy.props.BoolProperty(default=False)
    # [恢复] 精简模式开关
    bpy.types.Scene.gn_compact_mode = bpy.props.BoolProperty(
        name="Compact Mode",
        description="Strip UI data to save Tokens for AI context",
        default=True
    )

    # 2. 注册模块
    clipboard.register()
    bpy.utils.register_class(GN_PT_MainPanel)
    
    if hasattr(node_mappings, '_build_memory_cache'):
        node_mappings._build_memory_cache()
    elif hasattr(node_mappings, 'load_db'):
        node_mappings.load_db()
    
    print(f"[GeoNeural Bridge] v{bl_info['version']} Registered.")

def unregister():
    bpy.utils.unregister_class(GN_PT_MainPanel)
    clipboard.unregister()
    del bpy.types.Scene.gn_debug_mode
    del bpy.types.Scene.gn_compact_mode
    print(f"[GeoNeural Bridge] Unregistered.")

if __name__ == "__main__":
    register()