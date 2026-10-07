# KitPrep 中央厨房 BOM 备料

按菜品 BOM 展开订单行、合并同原料需求，对照库存计算缺料并生成备料单。

技术栈：Python 3.12 / FastAPI / SQLAlchemy / PostgreSQL / Vue 3 / TypeScript / Vite

## 启动

```bash
docker compose up --build
```

| 服务 | 地址 |
| --- | --- |
| 前端 | http://localhost:5000 |
| API | http://localhost:10100 |
| API 文档 | http://localhost:10100/docs |
| Postgres | localhost:5451 |

健康检查：`GET http://localhost:10100/api/health`

## 使用说明

1. 在「菜品」「BOM定额」维护中央厨房出品与用料树；定额页可填写出品率 / 用料出成率（0, 1]，留空 = 1。
2. 在「订单」「库存」确认当日需求与现有库存。
3. 打开「备料单」点击「生成备料单」落库；备料台与缺料页只读已落库的当前有效单，不按定义现算。
4. 在「缺料」查看 need − stock 为正的原料。

出成率语义：

- 需求 = 份数 × 定额 ÷ (出品率 × 用料率)，率改小需求变大；填 1 或未写过与一层展开一致。
- 定额页保存与当前有效备料单同一事务：要么整张按新率重写占用列与缺料贴，要么整张退回（出成率 0 或大于 1 全部退回保存前）。
- 已钉死的历史备料单不随保存改字；库存结存不受保存影响。

## 开发与测试

```bash
docker compose exec api pytest -q
```
