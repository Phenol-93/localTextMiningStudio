# Windows 绿色版 Smoke Test

## 构建

```powershell
.\scripts\build_windows.ps1
```

预期结果：

- 生成 `dist/LocalTextMiningStudio/`
- 生成 `dist/LocalTextMiningStudio/LocalTextMiningStudio.exe`
- 生成 `dist/LocalTextMiningStudio/README.txt`
- 生成 `dist/LocalTextMiningStudio_v0.1.0_windows.zip`

## 基本启动检查

1. 解压 zip 到一个可写目录。
2. 双击 `LocalTextMiningStudio.exe`。
3. 确认主窗口标题为“本地文本挖掘工作台”。
4. 确认左侧导航、页面区域、底部状态栏正常显示。
5. 确认状态栏右下角显示“作者：Phenol93”。

## 便携数据检查

1. 新建一个项目。
2. 确认软件目录下出现 `user_data/projects`。
3. 关闭并重新打开程序。
4. 确认可以打开刚才创建的项目。

## 基本功能检查

1. 导入一个临时 `.txt` 文件。
2. 进入文本预处理页面，预览 token 并保存。
3. 进入传统文本挖掘页面，运行词频统计。
4. 进入导出中心，导出 CSV 并生成报告。
5. 确认 `exports` 目录中出现导出文件。

## AI 功能检查

1. 进入设置页配置供应商、模型和 API Key。
2. 点击测试连接。
3. 确认日志和报告中没有明文 API Key。

## 离线图谱检查

1. 在有 accepted 或 edited 三元组的项目中打开“知识图谱”。
2. 点击“生成图谱”。
3. 点击“导出 graph.html”。
4. 断网后用浏览器打开导出的 `graph.html`，确认图谱可显示。
