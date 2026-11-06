# 织序 · 纺织工厂 Agent Demo

可在 Windows 本机运行的 ERP + MES 一体化系统与真实 DeepSeek Agent。包含后端、网页、SQLite 数据库、模拟数据、私有工具适配层、报表编辑器和可配置技能。原有 `docs/architecture.md`、`docs/implementation-plan.md`、`docs/pain-points.md` 保留为设计参考，实际实现以本文和 [实际架构](docs/demo-architecture.md) 为准。

## 一键启动与关闭

1. 安装 Python 3.11+，确保 `python` 在 PATH 中。
2. 环境变量中配置 `DEEPSEEK_API_KEY`。启动器支持当前进程、Windows 用户变量和系统变量；不需要把密钥写进项目。
3. 双击 **`start.cmd`**。首次自动创建 `.venv`、安装依赖、初始化数据、启动两个后端并打开网页。
4. 访问 **http://127.0.0.1:8765**，先登录。首次启动为7个岗位生成独立随机密码，账号见本机 `data/demo-accounts.json`（不会提交 Git）。
5. 使用管理员账号登录后，点击网页右上角或左下角 **⏻**，再点击“关闭整个 Demo”。两个后端及管理进程退出，数据保留。也可双击 `stop.cmd`。

Agent 正在办理业务时，网页关闭操作会提示等待任务结束。本机 `stop.cmd` 供机器维护者直接停止服务；普通岗位网页只能退出自己的登录。启动器只管理本项目创建的子进程，不按端口或进程名批量杀进程。再次启动保留已有数据，不重复播种。连续点击或并发启动会等待并复用同一个健康实例，不会因重复管理进程退出而误报失败。

命令行启动（不打开浏览器）：

```powershell
.\start.ps1 -NoBrowser
```

无需 Node、Docker、独立数据库服务或前端构建。ECharts、Marked 和 DOMPurify 的固定版本及许可证已保存在 `frontend/vendor/`，网页不依赖公共 CDN。首次安装 Python 依赖及每次 AI 调用需要网络。

## 功能

| 模块 | 已实现能力 |
| --- | --- |
| 岗位总览 | 根据岗位授权呈现订单、在产工单、良品率、库存预警及近期业务数据 |
| 权限管理 | 登录、账号管理、岗位字段读权限、业务写权限、客户数据范围、聊天与报表隔离 |
| ERP + MES | 客户/供应商、产品/BOM、物料/成品库存、销售单、采购入库、设备、排产、领料、报工质检、发货、库存流水与审计 |
| 智能助手 | 真实 DeepSeek function calling、自主多轮工具循环、Markdown 回复、聊天内交互图表、历史对话、执行状态、工具输入输出记录与异常反馈 |
| 数据分析 | 数据目录与业务口径、只读 SQL、JOIN/聚合/CTE、查询资源限制 |
| 报表工作室 | 明细表、透视表、柱状图、折线图、面积图、饼图、散点图、热力图；SQL 查询、单元格编辑、增删行、添加列、JSON 导入、CSV/图形 PNG 导出 |
| 技能与流程 | JSON 接入、网页编辑与导出、启用/禁用、输入校验、指令型技能及声明式事务流程 |
| 生命周期 | 一键启动、前端关闭整个 Demo、持久化、意外中断状态标记与会话工具消息修复 |

内置 3 个客户、2 个供应商、3 种面料、4 种原料、4 台设备、18 张销售单、13 张工单及历史报工/发货。日期相对首次初始化日期生成；库存从期初余额开始记录，期初之前的历史订单不用于反推当前库存。

业务规则由 ERP/MES 校验：下达工单按 BOM 领料，缺料或设备占用会拒绝；报工不能超量，不合格必须填写原因，合格品自动入库；支持不合格补产和部分发货；不能超库存或超订单余量发货；采购不能重复入库。请求具备幂等校验，多步骤技能任一步失败整组回滚。

## 建议的演示顺序

使用管理员账号演示完整业务闭环；其他岗位只展示岗位内能力。在“智能助手”中发送：

> 请使用生产经营晨报技能，检查交期、缺料和质量，保存异常明细表与产品订单金额柱状图。

> 请按客户统计订单金额和交付率，生成明细表与柱状图，说明统计口径。

> 原料 M002 再生涤纶丝已到货 400kg，请使用 purchase-receive 技能创建采购单并入库，核对库存变化。

> 使用 order-to-production 技能：客户 C001，产品 P001，数量 120 米，交期 2026-12-20，设备 MC02。创建订单、排产并下达领料。

按演示日期调整交期。然后在同一对话继续：

> 对刚才的工单报工：合格 118 米、不合格 2 米，原因色差。按刚才的订单发货 118 米，核对库存与单据状态。

> 在 MC02 补产剩余 2 米，合格报工后发货，使订单完成。

在“生产与经营”查看单据、库存和审计；在“报表工作室”打开图表、切换展示方式或修改数据。手工修改表格会断开原 SQL，保存编辑后的数据。SQL 报表保存时重新查询，已有报表是历史快照，不自动随业务数据更新。

助手回复支持 Markdown 标题、加粗、列表、引用、代码块、链接及表格，并在插入页面前清理不安全 HTML。生成的报表会直接出现在聊天中，图表卡片可切换柱状图、饼图、折线图等；顶部“本对话报表”入口可跳转到图表。历史会话中早期轮次的报表也会恢复，刷新页面保留当前会话。打开“报表工作室”可进一步编辑或导出图形。

## 登录与岗位权限

管理员账号名为 `admin`，密码在首次生成的 `data/demo-accounts.json` 中；其他岗位账号同样使用该文件里的独立随机密码。管理员进入“账号与权限”，可新建账号、重置密码、停用账号、分配客户编号，以及勾选岗位的可读字段和可执行业务。

| 演示账号 | 默认职责与数据范围 |
| --- | --- |
| `admin` | 全部业务、审计、账号与岗位授权、技能配置、关闭 Demo |
| `manager` | 全范围经营数据只读、分析报表 |
| `sales` | 默认仅负责 C001 客户及关联订单、工单、发货；可创建订单 |
| `production` | 生产、物料、设备、BOM；可排产、领料、报工；不显示价格和成本 |
| `warehouse` | 库存、采购收货、订单发货；不显示价格和成本 |
| `purchasing` | 供应商、原料成本与采购单；可创建采购单，不负责收货 |
| `finance` | 订单金额、原料成本及采购、发货数据只读 |

未授权菜单、字段、业务按钮和 Agent 写工具不可见；后端仍对每次请求校验。销售的客户范围同样作用于 SQL 聚合、关联查询、图表和 CSV。每个账号的聊天与报表独立保存，授权范围变化后旧范围结果隐藏；已有演示聊天和报表迁移至管理员账号。

实现说明与复现步骤见 [权限管理说明](docs/permissions.md)。真实 DeepSeek 岗位验证：`.\.venv\Scripts\python.exe scripts\acceptance_permissions.py`，结果见 [permissions-validation.json](docs/permissions-validation.json)。

## 技能配置

预制文件位于 `skills/*.json`：

- `order-to-production`：接单、排产、领料，3 步事务。
- `purchase-receive`：采购与到货入库，2 步事务，仅用于确认已到货。
- `daily-review`：生产经营晨报，自主查询并生成报表，不写业务数据。
- `stock-review`、`sales-review`、`production-review`：岗位内库存、订单交付和生产质量分析。

指令型技能用 `required_tables` 声明所需数据表；未声明依赖的纯指令技能默认仅管理员可见。事务型技能仅对拥有全部步骤业务权限的岗位展示，后端逐步校验数据范围。管理员管理技能，其他岗位仅能使用可用技能。

在网页“技能与流程”新增、编辑、启停和导出。放入新技能 JSON 文件也会自动发现，无需重启。网页配置保存在 `data/agent.sqlite3`，同 ID 的网页配置优先于文件默认值。配置格式及扩展方法见 [实际架构与接口](docs/demo-architecture.md)。

## 配置

| 环境变量 | 默认值 | 用途 |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | 无 | 模型密钥，仅后端使用 |
| `DEEPSEEK_MODEL` | `deepseek-flash` | 可改为账号支持的 `deepseek-v4-pro` |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | DeepSeek API 基地址 |
| `APP_PORT` | `8765` | 网页与 Agent API |
| `ERP_PORT` | `8766` | 受内部令牌保护的 ERP/MES 服务 |
| `DEMO_DATA_DIR` | 项目下 `data/` | 数据库目录 |
| `DEMO_RUNTIME_DIR` | 项目下 `.runtime/` | 启动状态、日志及关闭请求目录 |

启动脚本和管理进程使用相同的运行目录。独立测试可同时指定不同的端口、数据目录和运行目录。

模型使用官方 Chat Completions 工具接口，关闭思考模式，保留完整工具调用/返回配对。模型 ID 已通过实际账号 `/models` 验证。[DeepSeek 官方文档](https://api-docs.deepseek.com/guides/tool_calls/)

每任务最多 18 轮模型调用，轮次间检查 8 分钟预算；单次模型 HTTP 超时 100 秒，短暂网络错误、429 和部分 5xx 可重试，因此等待中的请求可能使总耗时超过轮次预算。没有密钥或 API 不可用时明确报错，不使用假 AI 替代。

## 验证

```powershell
# 业务规则、报表、SQL边界、技能和中断恢复测试
.\.venv\Scripts\python.exe -m pytest -q

# 真正调用DeepSeek，会产生API调用费用
.\.venv\Scripts\python.exe scripts\acceptance.py

# 静态检查；Node仅用于开发检查，不是运行依赖
node --check frontend/app.js
.\.venv\Scripts\python.exe -m compileall -q app scripts

# Markdown安全渲染、历史/实时图表、ECharts SVG与页面集成测试
npm ci --ignore-scripts
npm run test:frontend
```

真实 AI 验收在 8875/8876 端口启动独立系统，数据库位于 `.runtime/acceptance-*/data/`，不修改演示主库。核验模型工具轨迹及实际数据变化，结果写入 [acceptance-result.json](docs/acceptance-result.json)。首版交付结果见 [验收记录](docs/acceptance-report.md)。后续 Markdown 与聊天图表修复增加了13项前端测试，以及真实浏览器的历史图表恢复、柱状图/饼图切换检查；真实模型的定向验证见 [markdown-charts-validation.json](docs/markdown-charts-validation.json)。

## 文件与排障

```text
app/                  业务服务、Agent、适配器、报表、技能、启动管理
frontend/             无构建网页与本地ECharts
skills/               预制可配置技能
scripts/              依赖安装与真实AI验收脚本
tests/                业务及边界测试
data/erp.sqlite3      ERP+MES业务数据库
data/agent.sqlite3    对话、执行轨迹、报表、技能配置
.runtime/             日志、进程状态、独立验收数据
docs/                 参考文档、实际架构、验收证据
```

- 启动失败：终端会显示本次启动日志路径及具体原因（例如端口占用、数据库错误）。每次尝试使用独立的 `.runtime/launcher-<ID>.err.log` / `.out.log`，避免同时启动覆盖日志；当前服务日志为 `.runtime/erp.log` 和 `.runtime/agent.log`。端口占用可设置不同的 `APP_PORT` 和 `ERP_PORT` 后重启。
- AI 报错：检查密钥、余额、模型名和网络。密钥不显示在网页或日志中。
- 页面会话失效：重新登录。登录有效期为8小时；退出、停用账号、重置密码或修改授权会撤销现有登录。
- 备份：关闭 Demo 后复制 `data/`。通常不需要清空数据库；删库会丢失演示操作记录。

这是支持多个岗位账号的单机 Demo，默认仅监听 `127.0.0.1`。未实现生产级多租户身份、财务总账、PLC 对接、排产优化器或任意代码执行沙箱。对接层是私有 Python/HTTP 工具协议，没有 MCP 服务、公开工具发现或通用 HTTP 执行工具；协议选择本身不能阻止掌握本机权限和源码的人开发其他客户端。
