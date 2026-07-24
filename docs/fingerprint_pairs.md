# 指纹配对对比（业务表驱动）

机器 A 部署本分支后即可使用「指纹对比」菜单。

## 主线流程（本期）

```text
t_match_result_image
  image_reg / image_match  (= bmp stem，与写回一致)
       │
       ├─► T_CAP_FP_DATA.cap_image_id     → 图路径 fingerprint_image
       └─► T_FEATURE_RECORD.fp_image_id   → Bidiso / Neuiso 路径
              → ISO 解码 → 双栏叠加
```

筛选留意：`t_match_result_image.data_set_code`（与 `T_CAP_FP_DATA.dataset_code` 对应，如 `PK_5W`）。

## 功能

1. 导入 batmatch zip（可选路径写回 `T_CAP_FP_DATA` + `T_FEATURE_RECORD`）
2. 顶栏切换 **配对 / 单图**
   - 配对：左树 `t_match_result_image`；右栏双栏 `image_reg` / `image_match`
   - 单图：左树 `T_CAP_FP_DATA`；右栏单栏叠加
3. 方向键切换上一项 / 下一项
4. **评测指标**子页（顶栏「评测指标」）：按 `data_set_code` + 分数列计算 EER/FMR/DET

## 评测指标（子页）

路由：`/fingerprint-eval`（菜单隐藏，从指纹浏览跳转）。

| 字段 | 用途 |
|------|------|
| `data_set_code` | 评测单位 |
| `score`（默认）、`NeuNTms`、`Bionems`、`BioIdms`、`HXms`、`AlgVersion` | 算法分数列；扫描后「Genuine+Impostor 均有数值」才可选 |
| `sameflag` | `1`=Genuine，`0`=Impostor |

**已实现：** EER（含粗略 CI）、FMR100/1000/10000、ZeroFMR、ZeroFNMR、分数分布、FMR(t)/FNMR(t)、DET。  
接受规则：`score >= threshold`。

**未实现（表中无对应采集字段）：** REJenroll / REJnga / REJnira、注册/比对耗时、模板大小、内存。

| 方法 | 路径 | 作用 |
|------|------|------|
| GET | `/api/fingerprints/biz/eval/meta/` | 数据集列表 + 可用分数列 |
| GET | `/api/fingerprints/biz/eval/report/` | 准确率表 + 曲线数据 |

查询参数：`connection_id` 或 `db_alias`、`database`、`dataset_code`、`score_column`。

## API（业务浏览）

| 方法 | 路径 | 作用 |
|------|------|------|
| GET | `/api/fingerprints/biz/meta/` | `data_set_code` 列表 + layer-types |
| GET | `/api/fingerprints/biz/pairs/` | 配对分页（`dataset_code`/`keyword`） |
| GET | `/api/fingerprints/biz/pairs/{id}/view/` | `mode=pair`，`panels[reg,match]` |

`pair_meta` 仅含：`id`、`image_reg`、`image_match`、`data_set_code`（浏览侧不含 score 等指标）。

单样本兼容接口仍保留：`/biz/samples/`、`/biz/samples/{cap}/view/`。

## 路径写回

导入写回后两侧 stem 须能在 `T_CAP_FP_DATA` 命中，配对行才能双栏出图。

| 目标 | 写入 |
|------|------|
| `T_CAP_FP_DATA` | `cap_image_id`=stem；`dataset_code`=`PK_5W`；路径→`fingerprint_image` |
| `T_FEATURE_RECORD` | `fp_image_id`=stem；Bidiso→`feature_ara_data`；Neuiso→`feature_neuro_data` |

## 存储 / ISO

| 类型 | 路径 |
|------|------|
| 指纹 bmp | `upload/{YYYYMMDD}/{category_id}/{uuid}.bmp` |
| 特征模板 | `templates/{YYYYMMDD}/{uuid}.{suffix}` |

ISO：`setlen=0`，`setang=256`（可按 layer-type 配置）。

## 非本期

- 删除旧 `fingerprint_pair` 导入旁路
- 效率/内存类指标（缺采集字段）
