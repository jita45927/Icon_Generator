# 图片转 ICO 图标生成器

一款基于 Python + CustomTkinter 开发的 Windows 桌面工具，用于把图片转换成符合 Windows 标准的 ICO 图标文件。

- GitHub：<https://github.com/jita45927/Icon_Generator>
- Gitee（国内镜像）：<https://gitee.com/matt8469/Icon_Generator>

## 功能特性

- ✅ **多格式输入**：支持 PNG、JPG、JPEG、BMP
- ✅ **自定义裁剪**：拖动裁剪框移动位置，拖四角调整大小（始终保持正方形），可一键重置
- ✅ **透明区域选择**：在预览图上点击取色，按颜色容差自动连通填充为透明，支持多次加选
- ✅ **圆角 Alpha**：一键给图片叠加透明圆角，适合做现代化风格图标
- ✅ **多尺寸打包**：一次生成 16×16、32×32、48×48、64×64、128×128、256×256 六种尺寸
- ✅ **透明通道保留**：完整处理 PNG Alpha 通道，输出 32 位 RGBA 图标
- ✅ **混合编码**：256×256 使用 PNG 压缩，小尺寸使用 BMP，兼顾体积与兼容性
- ✅ **实时预览**：左侧原图 + 右侧 256×256 效果预览（带透明棋盘格背景）
- ✅ **拖拽载入**：支持把图片直接拖进窗口（未安装 `tkinterdnd2` 时自动降级为按钮载入）
- ✅ **超大图片保护**：自动缩放处理超大尺寸图片，避免内存占用过高

## 下载与运行

### 方式一：直接使用 EXE（推荐）

前往 Releases 页面下载 `IconGenerator.exe`，双击即可运行，无需安装 Python 或任何依赖。

- GitHub Releases：<https://github.com/jita45927/Icon_Generator/releases>
- Gitee 发行版：<https://gitee.com/matt8469/Icon_Generator/releases>

> 单文件 EXE 首次启动稍慢属正常现象；个别杀毒软件可能误报，请自行添加信任。

### 方式二：源码运行

```bash
git clone https://github.com/jita45927/Icon_Generator.git
cd Icon_Generator
pip install -r requirements.txt
python main.py
```

要求 Python 3.8+（Windows 自带 tkinter）。

## 使用方法

1. **载入图片**：点击「选择图片」，或直接把图片拖进窗口
2. **调整裁剪**：拖动蓝色裁剪框移动位置，拖动四角小方块调整大小，点「重置裁剪」恢复居中
3. **应用裁剪**：点击「应用裁剪」把当前选区应用到图片
4. **可选处理**：
   - 点「添加圆角Alpha」生成圆角透明效果
   - 点「选择透明区域」进入吸管模式，在预览图上点击要去掉的颜色，拖动「颜色容差」滑块调整范围，可多次点击加选
5. **生成图标**：点击「生成 ICO 文件」，选择保存路径即可

## 技术规格

| 项目 | 说明 |
|---|---|
| 输入格式 | PNG、JPG、JPEG、BMP |
| 输出格式 | ICO（Windows 标准图标） |
| 输出尺寸 | 16、32、48、64、128、256 |
| 色彩模式 | 32 位 RGBA，支持透明 |
| 系统要求 | Windows 10 / Windows 11 |

## 打包为 EXE

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --icon "ICO.ico" --name IconGenerator main.py
```

打包结果位于 `dist/IconGenerator.exe`。

## 项目结构

```
Icon_Generator/
├── main.py             # 主程序（界面 + 图像处理）
├── ICO.ico             # 程序图标
├── requirements.txt    # 运行依赖
├── LICENSE             # MIT 许可证
└── README.md           # 项目说明
```

## 关注作者

- Bilibili：**[AI马特](https://space.bilibili.com/1351334510)**
- 本程序由 TRAE-IDE 辅助生成；通过 [分享链接](https://www.trae.cn/events/code-fission/B8F6GKVM5QPU?utm_source=copy_link&utm_medium=code_fission) 注册并登录桌面端，新用户可一次性获得 3,000 积分

## 许可证

本项目基于 [MIT License](LICENSE) 开源，Copyright (c) 2026 AI马特。
