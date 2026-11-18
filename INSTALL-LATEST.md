# 新电脑首次安装

本次版本：**`student-20261117-k12-7`（1.7.1）**，学习源码 `fbb301fd21cf2169f834e0b548d56d201cc98365`。本批已完成三系统同批原生新装、当前和旧启动器检查更新验收；正式状态以[最新 Release](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/latest)、PUBLICATION-RECEIPT 和 CURRENT 为准。本机正式入口4→7及数据保留已通过，详见 LOCAL-ACTUAL-UPDATE-20261118.json。U盘仍保留旧4，等待下一整合批一次替换。

本批新增 **698 份理科原生 PDF、3,888 页，对应 6,915 条题源记录**，保留原图、公式与排版；原稿以整页或单元呈现，不宣称全部是精准单题裁图。正文先显示，题页异步加载，浅蓝色引用支持打开对应原页。既有294条预制题图、136册教材、12,101条有效教材参考和学习流程保留。本批同时修复更新器退出等待问题，不改老师规则、题干、模型输入或输出预算。[本批说明及验证边界](RELEASE-NOTES.md)。

根据电脑选择本批下面一组文件，**同一组必须全部下载，保留原名并放在本机同一个文件夹**。不要下载页面底部的 Source code，也不要把旧版分卷混入本批文件夹。建议预留 40 GB 临时空间。

## Apple 芯片 Mac（M 系列）

- [主文件 .dmg](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/student-20261117-k12-7/Kaixin-Super-Scholar-MacOS-Apple-Silicon-v1.7.1-20261117-k12-7-part.dmg)
- [分卷 002.dmgpart](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/student-20261117-k12-7/Kaixin-Super-Scholar-MacOS-Apple-Silicon-v1.7.1-20261117-k12-7-part.002.dmgpart)
- [分卷 003.dmgpart](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/student-20261117-k12-7/Kaixin-Super-Scholar-MacOS-Apple-Silicon-v1.7.1-20261117-k12-7-part.003.dmgpart)
- [分卷 004.dmgpart](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/student-20261117-k12-7/Kaixin-Super-Scholar-MacOS-Apple-Silicon-v1.7.1-20261117-k12-7-part.004.dmgpart)

需要 macOS 13 或以上。四个文件下齐后，只打开主文件 `.dmg`，把“开心动力超级学霸”拖进“应用程序”，再从“应用程序”打开。其余 `.dmgpart` 保持原位，不需要逐个打开。

## Intel Mac

- [主文件 .dmg](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/student-20261117-k12-7/Kaixin-Super-Scholar-MacOS-Intel-v1.7.1-20261117-k12-7-part.dmg)
- [分卷 002.dmgpart](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/student-20261117-k12-7/Kaixin-Super-Scholar-MacOS-Intel-v1.7.1-20261117-k12-7-part.002.dmgpart)
- [分卷 003.dmgpart](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/student-20261117-k12-7/Kaixin-Super-Scholar-MacOS-Intel-v1.7.1-20261117-k12-7-part.003.dmgpart)
- [分卷 004.dmgpart](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/student-20261117-k12-7/Kaixin-Super-Scholar-MacOS-Intel-v1.7.1-20261117-k12-7-part.004.dmgpart)
- [分卷 005.dmgpart](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/student-20261117-k12-7/Kaixin-Super-Scholar-MacOS-Intel-v1.7.1-20261117-k12-7-part.005.dmgpart)

需要 macOS 13 或以上。五个文件下齐后，只打开主文件 `.dmg`，把“开心动力超级学霸”拖进“应用程序”，再从“应用程序”打开。其余 `.dmgpart` 保持原位，不需要逐个打开。

## Windows 64 位

- [安装程序 Setup.exe](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/student-20261117-k12-7/Kaixin-Super-Scholar-Windows-v1.7.1-Setup.exe)
- [Runtime.001](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/student-20261117-k12-7/Kaixin-Super-Scholar-Windows-v1.7.1-Runtime.001)
- [Runtime.002](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/student-20261117-k12-7/Kaixin-Super-Scholar-Windows-v1.7.1-Runtime.002)
- [Runtime.003](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/student-20261117-k12-7/Kaixin-Super-Scholar-Windows-v1.7.1-Runtime.003)
- [Runtime.004](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/student-20261117-k12-7/Kaixin-Super-Scholar-Windows-v1.7.1-Runtime.004)

五个文件下齐后，只运行 `Setup.exe`，按向导安装；安装器会校验其余四个 Runtime 分卷。不要单独解压或改名分卷。

## 第一次打开

首次启动会在本机展开环境并导入教材，请等待完成。进入设置填写自己的聊天 API；摄像头、麦克风和共享屏幕按需要授权。在教材库核对能找到 136 册教材。产品主版本仍为 `1.7.1`；后续从“设置 → 关于”或“核心”点击“检查更新”，不把 `.command` 或手动小补丁作为日常流程。正常更新入口以已正式发布的版本为准；本说明不代替发布回执。

本批核心837,565,146字节（约799MiB），**不是整个首次安装包大小**；理科原生题页与清单新增295,359,867字节。既有预制题图包13,579,283字节也不是整个核心大小。核心仍包含题库，跨不同核心包去重尚未实现；缺少兼容运行环境的旧电脑还可能下载一次较大的环境。具体大小以窗口和同批验证文件为准。正常升级保留聊天、资料、阅读记录、API Key 和设置，无需删除学习目录或卸载重装。

Mac 如果提示“身份不明的开发者”，先确认文件来自本仓库，再到“系统设置 → 隐私与安全性”点击对应程序的“仍要打开”。这是系统首次来源确认，不需要运行额外补丁。[Apple 官方说明](https://support.apple.com/zh-cn/102445)

如果提示缺少分卷或镜像无法识别，先检查这组文件是否全部下载完成、放在同一文件夹且未被改名。不要把不同版本或不同芯片的文件混放。

以后的新版通过软件中的“核心 → 检查更新”或“设置 → 关于 → 检查更新”获取；检查和下载需要能够访问 GitHub。仅上传源码不会更新已安装客户端，维护者还需发布对应系统的签名更新包。

U盘交付另行合成为Windows完整ZIP和两份独立普通DMG，并配三份离线环境更新。是否完成介质替换以同批USB-DELIVERY-RECEIPT为准，不把GitHub发布等同于U盘已更新。完整构建号而非v1.7.1用于区分批次；正常升级始终优先软件内“检查更新”，不要串装历史补丁。

[本批文件页 k12-7](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/tag/student-20261117-k12-7) · [上一正式版 k12-4](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/tag/student-20261117-k12-4)
