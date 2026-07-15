"""
PNG 转 Windows ICO 图标生成器
==============================
将 PNG/JPG/JPEG/BMP 图片转换为 Windows 标准 ICO 图标文件的单文件桌面应用。

核心功能:
  - 智能居中裁剪(将非正方形图片裁剪为正方形)
  - 多尺寸打包(16x16 ~ 256x256 标准尺寸合并为单一 ICO)
  - 透明通道保留(完美处理 PNG Alpha 通道)
  - 拖拽载入与点击选择(所见即所得预览)

代码结构:
  - IconGenerator     : 图像处理类(裁剪/缩放/ICO 生成)
  - IconGeneratorApp  : UI 类(基于 CustomTkinter)
  - main()            : 程序入口
"""

import os
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageTk

# ============================================================================
# LANCZOS 重采样常量(兼容 Pillow 9.x 与 10.x)
# Pillow 10.0.0 移除了 Image.LANCZOS 顶层常量,改为 Image.Resampling.LANCZOS
# 这里做兼容处理,确保不同版本均可正常运行
# ============================================================================
try:
    LANCZOS = Image.Resampling.LANCZOS
except AttributeError:
    LANCZOS = Image.LANCZOS

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

    def generate_ico(self, input_path, output_path, crop_region=None):
        """
        完整 ICO 生成流程:载入 -> 裁剪 -> 多尺寸 -> 保存为 ICO
        参数:
          input_path  : 输入图片路径
          output_path : 输出 ICO 文件路径
          crop_region : 自定义裁剪区域 (x, y, size)，None则使用居中裁剪
        返回:
          list[tuple[int, int]] 实际生成的尺寸列表
        """
        # 1. 载入并预处理
        img = self.load_image(input_path)
        # 2. 裁剪为正方形(自定义或居中)
        if crop_region is not None:
            x, y, size = crop_region
            img_cropped = self.custom_crop_square(img, x, y, size)
        else:
            img_cropped = self.center_crop_square(img)
        # 3. 生成多尺寸列表
        icon_images = self.generate_icon_sizes(img_cropped)

        # 兜底:若所有尺寸都被跳过(理论上不会,因为最小 16x16),使用裁剪图
        if not icon_images:
            icon_images = [img_cropped]

        # 4. 使用 Pillow 多图层打包保存为 ICO
        #    重要:Pillow 的 ICO 插件以第一个图像的尺寸作为上限,
        #    会跳过所有大于第一个图像尺寸的目标尺寸。
        #    因此必须按尺寸降序排列,让最大的图像排在第一位,
        #    这样所有较小尺寸才不会被跳过。
        icon_images.sort(key=lambda im: im.size[0], reverse=True)
        #    第一个图像作为基础,其余通过 append_images 追加
        #    sizes 参数显式声明每个图层的尺寸
        icon_images[0].save(
            output_path,
            format='ICO',
            append_images=icon_images[1:],
            sizes=[(img.width, img.height) for img in icon_images]
        )

        return [(img.width, img.height) for img in icon_images]

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

    def __init__(self):
        super().__init__()

        # ===== 全局主题配置(现代化暗色主题 + 蓝色配色)=====
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        # ===== 窗口配置 =====
        self.title("PNG 转 ICO 图标生成器")
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
        """构建标题区:显示程序标题"""
        self.title_label = ctk.CTkLabel(
            self,
            text="PNG 转 ICO 图标生成器",
            font=ctk.CTkFont(size=22, weight="bold")
        )
        self.title_label.pack(pady=(15, 5))

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

    def _build_action_area(self):
        """构建操作区:三个按钮(选择图片 / 重置裁剪 / 生成 ICO 文件)"""
        self.action_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.action_frame.pack(fill="x", padx=20, pady=(0, 10))

        # "选择图片" 按钮
        self.select_btn = ctk.CTkButton(
            self.action_frame, text="选择图片",
            font=ctk.CTkFont(size=15, weight="bold"),
            height=40, command=self.on_select_image
        )
        self.select_btn.pack(side="left", expand=True, fill="x", padx=(0, 8))

        # "重置裁剪" 按钮
        self.reset_crop_btn = ctk.CTkButton(
            self.action_frame, text="重置裁剪",
            font=ctk.CTkFont(size=15, weight="bold"),
            height=40, command=self.on_reset_crop,
            fg_color="#6C757D", hover_color="#5A6268"
        )
        self.reset_crop_btn.pack(side="left", expand=True, fill="x", padx=(0, 8))

        # "生成 ICO 文件" 按钮
        self.generate_btn = ctk.CTkButton(
            self.action_frame, text="生成 ICO 文件",
            font=ctk.CTkFont(size=15, weight="bold"),
            height=40, command=self.on_generate_ico
        )
        self.generate_btn.pack(side="right", expand=True, fill="x", padx=(8, 0))

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

    def _update_previews(self):
        """更新原图预览与效果预览(256x256 带透明网格)"""
        if self.current_image is None:
            return

        # ---------- 原图预览:使用Canvas显示图片和裁剪框----------
        self._update_canvas_preview()

        # ---------- 效果预览:裁剪 -> 256x256 -> 叠加透明网格 ----------
        # 1. 使用用户选择的裁剪区域或默认居中裁剪
        if self.crop_size > 0:
            cropped = self.generator.custom_crop_square(
                self.current_image, self.crop_x, self.crop_y, self.crop_size
            )
        else:
            cropped = self.generator.center_crop_square(self.current_image)
        # 2. 缩放至 256x256
        effect = cropped.resize(self.EFFECT_PREVIEW_SIZE, LANCZOS)
        # 3. 创建棋盘格背景(用于直观展示透明区域)
        checker = self._create_checkerboard(self.EFFECT_PREVIEW_SIZE)
        # 4. 将效果图叠加到棋盘格上(使用 effect 的 Alpha 通道作为 mask)
        checker.paste(effect, (0, 0), effect)
        # 5. 包装为 CTkImage 并显示
        self._effect_ctk_image = ctk.CTkImage(
            light_image=checker, size=self.EFFECT_PREVIEW_SIZE
        )
        self.effect_label.configure(image=self._effect_ctk_image, text="")

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

        # 使用用户选择的裁剪区域
        if self.crop_size > 0:
            cropped = self.generator.custom_crop_square(
                self.current_image, self.crop_x, self.crop_y, self.crop_size
            )
        else:
            cropped = self.generator.center_crop_square(self.current_image)

        effect = cropped.resize(self.EFFECT_PREVIEW_SIZE, LANCZOS)
        checker = self._create_checkerboard(self.EFFECT_PREVIEW_SIZE)
        checker.paste(effect, (0, 0), effect)

        self._effect_ctk_image = ctk.CTkImage(
            light_image=checker, size=self.EFFECT_PREVIEW_SIZE
        )
        self.effect_label.configure(image=self._effect_ctk_image, text="")

    def on_window_resize(self, event):
        """窗口大小改变事件"""
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

        # 更新预览
        self._update_canvas_preview()
        self._update_effect_preview()
        self.set_status("裁剪区域已重置", self.COLOR_READY)

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
            # 准备裁剪区域参数
            crop_region = None
            if self.crop_size > 0:
                crop_region = (self.crop_x, self.crop_y, self.crop_size)
            
            # 调用图像处理器生成 ICO
            sizes = self.generator.generate_ico(
                self.current_image_path, output_path, crop_region
            )
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
