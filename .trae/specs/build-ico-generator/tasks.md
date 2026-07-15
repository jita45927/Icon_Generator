# Tasks

- [x] Task 1: 创建项目依赖文件 requirements.txt
  - [x] SubTask 1.1: 列出依赖:customtkinter、Pillow、tkinterdnd2
  - [x] SubTask 1.2: 注明 Python 版本要求

- [x] Task 2: 实现图像处理类(IconGenerator)
  - [x] SubTask 2.1: 实现载入图像并转换为 RGBA 模式
  - [x] SubTask 2.2: 实现超大图片保护(>5000px 等比缩小至 1024px)
  - [x] SubTask 2.3: 实现智能居中裁剪为正方形
  - [x] SubTask 2.4: 实现多尺寸生成(16/32/48/64/128/256),使用 LANCZOS 缩放,跳过原图小于的尺寸
  - [x] SubTask 2.5: 实现保存为 ICO 文件(Pillow 多图层打包)
  - [x] SubTask 2.6: 实现极小图片检测与提示逻辑

- [x] Task 3: 实现 UI 类(IconGeneratorApp,基于 CustomTkinter)
  - [x] SubTask 3.1: 创建主窗口(800x600,可缩放,现代化主题)
  - [x] SubTask 3.2: 实现拖拽区/预览区布局(虚线边框占位提示、原图预览、效果预览带透明网格背景)
  - [x] SubTask 3.3: 实现操作区(选择图片按钮、生成 ICO 文件按钮)
  - [x] SubTask 3.4: 实现状态栏(就绪/正在处理/保存成功/错误提示)
  - [x] SubTask 3.5: 绑定"选择图片"按钮事件(调用系统文件对话框,过滤图片格式)
  - [x] SubTask 3.6: 绑定"生成 ICO"按钮事件(调用另存为对话框,触发图像处理类生成)
  - [x] SubTask 3.7: 实现拖拽文件功能(tkinterdnd2,提供备选方案)
  - [x] SubTask 3.8: 实现格式校验与非图片文件友好提示
  - [x] SubTask 3.9: 实现异常处理(文件占用、极小图片等)

- [x] Task 4: 实现程序入口与主循环
  - [x] SubTask 4.1: 创建 main 入口,实例化 UI 类并启动主循环

- [x] Task 5: 验证与测试
  - [x] SubTask 5.1: 验证程序能正常启动并显示界面
  - [x] SubTask 5.2: 验证拖拽载入与点击载入功能
  - [x] SubTask 5.3: 验证非正方形图片裁剪效果
  - [x] SubTask 5.4: 验证生成的 ICO 文件包含正确尺寸且透明通道保留
  - [x] SubTask 5.5: 验证异常处理(文件占用、极小图片)

# Task Dependencies
- [Task 2] 和 [Task 3] 可并行开发(图像处理类与 UI 类相互独立)
- [Task 4] 依赖 [Task 2] 和 [Task 3]
- [Task 5] 依赖 [Task 4]
- [Task 1] 独立,可最先执行
