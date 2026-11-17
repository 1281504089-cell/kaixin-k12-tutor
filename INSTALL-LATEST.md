# 新电脑首次安装

本次版本：**`student-20261117-k12-2`（1.7.1）**，学习源码 `f6bc7a8f8c104b29ec51e57649f9336fdd1b99d9`。最终核心与三系统同批原生新装、当前和旧启动器检查更新验收已通过；正式状态以[最新 Release](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/latest)、PUBLICATION-RECEIPT 和 CURRENT 为准。本机真实升级单独记录。

本批增加 294 道完整题目图（26 份题源、82 个不同原图），继续保留教材库/题库两分页、学科过滤、12,101 条默认教材参考、完整题源跳转和 136 册教材，以及既有语音、高拍仪、阅读、笔记、资料、历史与更新功能。显示检查不代表全部题目完成学术审核；17 条题源精确隔离后，有效 20,845 条可读题源单位、18,890 条结构练习候选。[本批说明及验证边界](RELEASE-NOTES.md)。

根据电脑选择本批下面一组文件，**同一组必须全部下载，保留原名并放在本机同一个文件夹**。不要下载页面底部的 Source code，也不要把旧版分卷混入本批文件夹。建议预留 40 GB 临时空间。

## Apple 芯片 Mac（M 系列）

- [主文件 .dmg](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/student-20261117-k12-2/Kaixin-Super-Scholar-MacOS-Apple-Silicon-v1.7.1-20261117-k12-2-part.dmg)
- [分卷 002.dmgpart](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/student-20261117-k12-2/Kaixin-Super-Scholar-MacOS-Apple-Silicon-v1.7.1-20261117-k12-2-part.002.dmgpart)
- [分卷 003.dmgpart](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/student-20261117-k12-2/Kaixin-Super-Scholar-MacOS-Apple-Silicon-v1.7.1-20261117-k12-2-part.003.dmgpart)
- [分卷 004.dmgpart](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/student-20261117-k12-2/Kaixin-Super-Scholar-MacOS-Apple-Silicon-v1.7.1-20261117-k12-2-part.004.dmgpart)

需要 macOS 13 或以上。四个文件下齐后，只打开主文件 `.dmg`，把“开心动力超级学霸”拖进“应用程序”，再从“应用程序”打开。其余 `.dmgpart` 保持原位，不需要逐个打开。

## Intel Mac

- [主文件 .dmg](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/student-20261117-k12-2/Kaixin-Super-Scholar-MacOS-Intel-v1.7.1-20261117-k12-2-part.dmg)
- [分卷 002.dmgpart](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/student-20261117-k12-2/Kaixin-Super-Scholar-MacOS-Intel-v1.7.1-20261117-k12-2-part.002.dmgpart)
- [分卷 003.dmgpart](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/student-20261117-k12-2/Kaixin-Super-Scholar-MacOS-Intel-v1.7.1-20261117-k12-2-part.003.dmgpart)
- [分卷 004.dmgpart](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/student-20261117-k12-2/Kaixin-Super-Scholar-MacOS-Intel-v1.7.1-20261117-k12-2-part.004.dmgpart)

需要 macOS 13 或以上。四个文件下齐后，只打开主文件 `.dmg`，把“开心动力超级学霸”拖进“应用程序”，再从“应用程序”打开。其余 `.dmgpart` 保持原位，不需要逐个打开。

## Windows 64 位

- [安装程序 Setup.exe](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/student-20261117-k12-2/Kaixin-Super-Scholar-Windows-v1.7.1-Setup.exe)
- [Runtime.001](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/student-20261117-k12-2/Kaixin-Super-Scholar-Windows-v1.7.1-Runtime.001)
- [Runtime.002](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/student-20261117-k12-2/Kaixin-Super-Scholar-Windows-v1.7.1-Runtime.002)
- [Runtime.003](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/student-20261117-k12-2/Kaixin-Super-Scholar-Windows-v1.7.1-Runtime.003)
- [Runtime.004](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/student-20261117-k12-2/Kaixin-Super-Scholar-Windows-v1.7.1-Runtime.004)

五个文件下齐后，只运行 `Setup.exe`，按向导安装；安装器会校验其余四个 Runtime 分卷。不要单独解压或改名分卷。

## 第一次打开

首次启动会在本机展开环境并导入教材，请等待完成。进入设置填写自己的聊天 API；摄像头、麦克风和共享屏幕按需要授权。在教材库核对能找到 136 册教材。产品主版本仍为 `1.7.1`；后续从“设置 → 关于”或“核心”点击“检查更新”，不把 `.command` 或手动小补丁作为日常流程。正常更新入口以已正式发布的版本为准；本说明不代替发布回执。

题目图包自身为 13,579,283 字节，**不是整个核心或安装包大小**。核心仍包含题库，跨不同核心包去重尚未实现；缺少兼容运行环境的旧电脑还可能下载一次较大的环境。具体大小以窗口和同批验证文件为准。正常升级保留聊天、资料、阅读记录、API Key 和设置，无需删除学习目录或卸载重装。

Mac 如果提示“身份不明的开发者”，先确认文件来自本仓库，再到“系统设置 → 隐私与安全性”点击对应程序的“仍要打开”。这是系统首次来源确认，不需要运行额外补丁。[Apple 官方说明](https://support.apple.com/zh-cn/102445)

如果提示缺少分卷或镜像无法识别，先检查这组文件是否全部下载完成、放在同一文件夹且未被改名。不要把不同版本或不同芯片的文件混放。

以后的新版通过软件中的“核心 → 检查更新”或“设置 → 关于 → 检查更新”获取；检查和下载需要能够访问 GitHub。仅上传源码不会更新已安装客户端，维护者还需发布对应系统的签名更新包。

本批没有写入 U 盘；旧介质不是本批文件的交付证明。三端验收快照及正式状态的确认依据见 [SOURCE-TEST-HANDOFF.json](SOURCE-TEST-HANDOFF.json)，该文件区分已通过的原生验收与需由正式回执确认的发布、本机升级状态。

[本批文件页 k12-2](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/tag/student-20261117-k12-2) · [上一正式版 k12-1](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/tag/student-20261117-k12-1)
