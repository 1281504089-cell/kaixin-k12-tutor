# 开心动力超级学霸

我们基于 DeepTutor 做了这个桌面版，给用中文课本的小学、初中和高中学生用。从翻课本、问一道题到复盘，这些事都能在同一个桌面应用里完成。

- **装好就能翻 136 册教材。** 课本随安装包一起带上，可以按学段和科目找书。
- **在课本上圈一段就能问。** 选一句话、圈一条公式，提问时能带上原页。翻到下一页，也可以接着问前面的问题。
- **九科有各自的 AI 老师。** 每科都有自己的学习项目。做题卡住时可以选对应科目的老师，先要个提示，自己做下去。

[下载 Windows x64 版](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/tag/student-77f2ba387-windows-x64) · [下载 Apple 芯片 Mac 版](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/tag/student-77f2ba387-macos-arm64) · [下载 Intel Mac 版](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/tag/student-77f2ba387-macos-x64)

**20261111 辅导更新**带来了实时语音通话、高拍仪辅导和聊天内边读边问。已有 1.7.1 的电脑按系统下载对应的更新包，升级时会备份本机学习资料。 [下载最新版（语音浮窗）](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/tag/student-update-20261111-tutoring-voice-float) · [历次更新](https://github.com/1281504089-cell/kaixin-k12-tutor/releases)

[下载图文操作手册 PDF（含 20261111 增补）](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/core-updates/kaixin-k12-tutor-guide-20261111.pdf) · [查看安装步骤](#下载安装) · [看看怎么学](#学习功能) · [获取源码与开发指南](DEVELOPMENT.md)

Kaixin K12 Tutor is a DeepTutor-based desktop study companion for Chinese-speaking students from primary through high school.

## 下载安装

完整安装包版本为 **1.7.1**，自带本机运行环境和教材。第一次安装请下载下表对应的平台文件。装好后再按下方步骤升级辅导功能，并在设置中填写自己的聊天 API 开始问答。

| 电脑 | 安装文件 | 自动试装 |
| --- | --- | --- |
| Apple 芯片 Mac | [下载 Apple 芯片版](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/tag/student-77f2ba387-macos-arm64) | 分卷挂载、全新目录启动、教材读取、退出清理 |
| Intel Mac | [下载 Intel 版](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/tag/student-77f2ba387-macos-x64) | 分卷挂载、全新目录启动、教材读取、退出清理 |
| Windows x64 | [下载 Windows x64 版](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/tag/student-77f2ba387-windows-x64) | 缺卷拦截、中文路径安装、启动、退出、卸载保留资料 |

1. 下载同一发布页的全部平台分卷，放进一个新文件夹并保留原名。学生安装请使用表中的平台文件。
2. Mac 下载 1 个 `.dmg` 和 3 个 `.dmgpart`。双击 `.dmg`，把应用拖入 Applications。
3. Windows 下载 1 个 `Setup.exe` 和 4 个 `Runtime.001` 至 `Runtime.004`。双击 Setup，安装器会校验并合并分卷。
4. 预留至少 30 GB 空间。安装校验和首次启动解压都可能需要几分钟。

## 已安装用户更新

1. 先退出正在运行的客户端，从 [20261111 辅导更新页](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/tag/student-update-20261111-tutoring-voice-float) 下载对应系统的 `Kaixin-Updater-20261111-voice-float` ZIP。Apple 芯片 Mac 选 `macos-arm64`，Intel Mac 选 `macos-x64`，Windows 选 `windows-x64`。
2. Mac 解压后用新版应用替换「应用程序」里的旧版。Windows 解压到一个文件夹，从里面打开开心动力超级学霸，后续使用这个程序入口。

新版启动器里打开「核心 → 检查更新」，或「设置 → 关于 → 检查更新」。已是最新版时会直接显示「已是最新版本」。发现新版时点「下载并更新」。客户端优先从 GitHub API 读取对应系统的签名清单。遇到 GitHub 下载直链报 504 时，会自动从公开 Releases API 下载同一份签名更新。更新复用电脑上已有的 Python、Node.js、教材和本机资源。安装时备份学习工作区，启动失败时恢复上一版与备份。首次安装仍请用上方的完整学生版。

<details>
<summary>旧版启动器的备用下载方式</summary>

如果你需要为较早的版本补装 20261108.5 启动器，可以在终端执行对应系统的一行。Mac 用「终端」，Windows 用 PowerShell。最新辅导更新请用上方的 20261111 下载页。

```sh
# Apple 芯片 Mac
curl -fL -H 'Accept: application/octet-stream' 'https://api.github.com/repos/1281504089-cell/kaixin-k12-tutor/releases/assets/723681904' -o 'Kaixin-Updater-20261108.5-macos-arm64.zip'
# Intel Mac
curl -fL -H 'Accept: application/octet-stream' 'https://api.github.com/repos/1281504089-cell/kaixin-k12-tutor/releases/assets/723681480' -o 'Kaixin-Updater-20261108.5-macos-x64.zip'
# Windows x64
curl.exe -fL -H 'Accept: application/octet-stream' 'https://api.github.com/repos/1281504089-cell/kaixin-k12-tutor/releases/assets/723680574' -o 'Kaixin-Updater-20261108.5-windows-x64.zip'
```

下载并更换启动器后，从应用内检查更新即可。

</details>

## 学习功能

| 学习场景 | 怎么用 |
| --- | --- |
| 教材随读随问 | 按学段、学科筛选或搜索年级、册名，打开整册原页。划选文字可标注或提问。遇到公式、图形和扫描页，长按原页选择「截图引用」，拖框后把原图加入笔记或引用到提问。翻页后可在同一阅读会话继续追问。 |
| 聊天内边读边问 | 在输入框上方点「边读边问」，在右侧打开教材、资料库文档或临时附件。点「问当前页」，把这一页和问题放在同一个聊天里继续讨论。 |
| 实时语音通话 | 点聊天右上角的电话，直接开口。可切换学习辅导、英语陪练、口语翻译、模拟面试等场景，也可共享窗口或屏幕。关掉浮窗后可以从「通话中」重新打开，挂断后文字保存到原对话。 |
| 高拍仪辅导 | 点输入框上方的「高拍仪辅导员」，把纸面题对准摄像头。可旋转、镜像、调画面比例，或临时切到共享屏幕。做题时先给提示，明确要答案时会给简短讲解。 |
| 九科学习项目 | 语文、数学、英语、物理、化学、生物、历史、地理、政治各预置三个对话。选学科老师做专项练习，可分别设置项目指令和对话指令。 |
| 拍题与资料问答 | 拍照和一至两页的短 PDF 可交给支持读图的模型先看原图。需要全文时在后台解析。输入框和右侧预览共用临时附件。 |
| 错题本与笔记 | 按学科保存错题，选中文字或截取公式和图形后可加入笔记。 |
| 九科学习复盘 | 选学科和日期，默认读取对应科目项目，也可手动加入聊天或阅读对话。报告按学科整理考点、易错点和练习，理科按需配图，依据放在文末，可导出 Word。「四问复盘」选填。 |
| 选模型 | 菜单标出快速问答、理科难题验算、长文阅读等用途。填入 API 后可发现接口列出的受支持模型，打开菜单时在后台更新列表。 |
| 数学动画和视频讲解 | 发送后后台生成，可以继续其他学习。从「动画与视频」看进度、停止指定任务或回到原聊天播放。 |
| 其他学习工具 | 支持公式、图表、互动课件、日历和任务看板。安装包附带本机语音转文字和向量检索组件。 |

教材库收录的是当前目录中的主科册次。原页可直接阅读，日常答题自动参考已核对的教材要点，待核对页面保留状态。

学习记录、资料和设置保存在本机。语音通话和高拍仪辅导需要联网，并在「设置 → 语音 → 豆包实时语音」保存自己的 API Key。该 Key 独立于聊天模型及本机语音转文字。远程模型问答、Edge 朗读、搜索和公开视频字幕也需要网络。安装包已排除 API 密钥、个人学习记录和签名私钥。

## 开发者

从 GitHub 克隆发行仓库后，运行 `python3 bootstrap_source.py --with-updates`，即可校验、解包并应用最新源码修复。上方安装包仍是原有发布版。开发者指南列出本地启动命令、教材与学科配置的位置、打包入口和依赖说明。 [查看开发者指南](DEVELOPMENT.md) · [查看源码清单](source-manifest.json)

## 验证与许可

发布页附 `SHA256SUMS.txt` 和 `validation.json`，对应同一冻结源码 `77f2ba387713d23ef6af9897d393d24d84e421be`。Mac 在 macOS 15 原生构建机验证，Windows 在 Windows 原生构建机验证。体验包采用 Mac 临时签名和 Windows 未签名安装器，首次打开可能看到系统来源提示。

源码归档内附 `LICENSE` 与 `THIRD_PARTY_NOTICES.md`。教材、GeoGebra、Remotion 等资源的使用与分发条件请查看各自说明。 [接口与许可说明](delivery-notes.md) · [上游 DeepTutor](https://github.com/HKUDS/DeepTutor)
