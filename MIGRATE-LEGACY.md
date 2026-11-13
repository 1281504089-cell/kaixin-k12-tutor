# 已安装电脑的一次性更新器迁移

旧兼容包只补运行环境，不会替换旧更新器，所以装过旧兼容包的电脑仍需本次迁移一次。没有装过旧补丁的旧电脑也直接用本次迁移包，不必先装旧补丁。新电脑请用[最新版完整版](INSTALL-LATEST.md)。

- [Windows x64 迁移包](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/student-20261114-unified/Kaixin-Launcher-Migration-d3214451efd0-windows-x64-Setup.exe)
- [Intel Mac 迁移包](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/student-20261114-unified/Kaixin-Launcher-Migration-d3214451efd0-macos-x64.zip)
- [Apple 芯片 Mac 迁移包](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/student-20261114-unified/Kaixin-Launcher-Migration-d3214451efd0-macos-arm64.zip)

先正常退出软件，保留学习目录、设置和 Key。Windows 运行 Setup，它会检查已有固定安装位置并保留旧程序回退目录。Mac 解压 ZIP，保留旧 app 作为回退，再把同名 app 替换到原“应用程序”位置；可能需要完成系统首次来源确认。不要删除 Application Support 或本机学习目录。

从原固定入口重新打开，点“核心 → 检查更新”或“设置 → 关于 → 检查更新”。已有相容运行环境时选用约 45 MB 核心；最早旧底座缺少后来原生组件时，会在软件内自动下载约 1.17–1.25 GB 兼容资源一次。无需运行脚本或挑选 JSON。

迁移器提示仍在运行时，先退出再重试。若找不到已有完整运行环境，保留原目录联系维护者，不要删除资料或改环境编号。后续相容学习核心和界面更新直接检查更新。当前机制不能自动替换 Electron 本身；以后外壳改动仍须判断承载方式，不能只发核心就宣称外壳也已升级。

U 盘分为“从零安装”“装过前一个补丁”“旧版从未打补丁”三个入口，各自提供三系统文件。按电脑情况任选一类，不按顺序都装。

原生 CI 使用隔离合成资料，不代表已在每台用户电脑上试过。真实付费 API、实体摄像头及麦克风未在本批自动验收中调用；已有功能保留。

