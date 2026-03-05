# __init__.py
# BlenderNodeBridge v5.14.141 - UI Compact
# 修复: 移除 Debug 面板上方多余的 separator，减少 UI 留白，使布局更紧凑
# 基础: v5.14.6 (Twin Buttons)

bl_info = {
    "name": "BlenderNodeBridge (v5.14.141 UI)",
    "author": "Dev_Nodes_V5 & Dev_Analyst",
    "version": (5, 14, 141),
    "blender": (4, 0, 0),
    "location": "Node Editor > Sidebar > BlenderNodeBridge",
    "description": "UI 紧凑版：优化面板间距，提升视觉连贯性。",
    "category": "Node",
}

import bpy
import importlib
from .core import node_mappings

# 导入子模块 (Logic Layer)
from .operators import clipboard

modules_to_reload = [
    node_mappings,
    clipboard,
]

for m in modules_to_reload:
    importlib.reload(m)

# ==============================================================================
# 1. UI 面板 (Presentation Layer)
# ==============================================================================

class GN_PT_MainPanel(bpy.types.Panel):
    """BlenderNodeBridge 主面板"""
    bl_label = "BlenderNodeBridge"
    bl_idname = "GN_PT_main"
    bl_space_type = "NODE_EDITOR"
    bl_region_type = "UI"
    bl_category = "BlenderNodeBridge"

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        # --- 顶部状态栏 ---
        row = layout.row(align=True)
        try: 
            db_ok = node_mappings.load_db()
            if db_ok:
                row.label(text="AI Core: Ready", icon='CHECKMARK')
            else:
                row.label(text="AI Core: Offline", icon='ERROR')
        except: 
            row.label(text="System Error", icon='CANCEL')
        
        # 调试开关 (右上角)
        row.prop(scene, "gn_debug_mode", text="", icon='PREFERENCES')

        layout.separator()

        # --- 核心操作区 (Twin Buttons Design) ---
        box = layout.box()
        
        # 选项行
        row = box.row()
        row.prop(scene, "gn_compact_mode", text="精简模式 (AI Optimized)")
        
        layout.separator()
        
        # 使用 grid_flow 并排布局，并统一缩放
        grid = box.grid_flow(row_major=True, columns=2, even_columns=True, even_rows=True, align=True)
        
        # 左侧：复制按钮
        col_copy = grid.column(align=True)
        col_copy.scale_y = 1.6  # 统一高度 (大按钮)
        col_copy.operator("geonb.copy_nodes", text="复制 (Copy)", icon='COPYDOWN')
        
        # 右侧：粘贴按钮
        col_paste = grid.column(align=True)
        col_paste.scale_y = 1.6  # 统一高度 (大按钮)
        col_paste.operator("geonb.paste_nodes", text="粘贴 (Paste)", icon='PASTEDOWN')

        # --- 底部调试信息 (紧凑布局) ---
        if scene.gn_debug_mode:
            # [v5.14.7 修复] 移除了 layout.separator()，让两个 Box 紧挨着
            info_box = layout.box()
            info_box.label(text="Debug Info:", icon='INFO')
            info_box.label(text=f"Addon: {bl_info['version']}")
            info_box.label(text=f"Blender: {bpy.app.version_string}")

# ==============================================================================
# 2. 注册逻辑
# ==============================================================================

def register():
    # 注册场景属性 (Model State)
    bpy.types.Scene.gn_debug_mode = bpy.props.BoolProperty(
        name="Debug Mode",
        description="Enable verbose logging for troubleshooting",
        default=False
    )
    bpy.types.Scene.gn_compact_mode = bpy.props.BoolProperty(
        name="Compact Mode",
        description="Strip UI data to save Tokens for AI context",
        default=True
    )

    # 注册模块与面板
    clipboard.register()
    bpy.utils.register_class(GN_PT_MainPanel)
    
    # 初始化 AI 映射库
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