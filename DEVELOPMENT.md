# 开发者指南

开心动力超级学霸是基于 [DeepTutor](https://github.com/HKUDS/DeepTutor) 的 K–12 桌面改编。Electron 启动本机 Python 后端和 Next.js 前端。课堂资料、阅读进度和学习记录保存在工作区，远程聊天模型由使用者在设置中配置。

## 取得完整源码

准备 Git 和 Python 3.12。克隆仓库后在仓库根目录运行解包脚本。

```sh
git clone --depth 1 https://github.com/1281504089-cell/kaixin-k12-tutor.git
cd kaixin-k12-tutor
python3 bootstrap_source.py --with-updates
cd student-source
```

Windows 可用 `py -3.12 bootstrap_source.py --with-updates`。脚本会按清单校验两个分卷与合并归档的 SHA-256，然后解包到新的 `student-source/` 目录。归档的源码版本记录在 `student-source/SOURCE_FREEZE.json`。`--with-updates` 还会校验并应用[学生版源码修复](student-source-updates.patch)，可在解包目录用 `git log -2` 查看。省略该参数可取回与当前安装包一致的冻结源码。 [源码清单](source-manifest.json) · [解包脚本](bootstrap_source.py)

## 本地运行

准备 Python 3.12 和 Node.js 22，以下命令从 `student-source/` 执行。Mac 或 Linux 用 `source .venv/bin/activate` 激活虚拟环境。Windows PowerShell 用 `.\.venv\Scripts\Activate.ps1`。

```sh
python -m venv .venv
```

激活后安装依赖，再启动开发界面。

```sh
python -m pip install -r requirements/full.txt
python -m pip install -e . --no-deps
npm --prefix web ci --legacy-peer-deps
deeptutor init --non-interactive --home data/dev-home
deeptutor start --dev --home data/dev-home
```

在打开的界面里填写自己的聊天 API。开发数据放在源码目录下的 `data/dev-home`。源码启动可上传自己的资料调试；136 册教材、本机模型和原生渲染组件随桌面安装包提供。

## 从哪里改起

下表的路径相对于解包后的 `student-source/`。

| 要改的功能 | 代码入口 |
| --- | --- |
| 九科项目、默认对话和指令 | `deeptutor/services/workspace/student_study.py`、`web/lib/student-study-projects.ts`、`web/lib/student-prompts.ts` |
| 学科老师与专项提示词 | `web/public/student/teachers/` |
| 教材列表和首启导入 | `web/components/student/TextbookLibrary.tsx`、`deeptutor/services/student_learning/bootstrap.py` |
| 边读边问、选区引用和批注 | `web/components/reading/`、`deeptutor/services/student_learning/reading.py` |
| 错题本与学习报告 | `deeptutor/services/student_learning/mistakes.py`、`deeptutor/services/student_learning/reports.py` |
| 模型菜单与接口发现 | `web/components/chat/home/ModelSelector.tsx`、`deeptutor/services/settings/connection_setup.py` |
| 桌面外壳、运行时和打包 | `apps/desktop/`。本机构建步骤见源码内的 `apps/desktop/README.md`。 |

改网页时可运行 `npm --prefix web run typecheck`。桌面外壳安装 npm 依赖后可运行 `npm --prefix apps/desktop test`。原生打包使用对应平台的运行时及自有签名密钥。 [三平台学生版构建流程](.github/workflows/student-delivery.yml)

## 复用与归属

源码归档内的 `LICENSE` 为 Apache 2.0，第三方源码和素材归属见归档内的 `THIRD_PARTY_NOTICES.md`。GitHub 侧栏的 GPL-3.0 标识来自 [dvisvgm 的许可证文件](dvisvgm-LICENSE.txt)。使用或分发教材及打包组件时请核对各自的条款。 [接口与许可说明](delivery-notes.md)
