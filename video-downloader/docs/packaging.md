# 打包为可执行程序

本项目使用 PyInstaller 的 `onedir` 模式打包。配置文件位于
[`packaging/VideoDownloader.spec`](../packaging/VideoDownloader.spec)，构建依赖单独列在
[`requirements-build.txt`](../requirements-build.txt) 中，不会混入应用运行依赖。
默认图标资源位于 [`video_downloader/assets/`](../video_downloader/assets/)；替换图标时保留文件名和格式即可：

- `video_downloader.png`：Tkinter 窗口图标，打包时随程序一并包含。
- `video_downloader.ico`：Windows 可执行文件图标。
- `video_downloader.icns`：macOS 应用图标。
- `video_downloader.svg`：可编辑的矢量源文件；更换设计后请同步导出 PNG、ICO 和 ICNS。

Linux 下程序窗口会显示 PNG 图标；ELF 可执行文件自身通常不携带桌面图标，桌面快捷方式需要由桌面环境的 `.desktop` 启动器配置。

## 在 Linux 上构建

在项目根目录执行：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-build.txt
.venv/bin/python -m PyInstaller \
  --clean \
  --noconfirm \
  --distpath dist \
  --workpath build/work \
  packaging/VideoDownloader.spec
```

构建结果位于 `dist/VideoDownloader/`，运行其中的 `VideoDownloader` 文件。发布时需要分发整个目录，而不只是可执行文件。

后续重复构建时，在同一虚拟环境中再次运行 PyInstaller 命令即可。若要从干净环境复现构建，可按上面的步骤新建虚拟环境并安装锁定的应用及构建依赖；`requirements-build.txt` 同时固定了 PyInstaller 及其构建工具依赖版本。

## 跨平台注意事项

- PyInstaller 不负责跨操作系统交叉编译。Windows、macOS 和 Linux 版本需分别在各自系统上构建。
- 构建使用当前 Python 环境和系统图形库；Linux 产物应在目标 Linux 发行版上测试，目标系统仍可能需要兼容的图形/系统库。
- `.spec` 配置固定了应用入口、GUI（不显示控制台）和输出名称。PyInstaller 版本由 `requirements-build.txt` 固定，便于重复构建。
