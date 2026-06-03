# Local Text Mining Studio

本地文本挖掘工作台是一个面向中文文本分析的桌面应用，使用 PySide6 构建，默认以绿色版/便携模式运行。它把文档导入、文本预处理、传统文本挖掘、AI 三元组抽取、人工审核、实体关系标准化、知识图谱构建、图谱分析和结果导出放在同一个本地工作流里。

#### ↓↓↓↓↓绿色免安装版本这里下载↓↓↓↓↓
链接：https://1850521186.share.123pan.cn/123pan/5HR4vd-Kec6H?pwd=UIrS#
提取码：UIrS


后续计划先做好传统文本部分的可视化，然后再优化知识图谱部分，有bug反馈一下靴靴。

转载需标明出处。

## 功能概览

- 项目管理：每个项目使用独立的 `project.sqlite` 数据库。
- 文档导入：支持 `.txt`、`.csv`、`.docx`。
- 文本预处理：支持中文分词、停用词过滤、去标点、去数字、小写化、自定义词典和自定义停用词。
- 传统文本挖掘：支持词频、TF-IDF、LDA、NMF，并可导出 CSV。
- AI 三元组抽取：支持 OpenAI-compatible、Gemini、DeepSeek、Qwen/百炼、本地 Ollama 和自定义供应商。
- Prompt 模板：内置多类抽取模板，支持复制、编辑、导入、导出和恢复默认模板。
- 三元组审核：支持筛选、编辑、接受、拒绝、删除和导出。
- 实体/关系标准化：保留原始三元组，在构图和导出阶段应用映射。
- 知识图谱：使用 NetworkX 构建图谱，支持节点/边指标和社区计算。
- 图谱可视化：使用本地 Cytoscape.js 资源，支持离线查看。
- 导出与报告：支持 triples、nodes、edges CSV 和 Markdown 报告。

## 运行环境

- Windows 10/11
- Python 3.10 或更高版本
- 推荐使用虚拟环境或 Conda 环境

## 从源码运行

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m app.main
```

如果你使用 Conda：

```powershell
conda create -n local-text-mining-studio python=3.11 -y
conda activate local-text-mining-studio
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m app.main
```

## 测试

```powershell
python -m pytest
```

测试不会调用真实 AI API。Provider 相关测试使用 fake provider 或 mock。

## Windows 绿色版打包

项目提供 PyInstaller onedir 打包脚本：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_windows.ps1
```

输出位置：

- 绿色版目录：`dist/LocalTextMiningStudio/`
- 发布 zip：`dist/LocalTextMiningStudio_v0.1.0_windows.zip`

打包版本不要求用户安装 Python。发布目录需要整体保留，不要只复制 `.exe`。

## 数据与隐私

- 默认使用便携模式，运行数据保存在软件目录下的 `user_data/`。
- 日志写入 `logs/app.log`。
- 导出文件默认放在 `exports/`。
- API Key 不会写入配置 JSON 明文。
- 只有用户主动勾选“保存 API Key”时，才会尝试通过 keyring 保存。
- AI 抽取不会把完整原文或 API Key 写入日志。

## 目录结构

```text
app/
  core/          核心业务逻辑
  db/            SQLite schema、连接和 repository
  providers/     AI provider 抽象与适配
  resources/     停用词、Prompt 模板、本地 webview 资源
  ui/            PySide6 界面
  utils/         路径、日志、后台任务等工具
docs/            文档和 smoke test 说明
examples/        示例资源
scripts/         打包和发布脚本
tests/           pytest 测试
```

## 开发说明

- 启动命令固定为 `python -m app.main`。
- 默认不写死绝对路径，绿色版打包后会自动识别程序目录。
- 长任务通过后台线程执行，UI 更新使用 signal/slot。
- SQLite 使用标准库 `sqlite3`，SQL 查询应使用参数化参数。

## 许可证

当前仓库尚未声明开源许可证。正式发布前请添加 `LICENSE` 文件。
