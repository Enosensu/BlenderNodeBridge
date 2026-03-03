import bpy
import json
import os
import mathutils

# ==============================================================================
# 配置：输出路径
# ==============================================================================
OUTPUT_PATH = os.path.join(os.path.expanduser("~"), "Desktop", "blender_node_schema.json")

# ==============================================================================
# 1. 崩溃防御体系 (Meltdown Protection)
# ==============================================================================

# [高危节点名单]
# 这些节点在 Factory Startup 模式下非常脆弱，读取其 Default Value 会导致 Access Violation
CRASH_RISK_NODES = {
    "CompositorNodeColorBalance",
    "CompositorNodeCryptomatte", 
    "CompositorNodeCryptomatteV2",
    "CompositorNodeDefocus", 
    "CompositorNodeImage", 
    "CompositorNodeViewer",
    "CompositorNodeSplit", 
    "CompositorNodeSwitchView",
    "CompositorNodePlaneTrackDeform", 
    "CompositorNodeStabilize",
    "CompositorNodeMovieClip", 
    "FunctionNodeFormatString",
    "CompositorNodeTrackPos",
    "CompositorNodeColorCorrection",
    "CompositorNodeTonemap"
}

# [高危属性类型]
SKIP_PROP_TYPES = {'POINTER', 'COLLECTION'}

# ==============================================================================
# 2. 终极兜底编码器 (The Bulletproof Encoder)
# ==============================================================================
class BlenderJSONEncoder(json.JSONEncoder):
    """
    不管遇到什么对象，绝对不报错。
    如果认识就转列表，不认识就转字符串。
    """
    def default(self, obj):
        try:
            # 1. 显式 Mathutils 支持 (最优先)
            if isinstance(obj, (mathutils.Vector, mathutils.Euler, mathutils.Color, mathutils.Quaternion, mathutils.Matrix)):
                return [round(x, 6) for x in obj]
            
            # 2. 鸭子类型支持 (Vector/Euler/Color 的通用接口)
            if hasattr(obj, "to_list"): return [round(x, 6) for x in obj.to_list()]
            if hasattr(obj, "to_tuple"): return [round(x, 6) for x in obj.to_tuple()]
            
            # 3. 数组/列表 (递归处理)
            # 排除字符串和字典，避免无限递归
            if hasattr(obj, "__iter__") and not isinstance(obj, (str, bytes, dict)):
                return [x for x in obj]
                
            # 4. Blender ID 对象
            if hasattr(obj, "name") and hasattr(obj, "rna_type"):
                return obj.name
                
            # 5. 尝试交给标准库处理 (int, float, None 等)
            return super().default(obj)
            
        except Exception:
            # [核心修复] 无论发生什么错误 (TypeError, AttributeError...)
            # 只要上面的转换失败，统统转为字符串。
            # 这保证了 Euler 等“漏网之鱼”也能被安全导出。
            return str(obj)

# ==============================================================================
# 3. 安全转换工具 (Pre-Processor)
# ==============================================================================

def safe_convert_value(val):
    """预处理：尽力将数据转为 Python 原生类型"""
    if val is None: return None
    
    try:
        # 显式 Mathutils 类型检测
        if isinstance(val, (mathutils.Vector, mathutils.Euler, mathutils.Color, mathutils.Quaternion)):
            return [round(x, 6) for x in val]

        # 常规方法检测
        if hasattr(val, "to_list"): return [round(x, 6) for x in val.to_list()]
        if hasattr(val, "to_tuple"): return [round(x, 6) for x in val.to_tuple()]
        
        # Blender ID 对象
        if hasattr(val, "name") and hasattr(val, "rna_type"): return val.name
        
        # 列表/数组 (递归)
        if hasattr(val, "__iter__") and not isinstance(val, (str, bytes)):
            return [safe_convert_value(item) for item in val]
            
        return val
    except:
        return None

# ==============================================================================
# 4. 沙盒环境
# ==============================================================================

def setup_sandbox():
    print("🏗️ 构建防崩溃沙盒...")
    assets = {}
    if "SafeDummyImg" not in bpy.data.images:
        assets["image"] = bpy.data.images.new("SafeDummyImg", 32, 32)
    else: assets["image"] = bpy.data.images["SafeDummyImg"]
    
    if "SafeDummyMat" not in bpy.data.materials:
        assets["material"] = bpy.data.materials.new("SafeDummyMat")
    else: assets["material"] = bpy.data.materials["SafeDummyMat"]
    
    if "SafeDummyTex" not in bpy.data.textures:
        assets["texture"] = bpy.data.textures.new("SafeDummyTex", type='CLOUDS')
    else: assets["texture"] = bpy.data.textures["SafeDummyTex"]
    
    try: bpy.context.scene.use_nodes = True
    except: pass
    return assets

def inject_dependencies(node, assets):
    try:
        if hasattr(node, "image"): node.image = assets["image"]
        if hasattr(node, "material"): node.material = assets["material"]
        if hasattr(node, "texture"): node.texture = assets["texture"]
    except: pass

# ==============================================================================
# 5. 核心提取逻辑
# ==============================================================================

def extract_property_schema(node, prop_id):
    # 1. 绝对禁止访问 FormatString 的 items
    if node.bl_idname == "FunctionNodeFormatString" and prop_id in {"format_items", "items"}:
        return None

    prop = node.bl_rna.properties.get(prop_id)
    if not prop: return None
    
    data = {
        "type": prop.type,
        "name": prop.name,
        "identifier": prop.identifier,
        "description": prop.description,
        "subtype": prop.subtype
    }
    
    if prop.type == 'ENUM':
        try: data['options'] = [i.identifier for i in prop.enum_items]
        except: data['options'] = []

    # --- 值的读取 (危险操作区) ---
    if prop.type in SKIP_PROP_TYPES:
        data['default'] = None
    elif node.bl_idname in CRASH_RISK_NODES:
        data['default'] = None
    else:
        try:
            raw_val = getattr(node, prop_id)
            data['default'] = safe_convert_value(raw_val)
        except:
            data['default'] = None
            
    return data

def extract_socket_schema(socket, node_idname):
    info = {
        "name": socket.name,
        "identifier": socket.identifier,
        "type": socket.bl_idname,
        "description": getattr(socket, "description", "")
    }
    
    # 高危节点不读 default_value
    if node_idname in CRASH_RISK_NODES:
        info["default"] = None
    else:
        if hasattr(socket, "default_value"):
            try:
                info["default"] = safe_convert_value(socket.default_value)
            except:
                info["default"] = None
    return info

def scan_all_nodes():
    candidates = set()
    prefixes = ("GeometryNode", "ShaderNode", "CompositorNode", "TextureNode", "FunctionNode")
    for name in dir(bpy.types):
        if any(name.startswith(p) for p in prefixes):
            candidates.add(name)
    manual_add = ["NodeGroup", "NodeGroupInput", "NodeGroupOutput", "NodeReroute", "NodeFrame"]
    for m in manual_add:
        candidates.add(m)
    return sorted(list(candidates))

# ==============================================================================
# 6. 主程序
# ==============================================================================

def main():
    print("-" * 40)
    print(f"🚀 启动 V20 终极防弹提取 (Blender {bpy.app.version_string})")
    print("-" * 40)
    
    assets = setup_sandbox()
    
    labs = {}
    tree_types = ["GeometryNodeTree", "ShaderNodeTree", "CompositorNodeTree", "TextureNodeTree"]
    for t in tree_types:
        try:
            if f"WAKE_{t}" in bpy.data.node_groups:
                bpy.data.node_groups.remove(bpy.data.node_groups[f"WAKE_{t}"])
            labs[t] = bpy.data.node_groups.new(f"WAKE_{t}", t)
        except: pass

    node_ids = scan_all_nodes()
    print(f"📚 扫描到 {len(node_ids)} 个节点类型")
    
    final_nodes = {}
    alias_map = {}
    socket_map = {}
    
    for bl_idname in node_ids:
        node = None
        used_lab = None
        
        for lab in labs.values():
            try:
                node = lab.nodes.new(bl_idname)
                used_lab = lab
                break
            except: continue
            
        if node:
            inject_dependencies(node, assets)
            
            node_info = {
                "bl_idname": bl_idname,
                "ui_name": node.bl_label or node.name,
                "category": getattr(node, "bl_icon", "NONE"),
                "width": getattr(node, "width", 140),
                "properties": {},
                "inputs": [],
                "outputs": []
            }
            
            # 提取端口
            for s in node.inputs:
                s_data = extract_socket_schema(s, bl_idname)
                node_info["inputs"].append(s_data)
                socket_map[s.bl_idname] = s.bl_idname
                
            for s in node.outputs:
                s_data = extract_socket_schema(s, bl_idname)
                node_info["outputs"].append(s_data)
                socket_map[s.bl_idname] = s.bl_idname

            # 提取属性
            SKIP_INTERNAL = {'rna_type', 'name', 'location', 'width', 'height', 'dimensions', 
                             'inputs', 'outputs', 'interface', 'internal_links', 'parent', 
                             'label', 'color', 'select', 'mute', 'use_custom_color'}
            
            for p_id in node.bl_rna.properties.keys():
                if p_id not in SKIP_INTERNAL:
                    prop_data = extract_property_schema(node, p_id)
                    if prop_data:
                        node_info["properties"][p_id] = prop_data
            
            final_nodes[bl_idname] = node_info
            
            alias_map[bl_idname] = bl_idname
            alias_map[node_info["ui_name"]] = bl_idname
            simple = bl_idname.replace("GeometryNode", "").replace("ShaderNode", "").replace("FunctionNode", "").replace("CompositorNode", "").replace("TextureNode", "")
            alias_map[simple] = bl_idname
            alias_map[simple.upper()] = bl_idname
            
            used_lab.nodes.remove(node)
            
    full_db = {
        "meta": {
            "version": bpy.app.version_string,
            "generator": "GeoNeural V20 Bulletproof",
            "socket_map": socket_map
        },
        "nodes": final_nodes,
        "alias_map": alias_map
    }
    
    try:
        # [关键] 启用 check_circular=False 以防万一，并使用自定义 cls
        with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
            json.dump(full_db, f, indent=2, ensure_ascii=False, cls=BlenderJSONEncoder, check_circular=False)
            
        print("-" * 40)
        print(f"✅ 成功！已提取 {len(final_nodes)} 个节点")
        print(f"📂 数据库路径: {OUTPUT_PATH}")
        print("-" * 40)
        
        def draw_msg(self, context):
            self.layout.label(text=f"提取完成: {len(final_nodes)} 个节点")
            self.layout.label(text=f"保存至桌面: blender_node_schema.json")
        bpy.context.window_manager.popup_menu(draw_msg, title="提取成功", icon='CHECKMARK')
        
    except Exception as e:
        print(f"❌ 导出文件失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
