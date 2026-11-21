# 在自己的电脑上运行 EDAgent

EDAgent 的工作台和主 Agent 在 Windows 上运行，Linux 服务器执行 iEDA。第一次使用可以选择已登记的 SWERV 设计。它有 6,777 个标准单元和 3 个 SRAM 宏，能在已配置的研究服务器上从映射网表跑到布线 DEF 和抽象 GDS。

## 安装工作台

安装 Git、带 Windows 启动器的 Python 3.11 或更高版本、Node.js 24（含 npm），以及 Windows OpenSSH 客户端。打开 PowerShell 执行以下命令。

```powershell
git clone https://github.com/EasonGao0728/EDAgent.git
cd EDAgent
py -3 -m venv .venv-agent
.\.venv-agent\Scripts\python.exe -m pip install -e ".[chatgpt]"
npm.cmd ci --ignore-scripts
npm.cmd start
```

保持终端运行，打开[本地工作台](http://127.0.0.1:4173/)。按照界面中的模型连接指引填写服务地址、协议、模型 ID 和 API 密钥，选择支持工具调用的模型。以后在同一个目录运行 `npm.cmd start` 即可再次启动。

## 运行完整案例

1. 向服务器管理员获取已部署 iEDA 的主机和个人账号。按[部署指南](DEPLOYMENT.md)设置 SSH 别名 `eda-worker` 和两端的 `environments/remote-server.json`。先用 `ssh -o BatchMode=yes eda-worker id -u` 验证连接。全新安装默认显示服务器离线。独立部署还需准备匹配的原生工具、案例包和工艺库。
2. 服务器在线后，新建对话，打开「选择现有案例」，将任务类型筛为「完整后端」，选中 `swerv_nangate45`。
3. 在对话中输入「请从映射网表运行这个 SWERV 案例的完整后端，保留三个 SRAM 宏，交付布线 DEF、版图预览和 DRC 报告。」
4. 从当前任务查看布局、时钟树、布线和后续检查。打开交付卡片，核对宏数量、DEF 回读、GDS 验证和剩余 DRC。当前公开目录列出 50 个设计，其中 5 个已登记完整后端入口。逐项状态见[案例矩阵](CASE_MATRIX.md)。

「自定义输入案例」会列出映射网表、工艺及单元 LEF、匹配的 Liberty、SDC 和案例元数据要求。完整后端目前按登记输入包验证。

[原始架构图](images/agent-architecture.png) · [三个开发阶段](../README.md#development-roadmap) · [验收记录](QUALIFICATION.md)
