# 开心动力超级学霸 · K–12 专属学习搭子

基于 [DeepTutor](https://github.com/HKUDS/DeepTutor) 为 K–12 学科重新优化的本地桌面学习应用。首次启动自动导入当前收录的 **136 册主科教材**，覆盖小学、初中和高中。打开「教材 · 边读边问」就能翻原页、选段落、圈公式，随读随问。

Kaixin K12 Tutor is a DeepTutor-based desktop study companion for primary through high school.

[下载安装](#下载安装) · [学习功能](#学习功能) · [开发者指南](DEVELOPMENT.md)

## 下载安装

当前学生体验版 **1.7.1 · `77f2ba387`**。安装包已带本机运行环境和教材，新电脑安装后在设置中填写自己的聊天 API。

| 电脑 | 安装文件 | 自动试装 |
| --- | --- | --- |
| Apple 芯片 Mac | [下载 Apple 芯片版](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/tag/student-77f2ba387-macos-arm64) | 分卷挂载、全新目录启动、教材读取、退出清理 |
| Intel Mac | [下载 Intel 版](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/tag/student-77f2ba387-macos-x64) | 分卷挂载、全新目录启动、教材读取、退出清理 |
| Windows x64 | [下载 Windows x64 版](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/tag/student-77f2ba387-windows-x64) | 缺卷拦截、中文路径安装、启动、退出、卸载保留资料 |

1. 下载同一发布页的全部平台分卷，放进一个新文件夹并保留原名。学生安装请使用表中的平台文件。
2. Mac 下载 1 个 `.dmg` 和 3 个 `.dmgpart`。双击 `.dmg`，把应用拖入 Applications。
3. Windows 下载 1 个 `Setup.exe` 和 4 个 `Runtime.001` 至 `Runtime.004`。双击 Setup，安装器会校验并合并分卷。
4. 预留至少 30 GB 空间。安装校验和首次启动解压都可能需要几分钟。

## 学习功能

| 学习场景 | 怎么用 |
| --- | --- |
| 教材随读随问 | 按学段、学科筛选或搜索年级、册名，打开整册原页。划选文字或用「框选原页」标注和提问，公式、图形和上下标随选区截图引用。翻页后可在同一阅读会话继续追问。 |
| 九科学习项目 | 语文、数学、英语、物理、化学、生物、历史、地理、政治各预置三个对话。选学科老师做专项练习，可分别设置项目指令和对话指令。 |
| 拍题与资料问答 | 拍照和一至两页的短 PDF 可交给支持读图的模型先看原图。需要全文时在后台解析。输入框和右侧预览共用临时附件。 |
| 错题、笔记和复盘 | 按学科整理错题，把对话选段添加到笔记，按日期查看学习报告，可展开「四问复盘」。 |
| 选模型 | 菜单标出快速问答、理科难题验算、长文阅读等用途。填入 API 后可发现接口列出的受支持模型，打开菜单时在后台更新列表。 |
| 动画与学习工具 | 支持公式、图表、数学动画、互动课件、日历和任务看板。安装包附带本机语音转文字和向量检索组件。 |

教材库收录的是当前目录中的主科册次。原页可直接阅读，日常答题自动参考已核对的教材要点，待核对页面保留状态。

学习记录、资料和设置保存在本机。远程模型问答、Edge 朗读、搜索和公开视频字幕需要网络。安装包已排除 API 密钥、个人学习记录和签名私钥。

## 开发者

从 GitHub 克隆发行仓库后，运行 `python3 bootstrap_source.py`，即可校验并解包完整源码。开发者指南列出本地启动命令、教材与学科配置的位置、打包入口和依赖说明。 [查看开发者指南](DEVELOPMENT.md) · [查看源码清单](source-manifest.json)

## 验证与许可

发布页附 `SHA256SUMS.txt` 和 `validation.json`，对应同一冻结源码 `77f2ba387713d23ef6af9897d393d24d84e421be`。Mac 在 macOS 15 原生构建机验证，Windows 在 Windows 原生构建机验证。体验包采用 Mac 临时签名和 Windows 未签名安装器，首次打开可能看到系统来源提示。

源码归档内附 `LICENSE` 与 `THIRD_PARTY_NOTICES.md`。教材、GeoGebra、Remotion 等资源的使用与分发条件请查看各自说明。 [接口与许可说明](delivery-notes.md) · [上游 DeepTutor](https://github.com/HKUDS/DeepTutor)
