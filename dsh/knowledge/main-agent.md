# 主布局 Agent 知识卡，v1

当前后端是 toy 教学几何。宏中心加权 HPWL 是代理指标，不能推断时序、布线拥塞、功耗或真实芯片 PPA。

另有独立的 iEDA 真实 EDA 工具：mp_ieda_status 检查运行环境，mp_ieda_run 执行固定 sky130_gcd 的 iFP+iPL。它不用教学 state_id，不改变教学布局。GCD 没有硬宏，只验证标准单元布局接入；报告 HPWL 是 DBU，不可和 toy 抽象单位直接比较。iPL 自检不是独立制造级签核，未测完整 PPA。

先 query_design 获取真实状态，可通过 query=nets 查询连接关系。每次调用带当前 state_id。位置变化后旧状态不得继续使用。

工具 neighbor_v1 在网格步长的五倍邻域枚举单宏移动；swap_v1 交换两宏左下角。尺寸不同可能非法，由宿主独立检验。

固定工具遵守 fixed macros、blockages、spacing、grid 和 core boundary。HPWL 由宿主计算，不信任模型自报得分。

RAG 检索结果是参考材料，当前坐标和指标必须从设计查询得到。英文关键词示例：HPWL、fixed、grid、swap、context。

无改善可以改用另一种固定工具，也可以说明缺口后停止。DSH 桌面版支持 mp_request_tool 委托独立 Algorithm Agent；主 Agent 自己不编写或运行源码。

Algorithm Agent 首版只支持 weighted_macro_center_hpwl 目标。先交 ModelSpec，再生成 propose_moves Python 算子，最后在 Windows AppContainer 测试；宿主独立评价。主任务调用 mp_algorithm_step 推进阶段，交付状态 delivered 不代表布局已修改。

mp_run_generated 执行已交付工具，每次在当前状态重验后才接受改进。工具仅在当前会话登记，单快照测试不代表跨设计泛化。每任务最多两次 Maker 请求，每请求最多三次模型调用、两版代码；不能靠重新请求绕过停止规则。
