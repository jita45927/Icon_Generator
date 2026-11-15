"""
PNG 转 Windows ICO 图标生成器
==============================
将 PNG/JPG/JPEG/BMP 图片转换为 Windows 标准 ICO 图标文件的单文件桌面应用。

核心功能:
  - 智能居中裁剪(将非正方形图片裁剪为正方形)
  - 应用裁剪(确认裁剪区域后写回图片,可先不生成 ICO)
  - 圆角 Alpha(给裁剪后的图片叠加透明圆角通道)
  - 选择透明区域(吸管取色,向四周扩散连通区域并置为透明,可多次点击加选)
  - 多尺寸打包(16x16 ~ 256x256 标准尺寸合并为单一 ICO)
  - 透明通道保留(完美处理 PNG Alpha 通道)
  - 拖拽载入与点击选择(所见即所得预览)

代码结构:
  - IconGenerator     : 图像处理类(裁剪/缩放/ICO 生成)
  - IconGeneratorApp  : UI 类(基于 CustomTkinter)
  - main()            : 程序入口
"""

import io
import os
import struct
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import Image, ImageChops, ImageDraw, ImageTk

# ============================================================================
# LANCZOS 重采样常量(兼容 Pillow 9.x 与 10.x)
# Pillow 10.0.0 移除了 Image.LANCZOS 顶层常量,改为 Image.Resampling.LANCZOS
# 这里做兼容处理,确保不同版本均可正常运行
# ============================================================================
try:
    LANCZOS = Image.Resampling.LANCZOS
    NEAREST = Image.Resampling.NEAREST
    FLIP_TOP_BOTTOM = Image.Transpose.FLIP_TOP_BOTTOM
except AttributeError:
    LANCZOS = Image.LANCZOS
    NEAREST = Image.NEAREST
    FLIP_TOP_BOTTOM = Image.FLIP_TOP_BOTTOM

# ============================================================================
# 拖拽支持(tkinterdnd2,可选依赖)
# 若环境未安装 tkinterdnd2,则降级为仅按钮载入模式
# ============================================================================
try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    DND_AVAILABLE = True
except ImportError:
    DND_AVAILABLE = False


# ============================================================================
# 窗口基类:根据 tkinterdnd2 是否可用进行条件继承
# - 可用时:混合 CustomTkinter 与 TkinterDnD.DnDWrapper,支持拖拽
# - 不可用:退化为纯 CustomTkinter.CTk
# ============================================================================
if DND_AVAILABLE:
    class CTkWithDnD(ctk.CTk, TkinterDnD.DnDWrapper):
        """混合 CustomTkinter 与 tkinterdnd2 的窗口基类,具备拖拽能力"""

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            # 加载 tkdnd Tcl 扩展
            self.TkdndVersion = TkinterDnD._require(self)

    BaseWindow = CTkWithDnD
else:
    BaseWindow = ctk.CTk


# ============================================================================
# 图像处理类:负责载入、裁剪、缩放、ICO 生成等核心算法
# ============================================================================
class IconGenerator:
    """图像处理类:负责裁剪、缩放、ICO 生成等核心算法"""

    # Windows 标准图标尺寸列表(从小到大)
    SIZES = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]

    # 圆角半径占图片边长的比例(用于"添加圆角Alpha")
    CORNER_RADIUS_RATIO = 0.2

    # "选择透明区域"的颜色容差(按最大通道差计算,0-255)
    ALPHA_PICK_TOLERANCE = 32

    # 超大图片保护阈值:任一边超过此值则触发等比缩小
    MAX_INPUT_DIM = 5000
    # 缩小后的安全最大边长
    SAFE_MAX_DIM = 1024

    def load_image(self, input_path):
        """
        载入图片并做预处理
          1. 打开图片
          2. 强制转换为 RGBA 模式(确保透明通道被正确处理)
          3. 超大图片保护:若任一边 > 5000px,等比缩小至 1024px
        返回:
          PIL.Image (RGBA 模式)
        """
        # 打开图片文件
        img = Image.open(input_path)
        # 强制转换为 RGBA,确保透明背景被正确识别
        img = img.convert("RGBA")

        w, h = img.size
        # 超大图片保护,防止内存溢出
        if max(w, h) > self.MAX_INPUT_DIM:
            ratio = self.SAFE_MAX_DIM / max(w, h)
            new_size = (max(1, int(w * ratio)), max(1, int(h * ratio)))
            img = img.resize(new_size, LANCZOS)

        return img

    def center_crop_square(self, img):
        """
        智能居中裁剪为正方形
        以图片中心为基准,取较短边为边长裁剪,保留核心视觉区域
        """
        w, h = img.size
        min_dim = min(w, h)
        # 裁剪坐标计算(以中心为基准)
        left = (w - min_dim) / 2
        top = (h - min_dim) / 2
        right = (w + min_dim) / 2
        bottom = (h + min_dim) / 2
        return img.crop((left, top, right, bottom))

    def custom_crop_square(self, img, x, y, size):
        """
        自定义区域裁剪为正方形
        参数:
          img  : PIL Image
          x    : 裁剪区域左上角x坐标
          y    : 裁剪区域左上角y坐标
          size : 裁剪区域边长(正方形)
        返回:
          PIL.Image 裁剪后的图像
        """
        w, h = img.size
        # 确保裁剪区域在图片范围内
        x = max(0, min(x, w - size))
        y = max(0, min(y, h - size))
        size = max(1, min(size, w - x, h - y))
        return img.crop((x, y, x + size, y + size))

    def apply_rounded_alpha(self, img, radius_ratio=None):
        """
        给正方形图片叠加圆角 Alpha 通道
          1. 按边长比例计算圆角半径
          2. 以 4 倍超采样绘制蒙版后缩小,得到平滑的抗锯齿边缘
          3. 与原图 Alpha 相乘,保留图片自带的透明区域
        参数:
          img         : PIL Image
          radius_ratio: 圆角半径占边长的比例,None 则使用默认值
        返回:
          PIL.Image (RGBA)
        """
        if radius_ratio is None:
            radius_ratio = self.CORNER_RADIUS_RATIO

        img = img.convert("RGBA")
        w, h = img.size
        radius = max(1, int(round(min(w, h) * radius_ratio)))

        # 超采样绘制圆角蒙版,缩小后边缘更平滑
        scale = 4
        mask = Image.new("L", (w * scale, h * scale), 0)
        draw = ImageDraw.Draw(mask)
        draw.rounded_rectangle(
            [0, 0, w * scale - 1, h * scale - 1],
            radius=radius * scale,
            fill=255
        )
        mask = mask.resize((w, h), LANCZOS)

        # 与原 Alpha 相乘,避免覆盖图片已有透明区域
        alpha = ImageChops.multiply(img.getchannel("A"), mask)
        img.putalpha(alpha)
        return img

    def build_transparent_region(self, img, xy, tolerance=None):
        """
        从种子点向外扩散,返回与种子颜色相近且连通的区域蒙版
          - 与"全局同色替换"不同:只处理连通区域,遇到封闭边界即停止
          - 颜色相似度按 RGB 最大通道差判断
        参数:
          img      : PIL Image
          xy       : 种子点坐标 (x, y)
          tolerance: 颜色容差(0-255),None 则使用默认值
        返回:
          PIL.Image (L 模式,255 表示选中区域,0 表示未选中)
        """
        if tolerance is None:
            tolerance = self.ALPHA_PICK_TOLERANCE

        rgb = img.convert("RGB")
        w, h = rgb.size
        x = max(0, min(int(xy[0]), w - 1))
        y = max(0, min(int(xy[1]), h - 1))
        seed = rgb.getpixel((x, y))

        # 逐通道计算与种子色的差值,取其最大值作为颜色距离
        r, g, b = rgb.split()
        diff = ImageChops.difference(r, Image.new("L", rgb.size, seed[0]))
        for chan, value in ((g, seed[1]), (b, seed[2])):
            diff = ImageChops.lighter(
                diff,
                ImageChops.difference(chan, Image.new("L", rgb.size, value))
            )

        # 阈值化为二值图:255 表示颜色与种子相近
        similar = diff.point(lambda v: 255 if v <= tolerance else 0)

        # 在二值图上做连通填充(阈值为 0,只扩散到相近像素),128 为临时标记色
        ImageDraw.floodfill(similar, (x, y), 128, thresh=0)

        # 取出被标记的连通区域
        return similar.point(lambda v: 255 if v == 128 else 0)

    def apply_region_alpha(self, img, region_mask, offset=(0, 0)):
        """
        把指定区域设为完全透明(Alpha 置 0),用于"选择透明区域"
        参数:
          img        : PIL Image
          region_mask: L 模式蒙版(255 表示透明区域)
          offset     : 蒙版在 img 中的左上角偏移
        返回:
          PIL.Image (RGBA)
        """
        img = img.convert("RGBA")
        # 将区域蒙版铺回整图坐标
        full_mask = Image.new("L", img.size, 0)
        full_mask.paste(region_mask, offset)

        # 区域内的 Alpha 置 0,区域外保持原有 Alpha
        alpha = Image.composite(
            Image.new("L", img.size, 0), img.getchannel("A"), full_mask
        )
        img.putalpha(alpha)
        return img

    def generate_icon_sizes(self, img_cropped):
        """
        根据裁剪后的正方形图片生成多尺寸列表
          - 使用 LANCZOS 重采样保证小尺寸图标清晰度
          - 若原图裁剪后边长 < 目标尺寸,跳过该尺寸
        返回:
          list[PIL.Image] 各尺寸的图像列表
        """
        result = []
        cropped_dim = min(img_cropped.size)
        for size in self.SIZES:
            # 跳过原图小于目标尺寸的
            if cropped_dim < size[0]:
                continue
            resized = img_cropped.resize(size, LANCZOS)
            result.append(resized)
        return result

    @staticmethod
    def _encode_png_layer(img):
        """
        将单张图像编码为 PNG 图层数据(用于 256x256)
        PNG 体积远小于 BMP,且 Windows Vista 及以上原生支持
        """
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()

    @staticmethod
    def _encode_bmp_layer(img):
        """
        将单张图像编码为 ICO 内的 32bpp BMP 图层数据(用于 128 及以下)
          - BITMAPINFOHEADER:biHeight 必须为实际高度的 2 倍
            (上半部分为 XOR 位图,下半部分为 AND mask)
          - XOR 位图:BGRA 顺序、行序自下而上
          - AND mask:1 表示完全透明,行序自下而上,每行按 4 字节对齐
        这是兼容性最好的图标图层格式,所有 Windows API 与外壳路径都能正确处理
        """
        img = img.convert("RGBA")
        w, h = img.size
        r, g, b, a = img.split()

        # XOR 位图:RGB 通道换为 BGRA,再垂直翻转
        bgra = Image.merge("RGBA", (b, g, r, a))
        xor_data = bgra.transpose(FLIP_TOP_BOTTOM).tobytes()

        # AND mask:仅 alpha==0 的像素置 1(完全透明)
        alpha_bytes = a.tobytes()
        stride = ((w + 31) // 32) * 4
        mask_data = bytearray()
        for y in range(h - 1, -1, -1):
            row = bytearray(stride)
            base = y * w
            for x in range(w):
                if alpha_bytes[base + x] == 0:
                    row[x >> 3] |= 0x80 >> (x & 7)
            mask_data += row

        header = struct.pack(
            "<IiiHHIIiiII",
            40,                                # biSize
            w,                                 # biWidth
            h * 2,                             # biHeight(XOR + AND mask)
            1,                                 # biPlanes
            32,                                # biBitCount
            0,                                 # biCompression = BI_RGB
            len(xor_data) + len(mask_data),    # biSizeImage
            0, 0, 0, 0                         # 分辨率/调色板字段
        )
        return header + xor_data + bytes(mask_data)

    def generate_ico(self, img, output_path):
        """
        将处理好的正方形图片打包为多尺寸 ICO
        图层格式(兼容性优先):
          - 256x256      : PNG 压缩(体积小)
          - 128 及以下   : 32bpp BMP + 1-bit AND mask(全平台兼容)
        参数:
          img         : PIL Image(RGBA),应已裁剪为正方形并叠加好 Alpha
          output_path : 输出 ICO 文件路径
        返回:
          list[tuple[int, int]] 实际生成的尺寸列表
        """
        # 1. 生成多尺寸列表
        icon_images = self.generate_icon_sizes(img)

        # 兜底:若所有尺寸都被跳过(理论上不会,因为最小 16x16),使用原图
        if not icon_images:
            icon_images = [img]

        # 按尺寸降序排列,便于系统优先取大尺寸
        icon_images.sort(key=lambda im: im.size[0], reverse=True)

        # 2. 逐尺寸编码图层(Pillow 的 ICO 保存不支持按尺寸混用格式,故手动组装)
        layers = []
        for im in icon_images:
            im = im.convert("RGBA")
            if max(im.size) >= 256:
                data = self._encode_png_layer(im)
            else:
                data = self._encode_bmp_layer(im)
            layers.append((im.size, data))

        # 3. 组装 ICONDIR + ICONDIRENTRY 列表 + 图层数据
        count = len(layers)
        header = struct.pack("<HHH", 0, 1, count)   # reserved / type=1(ICON) / count
        offset = 6 + 16 * count                     # 图层数据的起始偏移
        directory = b""
        for (w, h), data in layers:
            directory += struct.pack(
                "<BBBBHHII",
                w & 0xFF,      # 宽(256 写 0)
                h & 0xFF,      # 高(256 写 0)
                0,             # 调色板颜色数(真彩色为 0)
                0,             # 保留字段
                1,             # 色彩平面数
                32,            # 每像素位数
                len(data),     # 图层数据长度
                offset         # 图层数据偏移
            )
            offset += len(data)

        with open(output_path, "wb") as f:
            f.write(header + directory + b"".join(data for _, data in layers))

        return [size for size, _ in layers]

    @staticmethod
    def is_image_file(file_path):
        """
        校验文件扩展名是否为支持的图片格式
        支持:PNG / JPG / JPEG / BMP
        """
        ext = os.path.splitext(file_path)[1].lower()
        return ext in ('.png', '.jpg', '.jpeg', '.bmp')

    @staticmethod
    def check_small_image(img):
        """
        检测极小图片:若原图小于 16x16 返回 True
        用于提示用户分辨率过低(但不阻止载入)
        """
        w, h = img.size
        return w < 16 or h < 16


# ============================================================================
# UI 类:基于 CustomTkinter 构建界面、绑定事件、显示状态
# ============================================================================
class IconGeneratorApp(BaseWindow):
    """
    主界面类(基于 CustomTkinter)
    负责:界面构建、事件绑定、预览显示、状态栏更新
    """

    # 预览区尺寸配置
    ORIGINAL_PREVIEW_BOX = (340, 340)  # 原图预览最大边界(按比例缩放适应)
    EFFECT_PREVIEW_SIZE = (256, 256)   # 效果预览固定尺寸
    CHECKER_CELL = 16                  # 透明网格每格像素大小

    # 状态栏颜色(区分不同状态)
    COLOR_READY = "gray70"       # 就绪/空闲
    COLOR_PROCESS = "#F0AD4E"    # 处理中(黄)
    COLOR_SUCCESS = "#28A745"    # 成功(绿)
    COLOR_ERROR = "#DC3545"      # 错误(红)

    # 标题下方推广信息(点击超链接打开注册链接)
    PROMO_URL = (
        "https://www.trae.cn/events/code-fission/B8F6GKVM5QPU"
        "?utm_source=copy_link&utm_medium=code_fission"
    )
    PROMO_TEXT = (
        "本程序由 TRAE-IDE 辅助生成，通过我的分享链接注册并登录桌面端，"
        "新用户一次性获得 3,000 积分！"
    )
    BILI_URL = "https://space.bilibili.com/1351334510"
    BILI_TEXT = "BILIBILI-【AI马特】"

    def __init__(self):
        super().__init__()

        # ===== 全局主题配置(现代化暗色主题 + 蓝色配色)=====
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        # ===== 窗口配置 =====
        self.title("图片 转 ICO 图标生成器")
        self.geometry("800x600")
        self.minsize(640, 480)

        # ===== 状态变量 =====
        self.current_image = None         # 当前载入的 PIL Image (RGBA)
        self.current_image_path = None    # 当前图片文件路径
        self.generator = IconGenerator()  # 图像处理器实例

        # 预览图引用(必须保存为实例属性,防止被 Python 垃圾回收导致图片不显示)
        self._original_ctk_image = None
        self._effect_ctk_image = None

        # 裁剪区域状态
        self.crop_x = 0                   # 裁剪区域左上角x坐标(原图坐标)
        self.crop_y = 0                   # 裁剪区域左上角y坐标(原图坐标)
        self.crop_size = 0                # 裁剪区域边长(正方形)
        self.display_crop_x = 0           # 裁剪区域左上角x坐标(Canvas显示坐标)
        self.display_crop_y = 0           # 裁剪区域左上角y坐标(Canvas显示坐标)
        self.display_crop_size = 0        # 裁剪区域显示边长

        # 拖动状态
        self.drag_mode = None             # None / 'move' / 'resize'
        self.drag_start_x = 0
        self.drag_start_y = 0
        self.drag_start_crop_x = 0
        self.drag_start_crop_y = 0
        self.drag_start_crop_size = 0

        # 图片缩放比例(原图 -> Canvas显示)
        self.image_scale = 1.0
        # 图片在Canvas上的偏移(居中显示)
        self.image_offset_x = 0
        self.image_offset_y = 0

        # 选择透明区域(吸管模式)状态
        self.pick_mode = False              # 是否处于吸管取色模式
        self.pending_region_mask = None     # 待确认的区域蒙版(裁剪图尺寸)
        self.pending_region_offset = (0, 0) # 该蒙版在 current_image 中的偏移
        self.pending_seeds = []             # 已点击的种子点列表(支持加选)
        self._tolerance_job = None          # 容差滑动时的延迟重算任务

        # ===== 构建 UI(从上到下)=====
        self._build_title()         # 1. 标题区
        self._build_preview_area()  # 2. 预览区(原图 + 效果预览)
        self._build_action_area()   # 3. 操作区(两个按钮)
        self._build_status_bar()    # 4. 状态栏

        # 注册拖拽(若 tkinterdnd2 可用)
        if DND_AVAILABLE:
            try:
                self.drop_target_register(DND_FILES)
                self.dnd_bind('<<Drop>>', self.on_drop)
            except Exception:
                # 拖拽不可用,静默降级为仅按钮载入
                pass

        # 绑定窗口大小改变事件
        self.bind("<Configure>", self.on_window_resize)

        # 初始状态
        self.set_status("就绪", self.COLOR_READY)

    # ======================== UI 构建方法 ========================

    def _build_title(self):
        """构建标题区:显示程序标题与推广信息"""
        self.title_label = ctk.CTkLabel(
            self,
            text="图片 转 ICO 图标生成器",
            font=ctk.CTkFont(size=22, weight="bold")
        )
        self.title_label.pack(pady=(15, 2))

        # 标题下方推广信息(说明文字 + 可点击的超链接)
        promo_frame = ctk.CTkFrame(self, fg_color="transparent")
        promo_frame.pack(pady=(0, 5))

        self.promo_label = ctk.CTkLabel(
            promo_frame,
            text=self.PROMO_TEXT,
            font=ctk.CTkFont(size=11),
            text_color="#4FA3FF",
            justify="center",
            wraplength=720
        )
        self.promo_label.pack()

        self.promo_link = ctk.CTkLabel(
            promo_frame,
            text="【注册地址】点此注册",
            font=ctk.CTkFont(size=12, underline=True),
            text_color="#4FA3FF",
            cursor="hand2"
        )
        self.promo_link.pack(pady=(2, 0))
        self.promo_link.bind("<Button-1>", self._open_promo_link)

        # B 站主页超链接
        self.bili_link = ctk.CTkLabel(
            promo_frame,
            text=self.BILI_TEXT,
            font=ctk.CTkFont(size=12, underline=True),
            text_color="#4FA3FF",
            cursor="hand2"
        )
        self.bili_link.pack(pady=(2, 0))
        self.bili_link.bind("<Button-1>", lambda event: webbrowser.open(self.BILI_URL))

    def _open_promo_link(self, event=None):
        """点击推广信息时用默认浏览器打开注册链接"""
        webbrowser.open(self.PROMO_URL)

    def _build_preview_area(self):
        """构建预览区:左侧原图 + 右侧效果预览(带透明网格)"""
        # 预览区主容器
        self.preview_frame = ctk.CTkFrame(self, corner_radius=10)
        self.preview_frame.pack(fill="both", expand=True, padx=20, pady=10)

        # 配置两列等宽布局
        self.preview_frame.columnconfigure(0, weight=1, uniform="preview")
        self.preview_frame.columnconfigure(1, weight=1, uniform="preview")
        self.preview_frame.rowconfigure(1, weight=1)

        # 左侧标题 "原图 (拖动裁剪框选择区域)"
        ctk.CTkLabel(
            self.preview_frame, text="原图 (拖动裁剪框选择区域)",
            font=ctk.CTkFont(size=14, weight="bold")
        ).grid(row=0, column=0, pady=(10, 5))

        # 右侧标题 "效果预览 (256x256)"
        ctk.CTkLabel(
            self.preview_frame, text="效果预览 (256x256)",
            font=ctk.CTkFont(size=14, weight="bold")
        ).grid(row=0, column=1, pady=(10, 5))

        # ---------- 左侧:原图预览容器(使用Canvas支持裁剪框) ----------
        self.original_frame = ctk.CTkFrame(
            self.preview_frame, corner_radius=8,
            border_width=2, border_color="gray50"
        )
        self.original_frame.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")
        # 禁止子控件影响容器尺寸,保持网格分配的空间
        self.original_frame.pack_propagate(False)

        # 原图Canvas(支持绘制裁剪框和鼠标交互)
        self.original_canvas = tk.Canvas(
            self.original_frame, bg="#222222",
            highlightthickness=0, cursor="crosshair"
        )
        self.original_canvas.pack(fill="both", expand=True)

        # 绑定鼠标事件
        self.original_canvas.bind("<ButtonPress-1>", self.on_canvas_press)
        self.original_canvas.bind("<B1-Motion>", self.on_canvas_drag)
        self.original_canvas.bind("<ButtonRelease-1>", self.on_canvas_release)

        # ---------- 右侧:效果预览容器 ----------
        self.effect_frame = ctk.CTkFrame(
            self.preview_frame, corner_radius=8,
            border_width=2, border_color="gray50"
        )
        self.effect_frame.grid(row=1, column=1, padx=10, pady=10, sticky="nsew")
        self.effect_frame.pack_propagate(False)

        # 效果预览标签
        self.effect_label = ctk.CTkLabel(
            self.effect_frame,
            text="等待图片载入",
            font=ctk.CTkFont(size=14),
            text_color="gray60",
            justify="center"
        )
        self.effect_label.pack(expand=True)

        # 吸管模式:点击效果预览取色
        self.effect_label.bind("<Button-1>", self.on_effect_click)

    def _build_action_area(self):
        """构建操作区:第一行编辑按钮,第二行透明区域与生成 ICO,第三行确认操作"""
        self.action_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.action_frame.pack(fill="x", padx=20, pady=(0, 10))

        # ---------- 第一行:选择/裁剪/圆角相关操作 ----------
        edit_frame = ctk.CTkFrame(self.action_frame, fg_color="transparent")
        edit_frame.pack(fill="x", pady=(0, 8))

        # "选择图片" 按钮
        self.select_btn = ctk.CTkButton(
            edit_frame, text="选择图片",
            font=ctk.CTkFont(size=15, weight="bold"),
            height=40, command=self.on_select_image
        )
        self.select_btn.pack(side="left", expand=True, fill="x", padx=(0, 8))

        # "重置裁剪" 按钮
        self.reset_crop_btn = ctk.CTkButton(
            edit_frame, text="重置裁剪",
            font=ctk.CTkFont(size=15, weight="bold"),
            height=40, command=self.on_reset_crop,
            fg_color="#6C757D", hover_color="#5A6268"
        )
        self.reset_crop_btn.pack(side="left", expand=True, fill="x", padx=(0, 8))

        # "应用裁剪" 按钮:把裁剪区域写回图片,不生成 ICO
        self.apply_crop_btn = ctk.CTkButton(
            edit_frame, text="应用裁剪",
            font=ctk.CTkFont(size=15, weight="bold"),
            height=40, command=self.on_apply_crop
        )
        self.apply_crop_btn.pack(side="left", expand=True, fill="x", padx=(0, 8))

        # "添加圆角Alpha" 按钮:先应用裁剪,再叠加圆角透明通道
        self.rounded_alpha_btn = ctk.CTkButton(
            edit_frame, text="添加圆角Alpha",
            font=ctk.CTkFont(size=15, weight="bold"),
            height=40, command=self.on_apply_rounded_alpha
        )
        self.rounded_alpha_btn.pack(side="left", expand=True, fill="x", padx=(8, 0))

        # ---------- 第二行:选择透明区域 + 生成 ICO 文件 ----------
        row2 = ctk.CTkFrame(self.action_frame, fg_color="transparent")
        row2.pack(fill="x", pady=(0, 8))

        # "选择透明区域" 按钮:进入吸管模式,点击区域后扩散填充 Alpha
        self.pick_btn = ctk.CTkButton(
            row2, text="选择透明区域",
            font=ctk.CTkFont(size=15, weight="bold"),
            height=40, command=self.on_pick_transparent
        )
        self.pick_btn.pack(side="left", expand=True, fill="x", padx=(0, 8))

        # "生成 ICO 文件" 按钮
        self.generate_btn = ctk.CTkButton(
            row2, text="生成 ICO 文件",
            font=ctk.CTkFont(size=15, weight="bold"),
            height=40, command=self.on_generate_ico
        )
        self.generate_btn.pack(side="left", expand=True, fill="x", padx=(8, 0))

        # ---------- 颜色容差滑块(吸管模式下显示) ----------
        self.tolerance_frame = ctk.CTkFrame(self.action_frame, fg_color="transparent")

        ctk.CTkLabel(
            self.tolerance_frame, text="颜色容差",
            font=ctk.CTkFont(size=13), anchor="w", width=64
        ).pack(side="left")

        self.tolerance_slider = ctk.CTkSlider(
            self.tolerance_frame, from_=0, to=128, number_of_steps=128,
            command=self.on_tolerance_change
        )
        self.tolerance_slider.set(self.generator.ALPHA_PICK_TOLERANCE)
        self.tolerance_slider.pack(side="left", expand=True, fill="x", padx=8)

        self.tolerance_value_label = ctk.CTkLabel(
            self.tolerance_frame, text=str(self.generator.ALPHA_PICK_TOLERANCE),
            font=ctk.CTkFont(size=13), width=36
        )
        self.tolerance_value_label.pack(side="left")

        # ---------- 第三行:透明区域确认操作(默认隐藏) ----------
        self.confirm_frame = ctk.CTkFrame(self.action_frame, fg_color="transparent")

        self.confirm_btn = ctk.CTkButton(
            self.confirm_frame, text="确定应用",
            font=ctk.CTkFont(size=15, weight="bold"),
            height=36, command=self.on_confirm_region,
            fg_color="#28A745", hover_color="#218838"
        )
        self.confirm_btn.pack(side="left", expand=True, fill="x", padx=(0, 8))

        self.cancel_btn = ctk.CTkButton(
            self.confirm_frame, text="取消",
            font=ctk.CTkFont(size=15, weight="bold"),
            height=36, command=self.on_cancel_region,
            fg_color="#6C757D", hover_color="#5A6268"
        )
        self.cancel_btn.pack(side="left", expand=True, fill="x", padx=(8, 0))

    def _build_status_bar(self):
        """构建底部状态栏:显示当前状态"""
        self.status_frame = ctk.CTkFrame(self, corner_radius=0, height=30)
        self.status_frame.pack(fill="x", side="bottom")

        self.status_label = ctk.CTkLabel(
            self.status_frame, text="就绪",
            font=ctk.CTkFont(size=12),
            text_color=self.COLOR_READY,
            anchor="w"
        )
        self.status_label.pack(side="left", padx=15)

    # ======================== 状态栏更新 ========================

    def set_status(self, text, color=None):
        """
        更新状态栏文本与颜色
        参数:
          text  : 状态文本
          color : 文本颜色(可选,不传则保持当前颜色)
        """
        self.status_label.configure(text=text)
        if color is not None:
            self.status_label.configure(text_color=color)

    # ======================== 图片载入与预览 ========================

    def load_image_file(self, file_path):
        """
        载入图片文件并更新预览
        包含:格式校验、极小图片提示、预览更新
        """
        # 格式校验:仅接受 PNG/JPG/JPEG/BMP
        if not self.generator.is_image_file(file_path):
            messagebox.showwarning("格式不支持", "仅支持 PNG/JPG/JPEG/BMP 格式")
            self.set_status("错误:不支持的文件格式", self.COLOR_ERROR)
            return

        try:
            # 载入并预处理图片
            img = self.generator.load_image(file_path)
            self.current_image = img
            self.current_image_path = file_path

            # 重置裁剪区域状态
            self.crop_x = 0
            self.crop_y = 0
            self.crop_size = 0

            # 新图片载入,清除吸管模式与待确认区域
            self._clear_pending_region()
            self._exit_pick_mode()

            # 极小图片提示(弹出警告,但不阻止载入)
            if self.generator.check_small_image(img):
                messagebox.showwarning(
                    "分辨率过低",
                    "图片分辨率过低,建议至少 256x256"
                )

            # 更新原图与效果预览
            self._update_previews()
            self.set_status(
                f"已载入:{os.path.basename(file_path)}",
                self.COLOR_READY
            )
        except Exception as e:
            # 载入失败,清空状态并提示
            self.current_image = None
            self.current_image_path = None
            messagebox.showerror("载入失败", f"无法读取图片:\n{e}")
            self.set_status(f"错误:{e}", self.COLOR_ERROR)

    def _current_cropped_image(self):
        """
        返回当前裁剪区域对应的正方形图片
        未设置裁剪区域时按居中裁剪计算
        """
        if self.current_image is None:
            return None
        if self.crop_size > 0:
            return self.generator.custom_crop_square(
                self.current_image, self.crop_x, self.crop_y, self.crop_size
            )
        return self.generator.center_crop_square(self.current_image)

    def _update_previews(self):
        """更新原图预览与效果预览(256x256 带透明网格)"""
        if self.current_image is None:
            return

        # ---------- 原图预览:使用Canvas显示图片和裁剪框----------
        self._update_canvas_preview()

        # ---------- 效果预览:裁剪 -> 256x256 -> 叠加透明网格 ----------
        self._update_effect_preview()

    def _update_canvas_preview(self):
        """更新Canvas预览图和裁剪框"""
        if self.current_image is None:
            return

        canvas_width = self.original_canvas.winfo_width()
        canvas_height = self.original_canvas.winfo_height()

        if canvas_width <= 1 or canvas_height <= 1:
            return

        # 清空Canvas
        self.original_canvas.delete("all")

        # 计算缩放比例(保持原图比例适应Canvas)
        img_w, img_h = self.current_image.size
        scale_w = canvas_width / img_w
        scale_h = canvas_height / img_h
        self.image_scale = min(scale_w, scale_h)

        # 计算显示尺寸和偏移(居中显示)
        display_w = int(img_w * self.image_scale)
        display_h = int(img_h * self.image_scale)
        self.image_offset_x = (canvas_width - display_w) // 2
        self.image_offset_y = (canvas_height - display_h) // 2

        # 缩放图片用于显示
        display_img = self.current_image.resize((display_w, display_h), LANCZOS)
        
        # 使用 ImageTk.PhotoImage 在 Canvas 上显示图片
        self._original_tk_image = ImageTk.PhotoImage(display_img)

        # 在Canvas上显示图片
        self.original_canvas.create_image(
            self.image_offset_x, self.image_offset_y,
            image=self._original_tk_image,
            anchor="nw"
        )

        # 设置初始裁剪区域(居中正方形)
        if self.crop_size == 0:
            min_dim = min(img_w, img_h)
            self.crop_size = min_dim
            self.crop_x = (img_w - min_dim) // 2
            self.crop_y = (img_h - min_dim) // 2

        # 转换裁剪区域坐标到Canvas显示坐标
        self.display_crop_x = int(self.crop_x * self.image_scale + self.image_offset_x)
        self.display_crop_y = int(self.crop_y * self.image_scale + self.image_offset_y)
        self.display_crop_size = int(self.crop_size * self.image_scale)

        # 绘制裁剪框
        self._draw_crop_rect()

    def _draw_crop_rect(self):
        """绘制裁剪框"""
        self.original_canvas.delete("crop")

        x1 = self.display_crop_x
        y1 = self.display_crop_y
        x2 = x1 + self.display_crop_size
        y2 = y1 + self.display_crop_size

        # 绘制半透明遮罩(裁剪框外的区域变暗)
        canvas_width = self.original_canvas.winfo_width()
        canvas_height = self.original_canvas.winfo_height()

        # 左上区域
        self.original_canvas.create_rectangle(
            0, 0, x1, canvas_height,
            fill="#000000", stipple="gray50",
            tags="crop"
        )
        # 右上区域
        self.original_canvas.create_rectangle(
            x2, 0, canvas_width, canvas_height,
            fill="#000000", stipple="gray50",
            tags="crop"
        )
        # 中间上方区域
        self.original_canvas.create_rectangle(
            x1, 0, x2, y1,
            fill="#000000", stipple="gray50",
            tags="crop"
        )
        # 中间下方区域
        self.original_canvas.create_rectangle(
            x1, y2, x2, canvas_height,
            fill="#000000", stipple="gray50",
            tags="crop"
        )

        # 绘制裁剪框边框(蓝色)
        self.original_canvas.create_rectangle(
            x1, y1, x2, y2,
            outline="#00BFFF", width=2,
            tags="crop"
        )

        # 绘制四角小方块(用于调整大小)
        handle_size = 8
        corners = [
            (x1, y1), (x2 - handle_size, y1),
            (x1, y2 - handle_size), (x2 - handle_size, y2 - handle_size)
        ]
        for cx, cy in corners:
            self.original_canvas.create_rectangle(
                cx, cy, cx + handle_size, cy + handle_size,
                fill="#00BFFF", outline="#FFFFFF", width=1,
                tags="crop"
            )

    def _create_checkerboard(self, size):
        """
        创建棋盘格透明背景(浅灰与白色交替)
        用于在效果预览中直观展示图标的透明区域
        参数:
          size : 棋盘格图像尺寸 (width, height)
        返回:
          PIL.Image (RGBA)
        """
        # 创建白色底
        bg = Image.new("RGBA", size, (255, 255, 255, 255))
        draw = ImageDraw.Draw(bg)
        light = (220, 220, 220, 255)  # 浅灰色
        cell = self.CHECKER_CELL
        # 绘制交替的浅灰方块
        for y in range(0, size[1], cell):
            for x in range(0, size[0], cell):
                if ((x // cell) + (y // cell)) % 2 == 0:
                    draw.rectangle(
                        [x, y, x + cell - 1, y + cell - 1],
                        fill=light
                    )
        return bg

    # ======================== 裁剪区域鼠标事件 ========================

    def on_canvas_press(self, event):
        """Canvas鼠标按下事件"""
        if self.current_image is None:
            return

        x = event.x
        y = event.y

        x1 = self.display_crop_x
        y1 = self.display_crop_y
        x2 = x1 + self.display_crop_size
        y2 = y1 + self.display_crop_size

        handle_size = 8

        # 判断是否点击了四角调整柄
        corners = [
            (x1, y1, x1 + handle_size, y1 + handle_size),
            (x2 - handle_size, y1, x2, y1 + handle_size),
            (x1, y2 - handle_size, x1 + handle_size, y2),
            (x2 - handle_size, y2 - handle_size, x2, y2)
        ]

        for i, (cx1, cy1, cx2, cy2) in enumerate(corners):
            if cx1 <= x <= cx2 and cy1 <= y <= cy2:
                self.drag_mode = 'resize'
                self.drag_corner = i
                break
        else:
            # 判断是否点击了裁剪框内部(移动模式)
            if x1 <= x <= x2 and y1 <= y <= y2:
                self.drag_mode = 'move'
            else:
                return

        # 裁剪区域即将变化,待确认的透明区域失效
        if self.pending_region_mask is not None:
            self._clear_pending_region()
            self._update_effect_preview()

        # 记录拖动起始状态
        self.drag_start_x = x
        self.drag_start_y = y
        self.drag_start_crop_x = self.crop_x
        self.drag_start_crop_y = self.crop_y
        self.drag_start_crop_size = self.crop_size

    def on_canvas_drag(self, event):
        """Canvas鼠标拖动事件"""
        if self.drag_mode is None or self.current_image is None:
            return

        dx = event.x - self.drag_start_x
        dy = event.y - self.drag_start_y

        img_w, img_h = self.current_image.size

        if self.drag_mode == 'move':
            # 移动裁剪框
            new_crop_x = self.drag_start_crop_x + dx / self.image_scale
            new_crop_y = self.drag_start_crop_y + dy / self.image_scale

            # 限制在图片范围内
            new_crop_x = max(0, min(new_crop_x, img_w - self.crop_size))
            new_crop_y = max(0, min(new_crop_y, img_h - self.crop_size))

            self.crop_x = int(new_crop_x)
            self.crop_y = int(new_crop_y)

        elif self.drag_mode == 'resize':
            # 调整裁剪框大小(保持正方形)
            # 根据角的位置计算新尺寸
            if self.drag_corner in (0, 1):
                # 上两角,调整高度向上
                delta = dy
            else:
                # 下两角,调整高度向下
                delta = dy

            # 取dx和dy中较大的变化作为尺寸变化(保持正方形)
            delta_size = int(max(abs(dx), abs(dy)) / self.image_scale)

            if self.drag_corner in (0, 2):
                # 左两角,从左边调整
                if dx < 0:
                    # 向左扩大
                    self.crop_x = max(0, self.drag_start_crop_x + dx / self.image_scale)
                    delta_size = int(abs(dx) / self.image_scale)
                else:
                    # 向右缩小
                    delta_size = -int(dx / self.image_scale)
            else:
                # 右两角,从右边调整
                if dx > 0:
                    delta_size = int(dx / self.image_scale)
                else:
                    delta_size = -int(abs(dx) / self.image_scale)

            # 限制最小尺寸(至少16x16)
            new_size = max(16, self.drag_start_crop_size + delta_size)

            # 更新位置和尺寸
            if self.drag_corner == 0:
                # 左上角:同时调整x,y和size
                self.crop_x = max(0, self.drag_start_crop_x + dx / self.image_scale)
                self.crop_y = max(0, self.drag_start_crop_y + dy / self.image_scale)
                self.crop_size = new_size
            elif self.drag_corner == 1:
                # 右上角:调整y和size
                self.crop_y = max(0, self.drag_start_crop_y + dy / self.image_scale)
                self.crop_size = new_size
            elif self.drag_corner == 2:
                # 左下角:调整x和size
                self.crop_x = max(0, self.drag_start_crop_x + dx / self.image_scale)
                self.crop_size = new_size
            elif self.drag_corner == 3:
                # 右下角:只调整size
                self.crop_size = new_size

            # 确保裁剪区域不超出图片边界
            self.crop_x = min(self.crop_x, img_w - self.crop_size)
            self.crop_y = min(self.crop_y, img_h - self.crop_size)

        # 转换为整数
        self.crop_x = int(self.crop_x)
        self.crop_y = int(self.crop_y)
        self.crop_size = int(self.crop_size)

        # 更新显示坐标和重新绘制
        self.display_crop_x = int(self.crop_x * self.image_scale + self.image_offset_x)
        self.display_crop_y = int(self.crop_y * self.image_scale + self.image_offset_y)
        self.display_crop_size = int(self.crop_size * self.image_scale)

        self._draw_crop_rect()
        self._update_effect_preview()

    def on_canvas_release(self, event):
        """Canvas鼠标释放事件"""
        self.drag_mode = None

    def _update_effect_preview(self):
        """单独更新效果预览"""
        if self.current_image is None:
            return

        # 使用用户选择的裁剪区域(与主预览保持一致)
        cropped = self._current_cropped_image()
        if cropped is None:
            return

        effect = cropped.resize(self.EFFECT_PREVIEW_SIZE, LANCZOS)

        # 待确认的透明区域用洋红色半透明高亮显示
        if self.pending_region_mask is not None:
            region = self.pending_region_mask.resize(
                self.EFFECT_PREVIEW_SIZE, NEAREST
            )
            tint = Image.new("RGBA", self.EFFECT_PREVIEW_SIZE, (255, 0, 128, 120))
            effect = Image.composite(tint, effect.convert("RGBA"), region)

        checker = self._create_checkerboard(self.EFFECT_PREVIEW_SIZE)
        checker.paste(effect, (0, 0), effect)

        self._effect_ctk_image = ctk.CTkImage(
            light_image=checker, size=self.EFFECT_PREVIEW_SIZE
        )
        self.effect_label.configure(image=self._effect_ctk_image, text="")

    # ======================== 选择透明区域(吸管) ========================

    def _current_crop_offset(self):
        """返回当前裁剪区域在 current_image 中的左上角偏移"""
        img_w, img_h = self.current_image.size
        if self.crop_size > 0:
            size = min(self.crop_size, img_w, img_h)
            x = max(0, min(self.crop_x, img_w - size))
            y = max(0, min(self.crop_y, img_h - size))
            return (x, y)
        # 未设置裁剪框时按居中裁剪计算
        dim = min(img_w, img_h)
        return ((img_w - dim) // 2, (img_h - dim) // 2)

    def _clear_pending_region(self):
        """清除待确认的透明区域选择(不刷新预览)"""
        self.pending_region_mask = None
        self.pending_region_offset = (0, 0)
        self.pending_seeds = []
        self.confirm_frame.pack_forget()

    def _exit_pick_mode(self):
        """退出吸管模式"""
        self.pick_mode = False
        self.tolerance_frame.pack_forget()
        self.effect_label.configure(cursor="")

    def _tolerance_value(self):
        """当前滑块设定的颜色容差"""
        return int(round(self.tolerance_slider.get()))

    def on_tolerance_change(self, value):
        """容差滑块事件:更新数值显示,并在已选区域上延迟重算"""
        self.tolerance_value_label.configure(text=str(int(round(float(value)))))
        if not self.pending_seeds:
            return
        # 拖动滑块会连续触发,做 120ms 防抖后再重算
        if self._tolerance_job is not None:
            self.after_cancel(self._tolerance_job)
        self._tolerance_job = self.after(120, self._recompute_pending_region)

    def _recompute_pending_region(self):
        """用当前容差重新计算待确认区域(所有已选区域取并集)"""
        self._tolerance_job = None
        if not self.pending_seeds or self.current_image is None:
            return

        cropped = self._current_cropped_image()
        if cropped is None:
            return

        mask = None
        try:
            for seed in self.pending_seeds:
                region = self.generator.build_transparent_region(
                    cropped, seed, self._tolerance_value()
                )
                # 多次选择取并集(加选)
                mask = region if mask is None else ImageChops.lighter(mask, region)
        except Exception:
            return

        if mask is None:
            return
        self.pending_region_mask = mask
        self._update_effect_preview()

    def on_pick_transparent(self):
        """选择透明区域按钮事件:进入吸管模式,等待点击效果预览"""
        if self.current_image is None:
            messagebox.showwarning("未载入图片", "请先选择一张图片")
            return

        self._clear_pending_region()
        self.pick_mode = True
        self.tolerance_frame.pack(fill="x", pady=(0, 8))
        self.effect_label.configure(cursor="crosshair")
        self._update_effect_preview()
        self.set_status(
            "吸管模式:点击预览中的区域(可多次点击加选)",
            self.COLOR_PROCESS
        )

    def on_effect_click(self, event):
        """效果预览点击事件:取点击处颜色扩散出连通区域,并累加到已有选择"""
        if not self.pick_mode or self.current_image is None:
            return

        cropped = self._current_cropped_image()
        if cropped is None:
            return

        # 1. 控件坐标 -> 效果预览坐标(图像在标签内居中显示)
        pw, ph = self.EFFECT_PREVIEW_SIZE
        px = event.x - max(0, (self.effect_label.winfo_width() - pw) // 2)
        py = event.y - max(0, (self.effect_label.winfo_height() - ph) // 2)
        if not (0 <= px < pw and 0 <= py < ph):
            return

        # 2. 效果预览坐标 -> 裁剪图坐标
        cw, ch = cropped.size
        ix = min(cw - 1, int(px * cw / pw))
        iy = min(ch - 1, int(py * ch / ph))

        self.set_status("正在计算透明区域...", self.COLOR_PROCESS)
        self.update_idletasks()

        try:
            region = self.generator.build_transparent_region(
                cropped, (ix, iy), self._tolerance_value()
            )
        except Exception as e:
            messagebox.showerror("选择失败", f"无法计算透明区域:\n{e}")
            self.set_status(f"错误:{e}", self.COLOR_ERROR)
            return

        # 3. 累加选区:多次点击取并集(加选)
        if (self.pending_region_mask is not None
                and self.pending_region_mask.size == region.size):
            self.pending_seeds.append((ix, iy))
            self.pending_region_mask = ImageChops.lighter(
                self.pending_region_mask, region
            )
        else:
            # 首次选择,或裁剪区域已变化:从当前点为起点重新开始
            self.pending_seeds = [(ix, iy)]
            self.pending_region_mask = region

        self.pending_region_offset = self._current_crop_offset()
        self.confirm_frame.pack(fill="x")
        self._update_effect_preview()
        self.set_status(
            f"已选 {len(self.pending_seeds)} 处区域(可继续点击加选),点击「确定应用」使其透明",
            self.COLOR_SUCCESS
        )

    def on_confirm_region(self):
        """确定应用按钮事件:把选中区域设为完全透明"""
        if self.current_image is None or self.pending_region_mask is None:
            return

        try:
            self.current_image = self.generator.apply_region_alpha(
                self.current_image,
                self.pending_region_mask,
                self.pending_region_offset
            )
            self._clear_pending_region()
            self._exit_pick_mode()
            self._update_previews()
            self.set_status("已将该区域设为透明", self.COLOR_SUCCESS)
        except Exception as e:
            messagebox.showerror("处理失败", f"设置透明区域失败:\n{e}")
            self.set_status(f"错误:{e}", self.COLOR_ERROR)

    def on_cancel_region(self):
        """取消按钮事件:放弃本次区域选择"""
        self._clear_pending_region()
        self._exit_pick_mode()
        self._update_effect_preview()
        self.set_status("已取消选择", self.COLOR_READY)

    def on_window_resize(self, event):
        """窗口大小改变事件"""
        # 推广信息随窗口宽度换行,避免文字被裁切
        if hasattr(self, "promo_label"):
            self.promo_label.configure(wraplength=max(400, event.width - 60))
        # 延迟更新,避免频繁重绘
        self.after(100, self._delayed_resize_update)

    def _delayed_resize_update(self):
        """延迟更新Canvas预览"""
        if self.current_image is not None:
            self._update_canvas_preview()

    def on_reset_crop(self):
        """重置裁剪区域按钮事件"""
        if self.current_image is None:
            return

        # 重置为居中裁剪
        img_w, img_h = self.current_image.size
        min_dim = min(img_w, img_h)
        self.crop_size = min_dim
        self.crop_x = (img_w - min_dim) // 2
        self.crop_y = (img_h - min_dim) // 2

        # 裁剪区域变化,待确认的透明区域失效
        self._clear_pending_region()

        # 更新预览
        self._update_canvas_preview()
        self._update_effect_preview()
        self.set_status("裁剪区域已重置", self.COLOR_READY)

    def _apply_crop_to_image(self):
        """把当前裁剪区域写回 current_image,并把裁剪框重置为整张图"""
        cropped = self._current_cropped_image()
        self.current_image = cropped
        # 裁剪框重置为整张图片(正方形)
        img_w, img_h = cropped.size
        self.crop_size = min(img_w, img_h)
        self.crop_x = (img_w - self.crop_size) // 2
        self.crop_y = (img_h - self.crop_size) // 2
        return cropped

    def on_apply_crop(self):
        """应用裁剪按钮事件:裁剪并写回图片,不生成 ICO"""
        if self.current_image is None:
            messagebox.showwarning("未载入图片", "请先选择一张图片")
            return

        try:
            cropped = self._apply_crop_to_image()
            # 更新原图与效果预览
            self._update_previews()
            self.set_status(
                f"裁剪已应用:{cropped.width}x{cropped.height}",
                self.COLOR_SUCCESS
            )
        except Exception as e:
            messagebox.showerror("裁剪失败", f"应用裁剪失败:\n{e}")
            self.set_status(f"错误:{e}", self.COLOR_ERROR)

    def on_apply_rounded_alpha(self):
        """添加圆角Alpha按钮事件:先应用裁剪,再叠加圆角透明通道"""
        if self.current_image is None:
            messagebox.showwarning("未载入图片", "请先选择一张图片")
            return

        try:
            # 1. 先应用裁剪,保证作用于正方形图片
            cropped = self._apply_crop_to_image()
            # 2. 叠加圆角 Alpha 通道
            self.current_image = self.generator.apply_rounded_alpha(cropped)
            # 3. 更新预览(效果预览会透过棋盘格显示圆角透明区域)
            self._update_previews()
            self.set_status(
                f"已添加圆角 Alpha:{cropped.width}x{cropped.height}",
                self.COLOR_SUCCESS
            )
        except Exception as e:
            messagebox.showerror("处理失败", f"添加圆角 Alpha 失败:\n{e}")
            self.set_status(f"错误:{e}", self.COLOR_ERROR)

    # ======================== 事件处理 ========================

    def on_select_image(self):
        """选择图片按钮事件:调用系统文件选择对话框"""
        file_path = filedialog.askopenfilename(
            title="选择图片",
            filetypes=[("图片文件", "*.png *.jpg *.jpeg *.bmp")]
        )
        if file_path:
            self.load_image_file(file_path)

    def on_generate_ico(self):
        """生成 ICO 按钮事件:检查图片 -> 另存为 -> 生成"""
        # 检查是否已载入图片
        if self.current_image is None or self.current_image_path is None:
            messagebox.showwarning("未载入图片", "请先选择一张图片")
            return

        # 构造默认输出文件名(与原图同名,后缀 .ico)
        base = os.path.splitext(os.path.basename(self.current_image_path))[0]
        output_path = filedialog.asksaveasfilename(
            title="保存 ICO 文件",
            defaultextension=".ico",
            initialfile=f"{base}.ico",
            filetypes=[("ICO 文件", "*.ico")]
        )
        if not output_path:
            # 用户取消保存
            return

        # 设置处理中状态并立即刷新界面
        self.set_status("正在处理...", self.COLOR_PROCESS)
        self.update_idletasks()

        try:
            # 使用当前裁剪区域(或居中裁剪)生成 ICO
            # current_image 已包含"应用裁剪"和"圆角 Alpha"的处理结果
            img = self._current_cropped_image()
            if img is None:
                messagebox.showwarning("未载入图片", "请先选择一张图片")
                return

            # 调用图像处理器生成 ICO
            sizes = self.generator.generate_ico(img, output_path)
            # 拼接尺寸信息用于状态显示
            size_str = ", ".join(f"{w}x{h}" for w, h in sizes)
            self.set_status(
                f"保存成功:{output_path} (尺寸:{size_str})",
                self.COLOR_SUCCESS
            )
        except PermissionError:
            # 文件被占用(如正在其他程序中打开)
            messagebox.showerror(
                "文件被占用",
                "文件正在被使用,请关闭后重试"
            )
            self.set_status("错误:文件正在被使用", self.COLOR_ERROR)
        except Exception as e:
            # 其他异常:捕获并显示在状态栏,不让程序崩溃
            messagebox.showerror("生成失败", f"生成 ICO 失败:\n{e}")
            self.set_status(f"错误:{e}", self.COLOR_ERROR)

    def on_drop(self, event):
        """
        拖拽载入事件
        tkinterdnd2 传递的路径含空格时会被花括号 {} 包裹,需做解析
        """
        file_path = event.data.strip()
        # 处理花括号包裹的路径(Windows 路径含空格时)
        if file_path.startswith('{'):
            end = file_path.find('}')
            if end != -1:
                file_path = file_path[1:end]
        # 多文件拖入时只取第一个
        if file_path:
            self.load_image_file(file_path)


# ============================================================================
# 程序入口
# ============================================================================
def main():
    """程序入口:创建应用实例并启动主循环"""
    app = IconGeneratorApp()
    app.mainloop()


if __name__ == "__main__":
    main()
