# 指纹成对对比（Fingerprint Pair Compare）

机器 A 部署本分支后即可使用「指纹对比」菜单。

## 功能

1. 导入 batmatch_out 风格 zip（每对目录含 2 张 bmp + 各侧多层模板）
2. 按指位 / 批次 / 分数 / 特征类型 / 算法版本筛选配对
3. 对比页左右双栏，勾选 Bidiso / neuiso（及后续扩展类型）即时叠加细节点
4. 同算法多 `algo_version` 用不同颜色区分

## 存储

| 类型 | 路径 |
|------|------|
| 指纹 bmp | `upload/{YYYYMMDD}/{category_id}/{uuid}.bmp`（沿用现有） |
| 特征模板 | `templates/{YYYYMMDD}/{uuid}.{suffix}`（独立目录） |

MinIO 下同样是相对路径对象键，前缀不变。

## ISO 解码参数

对齐样本标定（decodeISOV1.1）：

- `setlen` 默认 **0**
- `setang` 默认 **256**

按 `fingerprint_layer_type` 可为每种特征类型单独配置。

## 机器 A 上线

1. 拉取本分支并重启 backend / web
2. MySQL 会在启动时自动 `CREATE TABLE IF NOT EXISTS`（也可手动执行 `sql/fingerprint_pairs.sql`）
3. 确保运行环境可写项目根下 `templates/`（或 MinIO 可写对应前缀）
4. 浏览器打开「指纹对比」→ 导入小样本 zip（勿提交整包 batmatch_out）

## API 摘要

- `GET /api/fingerprints/layer-types/` — 动态勾选配置
- `POST /api/fingerprints/layer-types/` — 管理员新增特征类型（扩到 6 种无需改前端结构）
- `POST /api/fingerprints/pairs/import-zip/` — 导入 zip
- `GET /api/fingerprints/pairs/` — 列表筛选
- `GET /api/fingerprints/pairs/{id}/compare/?layers=bidiso,neuiso&versions=1.0` — 对比数据

## 扩展特征类型

管理员调用：

```json
POST /api/fingerprints/layer-types/
{
  "layer_key": "newtype",
  "label": "NewType",
  "color": "#43a047",
  "suffixes": "newtype",
  "default_setlen": 0,
  "default_setang": 256
}
```

导入带 `.newtype` 后缀的模板后，对比页勾选框会自动出现。

## 非目标（本期不做）

bmp→模板提取引擎、Neurotec/ISOTemplateView 集成、嵌入式固件。
