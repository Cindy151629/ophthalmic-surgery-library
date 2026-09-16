# 眼科手术文献与视频阅读库

网页按七个一级板块、亚专科和具体术式组织。两版 Word 的 609 条来源行按实际超链接与标识符对账，合并为 562 条基线资源：279 篇文献、283 条视频。每篇基线文献均有中文阅读笔记；正文、正文片段及摘要依据分别标明。新发现而尚未细读的题录在“新发现·待读”中单列。

本库不是全部眼科手术资源清单。公开资料受限时保留身份和阅读范围，不把摘要称为全文，不把具体页面核实称为视频播放测试。视频在原站观看，本站不下载、转录、托管或自动加载播放器。

## 构建与测试

```sh
python -m pip install -r requirements.txt
python scripts/build.py
python -m unittest discover -s tests -v
python scripts/update.py
```

`data/records.json` 是唯一规范数据源。`site` 和单文件离线 HTML 由构建生成。`data/review-queue.json` 保存有疑点或未通过自动规则的候选；自动流程不会覆盖阅读笔记。DOI/PMID/PMCID、原始来源键和跨版编号均保留。相同裸编号存在歧义时使用 `#original:CAT-V01` 或 `#expanded:CAT-V01`，也可使用稳定资源 ID。

## 云端每周维护

GitHub Actions 的 `weekly.yml` 按 Asia/Shanghai 每周一 09:17 调度，也支持 workflow_dispatch。手动发布已经核验的目录/页面修订时可关闭 refresh_sources；该模式会明确记录为 publish-reviewed，不推进任何发现水位。定时运行始终执行来源发现。调度 active、手动触发运行完成、未来某次定时实际发生，是三种不同证据。网页分别读取运行状态和已验证发布回执。

程序以 Europe PMC/PubMed 和配置的官方视频目录为来源，完整分页、30 天重叠窗口、七板块轮转历史补检，逐项去重和核验。符合自动规则的题录、具体视频页可发布；正文阅读不由定时脚本伪造。失败的来源不推进成功水位；网络失败不删除旧条目。来源连续失败时暂停同源链接重试并记录延期范围，避免整库受一次来源故障拖累。

发布前运行测试，发布后逐一比较四个 HTTPS 文件的 SHA-256；通过后才写 `data/publication-status.json`，并将对应制品固定到 `release-good`。部署失败会尝试恢复上一已验版本。`data/runtime-status.json` 区分开始、部分来源受限、失败、成功；`reports/runs` 保存每次实际证据。某周失败后的唯一常规恢复操作是处理来源或权限问题后重跑 Actions 中同一工作流；不需要每周打开 Codex。

## 导入和证据边界

初次 Word 导入基于 OOXML relationships 的真实超链接，旧版和新版分开记录；不按题名猜 URL。原始 Word、来源正文缓存、私人批注和认证信息不进入此仓库。公开仓库只含资源元数据、任务撰写笔记、核验结果及维护代码。原始文件备份与完整本地证据留在本地工作区。

`reports/import-reconciliation.json` 列出每行导入去向；`reports/coverage.json` 是构建生成的术式矩阵；`reports/note-conflicts.json` 记录来源冲突；`reports/current-run.json` 和运行制品保存执行证据。链接状态、医学内容核对范围、文章关联通知分别记录。
