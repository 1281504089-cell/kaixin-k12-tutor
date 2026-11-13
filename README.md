# 开心动力超级学霸

我们基于 DeepTutor 做了这个桌面版，给用中文课本的小学、初中和高中学生用。从翻课本、问一道题到复盘，这些事都能在同一个桌面应用里完成。

- **装好就能翻 136 册教材。** 课本随安装包一起带上，可以按学段和科目找书。
- **在课本上圈一段就能问。** 选一句话、圈一条公式，提问时能带上原页。翻到下一页，也可以接着问前面的问题。
- **九科有各自的 AI 老师。** 每科都有自己的学习项目。做题卡住时可以选对应科目的老师，先要个提示，自己做下去。

[下载 Windows x64 版](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/tag/student-04276f68a-windows-x64) · [下载 Apple 芯片 Mac 版](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/tag/student-04276f68a-macos-arm64) · [下载 Intel Mac 版](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/tag/student-04276f68a-macos-x64)

**20261113 整合更新。** 对话里的教材页码现在能直接打开对应原页，有核实原句时会短暂标亮；右侧收起或切到活动后也能点击打开；阅读区可输入页码、按回车跳转。无关教材页不再额外跑一轮模型研读。合并了移入项目、查历史聊天、在聊天里创建和修改任务，以及此前的附件长期保存、语音输入、选择卡片和数学配图更新。[整合说明与验证范围](INTEGRATED-20261113.md)

**20261112 三系统完整安装版。** 首次安装即包含 MOSS、豆包实时语音、高拍仪、手机摄像头与共享屏幕、场景切换、阅读记录恢复、原 PDF 文字／公式截图引用和 Kimi API 入口。启动页、桌面菜单、主界面和 Windows 安装向导默认简体中文，不需要先装旧版再补功能更新。已补齐 MOSS-Live 在系统 SOCKS 代理下需要的语音连接组件，三个系统均重新打包、原生试装。已有用户升级时保留本机学习工作区。 [完整安装说明](INSTALL-20261112.md) · [旧版更新与回退](https://github.com/1281504089-cell/kaixin-k12-tutor/releases)

添加文字聊天 API 时，可搜索 **Kimi / Moonshot（月之暗面）** 并填写对应 Key；原有接口、密钥和默认模型保持不变。

在「设置 → 语音」可切换豆包 / **MOSS-Live 实时语音**，分别保存 Key；不会自动更换原有豆包配置。上方三种系统的完整安装包均已包含这项功能。[MOSS-Live 接入与小样本对比](MOSS-LIVE.md)

[查看 20261112 安装说明](INSTALL-20261112.md) · [原版安装图解 PDF](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/student-complete-20261111/INSTALL-complete-20261111.pdf) · [查看安装步骤](#下载安装) · [看看怎么学](#学习功能) · [获取源码与开发指南](DEVELOPMENT.md)

Kaixin K12 Tutor is a DeepTutor-based desktop study companion for Chinese-speaking students from primary through high school.

## 20261113 源码修复

[数学配图与选择题卡的新增说明、实拍及实测数据](MATH-FIGURES-20261113.md)：讲题需要图时主动配静态图，确有必要才用交互图；完整文字选择题自动补快捷选项，原题保留。沿用原有 SVG／GeoGebra 显示与动画流程，只保留有速度实测收益的补充路径。**已合入 20261113 签名代码更新；三系统完整安装包仍为 20261112，未重新打包。**

[查看本次修复、使用方式和验证范围](SOURCE-FIXES-20261113.md)：附件可选临时／长期保存、科目项目新建对话、离线语音转写和录音声波反馈、模型切换兼容、DeepSeek 分级生成预算与摘要失败提示。**已合入 20261113 签名代码更新。Intel Mac 用户从客户端检查更新；下方 20261112 完整安装包仍需另作增量更新，Apple 芯片与 Windows 本轮未做真机试装。**

## 下载安装

完整安装包基础版本为 **1.7.1**，已合入 20261111 辅导与阅读修复，以及 20261112 语音连接组件修复，自带本机运行环境和 136 册教材。第一次安装只用下表对应系统的这一套文件；装好后在设置填写自己的 API。界面默认简体中文。

| 电脑 | 安装文件 | 自动试装 |
| --- | --- | --- |
| Apple 芯片 Mac | [下载 Apple 芯片版](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/tag/student-04276f68a-macos-arm64) | 原生安装启动、教材读取、13 项语音回归、代理收发 |
| Intel Mac | [下载 Intel 版](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/tag/student-04276f68a-macos-x64) | 原生安装启动、教材读取、13 项语音回归、代理收发 |
| Windows x64 | [下载 Windows x64 版](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/tag/student-04276f68a-windows-x64) | 中文路径安装、启动、13 项语音回归、卸载保留资料 |

1. 下载同一发布页的全部平台分卷，放进一个新文件夹并保留原名。学生安装请使用表中的平台文件。
2. Mac 下载 1 个 `.dmg` 和 3 个 `.dmgpart`。双击 `.dmg`，把应用拖入 Applications。
3. Windows 下载 1 个 `Setup.exe` 和 4 个 `Runtime.001` 至 `Runtime.004`。双击 Setup，安装器会校验并合并分卷。
4. 建议预留 40 GB 临时空间。安装校验和首次启动解压都可能需要几分钟。

**U 盘交付采用每个系统一份完整文件**：Apple 芯片和 Intel 各一个普通 `.dmg`；Windows 一个完整 ZIP，解压后运行 `Setup.exe`。无需手动合并 Mac 分卷或另补语音组件。GitHub 每个发布附件限制为 2 GiB，因此上方下载页仍提供经校验的分卷；U 盘与 GitHub 包内使用同一份已验证运行环境。

<details>
<summary>Mac 打开分卷提示错误 109、110 或“镜像无法识别”</summary>

先把同一版本的 `.dmg`、全部 `.dmgpart` 和 `SHA256SUMS.txt` 放在本机同一个文件夹，保留原名。若 U 盘附带「Mac-Apple芯片-兼容安装」，打开该文件夹内的单文件 `.dmg`，再把应用拖入「应用程序」。

GitHub 下载的两种 Mac 包均可合并成单文件。先在终端进入下载文件夹，校验通过后执行转换；把 `./发布页中以-part.dmg结尾的文件名` 换成当前文件夹里真正的首卷名称。

```sh
shasum -a 256 -c SHA256SUMS.txt
hdiutil convert -format ULFO -o "$HOME/Downloads/Kaixin-Mac-Complete.dmg" ./发布页中以-part.dmg结尾的文件名
open "$HOME/Downloads/Kaixin-Mac-Complete.dmg"
```

合并额外占用约 7 GB。若输出文件已存在，先核对版本或换一个文件名；校验失败时重新复制或下载失败的分卷。客户端要求 macOS 13 或以上。U 盘 20261112 目录已提供普通单文件镜像，可以直接打开，不用转换。

U 盘单文件镜像按磁盘校验、只读挂载、应用签名、芯片架构、运行环境签名和完整回读流程验收。对应系统的安装与启动已在原生构建机验证；U 盘成品的完成状态与具体结果见[三系统验收记录](verification/20261112-complete.json)。

</details>

三种系统包含相同的学习功能。体积主要来自 136 册教材和本机运行工具；各系统的原生运行文件、安装容器和压缩方式不同，请按对应发布页全部安装分卷的合计大小比较。MOSS、豆包与本次修复已集成在完整包里。

## 旧版用户的可选增量更新

首次安装请先用上方完整包。20261113 的阅读与学习操作通过代码增量更新提供；以下小包供已经安装过 1.7.1 运行环境的电脑使用。

这里的增量包主要更新应用代码，不会自动给旧运行环境补装 20261112 的语音代理依赖。使用 MOSS-Live 时若提示缺少本机组件，请先用 [Mac 离线语音修复包](MOSS-LIVE.md#2026-11-12部分电脑开始通话即断开)，或安装上方对应系统的完整包。

1. 先退出正在运行的客户端，从 [20261111 辅导更新页](https://github.com/1281504089-cell/kaixin-k12-tutor/releases/tag/student-update-20261111-reading-complete) 下载对应系统的 `Kaixin-Updater-20261111-reading-complete` ZIP。Apple 芯片 Mac 选 `macos-arm64`，Intel Mac 选 `macos-x64`，Windows 选 `windows-x64`。
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
| 实时语音通话 | 在「设置 → 语音」选豆包或 MOSS-Live 并保存对应 Key。点聊天右上角的电话，有已保存 Key 时直接接通；首次也可在通话窗口填写。可切换学习辅导、英语陪练、口语翻译、模拟面试等场景，也可共享窗口或屏幕。收起浮窗后可以从「通话中」重新打开，挂断后文字保存到原对话。 |
| 高拍仪辅导 | 点输入框上方的「高拍仪辅导员」，再点「开始通话」（部分版本显示「开始语音通话」），把纸面题对准摄像头。可旋转、镜像、调画面比例，或临时切到共享屏幕。做题时先给提示，明确要答案时会给简短讲解。 |
| 九科学习项目 | 语文、数学、英语、物理、化学、生物、历史、地理、政治各预置三个对话。选学科老师做专项练习，可分别设置项目指令和对话指令。 |
| 拍题与资料问答 | 拍照和一至两页的短 PDF 可交给支持读图的模型先看原图。需要全文时在后台解析。输入框和右侧预览共用临时附件。 |
| 错题本与笔记 | 按学科保存错题，选中文字或截取公式和图形后可加入笔记。 |
| 九科学习复盘 | 选学科和日期，默认读取对应科目项目，也可手动加入聊天或阅读对话。报告按学科整理考点、易错点和练习，理科按需配图，依据放在文末，可导出 Word。「四问复盘」选填。 |
| 选模型 | 菜单标出快速问答、理科难题验算、长文阅读等用途。填入 API 后可发现接口列出的受支持模型，打开菜单时在后台更新列表。 |
| 数学动画和视频讲解 | 发送后后台生成，可以继续其他学习。从「动画与视频」看进度、停止指定任务或回到原聊天播放。 |
| 其他学习工具 | 支持公式、图表、互动课件、日历和任务看板。安装包附带本机语音转文字和向量检索组件。 |

教材库收录的是当前目录中的主科册次。原页可直接阅读，日常答题自动参考已核对的教材要点，待核对页面保留状态。

学习记录、资料和设置保存在本机。语音通话和高拍仪辅导需要联网，可在「设置 → 语音」提前保存豆包或 MOSS-Live API Key；首次通话时填写的 Key 也会在接通后保存。两个服务分别保存 Key，独立于聊天模型及本机语音转文字。远程模型问答、Edge 朗读、搜索和公开视频字幕也需要网络。安装包已排除 API 密钥、个人学习记录和签名私钥。

## 开发者

从 GitHub 克隆发行仓库后，运行 `python3 bootstrap_source.py --with-updates`，即可校验、解包并应用最新源码修复。上方完整安装包已由完整补丁集合重建，不需要另补辅导更新。开发者指南列出本地启动命令、教材与学科配置的位置、打包入口和依赖说明。 [查看开发者指南](DEVELOPMENT.md) · [查看源码清单](source-manifest.json)

## 验证与许可

发布页附 `SHA256SUMS.txt`、`validation.json`、`components.json` 和 `installed-voice-smoke.json`，记录各系统完整包的源码标识、运行环境校验值与首次安装验收结果；旧冻结快照与全部增量补丁保留。Mac 在 macOS 15 原生构建机验证，Windows 在 Windows 原生构建机验证。体验包采用 Mac 临时签名和 Windows 未签名安装器，首次打开可能看到系统来源提示。

源码归档内附 `LICENSE` 与 `THIRD_PARTY_NOTICES.md`。教材、GeoGebra、Remotion 等资源的使用与分发条件请查看各自说明。 [接口与许可说明](delivery-notes.md) · [上游 DeepTutor](https://github.com/HKUDS/DeepTutor)
