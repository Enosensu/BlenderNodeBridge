# BlenderNodeBridge 🌉

*(Formerly GeoNeural Bridge)*

**BlenderNodeBridge** 是一款旨在打破大语言模型（LLM）与 Blender 节点系统底层 API 之间壁垒的终极“全节点”通用插件。

无论是**几何节点（Geometry Nodes）**、**着色器节点（Shader Nodes）还是合成器节点（Compositor Nodes）**，它都能将 AI 生成的极度自由、高度紧凑甚至偶尔带有“幻觉”的 JSON 数据，100% 稳健地在 Blender 中精准物理复原。

---

## ✨ 核心特性 (Core Features)

本项目彻底摒弃了传统的“面向字典打补丁”式的硬编码开发，重构为**“三位一体”的动态响应生态架构**，实现了对未来 Blender 版本的自适应兼容：

* 🧠 **智能语义大脑 (The Semantic Brain)**
* **跨域前缀纠错 (Namespace Rescue)**：自动剥离 AI 混淆的 API 前缀（如将 `FunctionNodeVectorRotate` 自动修正为 `ShaderNodeVectorRotate`），免疫命名空间幻觉。
* **动态降维与模糊匹配 (Fuzzy Mapping)**：无视大小写、下划线及拼写误差，在纯净语义层面上为 JSON 节点寻找 Blender 内存中的最优候选队列。


* 🛡️ **欧米茄级防御装甲 (Omega Armor Architecture)**
* **活体内存反射 (Live Reflection)**：采用深层递归 `__subclasses__()` 无死角扫描 Blender 内存，动态抓取最新版本的所有可用节点，告别过时的硬编码。
* **活跃插槽优先协议 (EVP / ASP)**：针对多态节点（如 `ShaderNodeMix`、`GeometryNodeSwitch`），通过读取插槽的 `enabled` 与 `hide` 状态，彻底消灭“废弃幽灵插槽”抢占连线的底层 Bug。
* **物理索引映射 (Index Identity Mapping)**：在图谱提取阶段，采用绝对物理 Index 替代不稳定的显示名称 (Name)，彻底杜绝同名插槽产生的数据截断与丢失。


* 🚀 **极致的 AI 交互优化 (LLM Context Optimization)**
* **超紧凑精简模式 (Compact Mode)**：导出时自动剥离冗余 UI 属性、未连接插槽的默认值及系统默认色块，将 JSON 体积压缩至极限，大幅节省大模型的 Token 开销。
* **全向双写与万能探针**：动态穿透 Zone 节点（Simulation/Repeat/Bake 等），完美实现 AI 对底层几何数据结构的高级操控。



---

## 🆕 近期更新 (Recent Updates - Omega Armor 系列)

* **v5.14.141 - Index Identity Mapping**: 重构序列化引擎，将连接锚点从 `(节点名, 插槽名)` 升维至绝对物理位置 `(节点名, 插槽索引)`，彻底解决 Math/Switch 等多输入同名插槽的数据剥离丢失问题。
* **v5.14.140 - Core Node Injection**: 修复了 Blender C++ 底层基石节点（如 `NodeGroupInput`、`NodeReroute`）未在 Python 类中暴露 ID 的历史暗坑，实现原生结构节点的无缝复制粘贴。
* **v5.14.137 - EVP Abstraction**: 将几何节点的“动态销毁”特性抽象为全局的 **Enabled Validation Priority (EVP)** 机制，统一了着色器节点与几何节点对“多态隐身插槽”的判定逻辑。
* **v5.14.134 - Hybrid Validation Lock**: 为拓扑愈合机制（Auto-Heal）引入前缀包容与相似度混合锁，防止外部缺失节点被“过度医疗”错连，同时包容 AI 生成短名称触发的 Blender `.001` 重命名操作。
* **v5.14.131 - Pulse-Sync Protocol**: 引入脉冲同步协议，强制刷新动态节点（Zone Nodes）在数据注入后的依赖图拓扑，消除毫秒级的时序真空断连问题。

---

## 📦 安装与使用 (Installation & Usage)

1. 下载本项目源代码。
2. 在 Blender 中打开 `编辑 (Edit)` > `偏好设置 (Preferences)` > `插件 (Add-ons)`。
3. 点击 `安装 (Install)` 并选择下载的 ZIP 文件（或包含 `__init__.py` 的文件夹）。
4. 勾选启用 **BlenderNodeBridge**。
5. **使用方法**：在任意节点编辑器（几何/着色器/合成器）侧边栏 `GeoNeural` 选项卡中，使用 `Copy Nodes` 将选中节点转换为紧凑 JSON 交给 AI，或使用 `Paste Nodes` 将 AI 编写的 JSON 物理具象化为节点树。

---

## 🤝 鸣谢 (Acknowledgements)

本项目在架构设计、深层 Blender API 源码剖析以及复杂模式抽象的迭代过程中，全程由 **Gemini 3.1 Pro** 辅助开发。特此致谢其在代码健壮性审查与 SOLID 原则实践中提供的“全知视角”级（Dev_Omniscient）技术洞察与支持。

---

## 📄 许可证 (License)

本项目基于 **[MIT License](https://www.google.com/search?q=LICENSE)** 开源。您可以自由地使用、修改和分发本项目的代码，只需保留原作者的版权声明和许可声明即可。
