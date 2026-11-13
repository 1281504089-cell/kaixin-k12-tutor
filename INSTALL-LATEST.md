# 新电脑首次安装

当前完整安装版：**2026-11-13 sync2（1.7.1）**。已包含本轮应用代码、运行环境和 136 册教材；装好后不需要再运行 `.command` 或另装小补丁。

根据电脑选择下面一组文件，**同一组必须全部下载，保留原名并放在本机同一个文件夹**。不要下载发布页底部的 Source code。建议预留 40 GB 临时空间。

## Apple 芯片 Mac（M 系列）

- [主文件 .dmg](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/student-20261113-sync2/Kaixin-Super-Scholar-MacOS-Apple-Silicon-v1.7.1-04276f68a-arm64-part.dmg)
- [分卷 002.dmgpart](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/student-20261113-sync2/Kaixin-Super-Scholar-MacOS-Apple-Silicon-v1.7.1-04276f68a-arm64-part.002.dmgpart)
- [分卷 003.dmgpart](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/student-20261113-sync2/Kaixin-Super-Scholar-MacOS-Apple-Silicon-v1.7.1-04276f68a-arm64-part.003.dmgpart)
- [分卷 004.dmgpart](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/student-20261113-sync2/Kaixin-Super-Scholar-MacOS-Apple-Silicon-v1.7.1-04276f68a-arm64-part.004.dmgpart)

需要 macOS 13 或以上。四个文件下齐后，只打开主文件 `.dmg`，把“开心动力超级学霸”拖进“应用程序”，再从“应用程序”打开。其余 `.dmgpart` 保持原位，不需要逐个打开。

## Intel Mac

- [主文件 .dmg](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/student-20261113-sync2/Kaixin-Super-Scholar-MacOS-Intel-v1.7.1-04276f68a-x64-part.dmg)
- [分卷 002.dmgpart](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/student-20261113-sync2/Kaixin-Super-Scholar-MacOS-Intel-v1.7.1-04276f68a-x64-part.002.dmgpart)
- [分卷 003.dmgpart](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/student-20261113-sync2/Kaixin-Super-Scholar-MacOS-Intel-v1.7.1-04276f68a-x64-part.003.dmgpart)
- [分卷 004.dmgpart](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/student-20261113-sync2/Kaixin-Super-Scholar-MacOS-Intel-v1.7.1-04276f68a-x64-part.004.dmgpart)

需要 macOS 13 或以上。四个文件下齐后，只打开主文件 `.dmg`，把“开心动力超级学霸”拖进“应用程序”，再从“应用程序”打开。其余 `.dmgpart` 保持原位，不需要逐个打开。

## Windows 64 位

- [安装程序 Setup.exe](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/student-20261113-sync2/Kaixin-Super-Scholar-Windows-v1.7.1-Setup.exe)
- [Runtime.001](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/student-20261113-sync2/Kaixin-Super-Scholar-Windows-v1.7.1-Runtime.001)
- [Runtime.002](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/student-20261113-sync2/Kaixin-Super-Scholar-Windows-v1.7.1-Runtime.002)
- [Runtime.003](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/student-20261113-sync2/Kaixin-Super-Scholar-Windows-v1.7.1-Runtime.003)
- [Runtime.004](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/student-20261113-sync2/Kaixin-Super-Scholar-Windows-v1.7.1-Runtime.004)

五个文件下齐后，只运行 `Setup.exe`，按向导安装；安装器会校验其余四个 Runtime 分卷。不要单独解压或改名分卷。

## 第一次打开

首次启动会在本机展开环境并导入教材，请等待完成。进入设置填写自己的聊天 API；摄像头、麦克风和共享屏幕按需要授权。在教材库核对能找到 136 册教材；在“关于”核对运行核心编号包含 `20261113-sync2`，产品主版本仍为 `1.7.1`。

Mac 如果提示“身份不明的开发者”，先确认文件来自本仓库，再到“系统设置 → 隐私与安全性”点击对应程序的“仍要打开”。这是系统首次来源确认，不需要运行额外补丁。[Apple 官方说明](https://support.apple.com/zh-cn/102445)

如果提示缺少分卷或镜像无法识别，先检查这组文件是否全部下载完成、放在同一文件夹且未被改名。不要把不同版本或不同芯片的文件混放。

以后的新版通过软件中的“核心 → 检查更新”或“设置 → 关于 → 检查更新”获取；检查和下载需要能够访问 GitHub。仅上传源码不会更新已安装客户端，维护者还需发布对应系统的签名更新包。

[回到 GitHub 完整版发布页](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/latest)
