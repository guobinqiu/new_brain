# Config Profile Split Implementation Plan

**Goal:** 把评估配置拆成固定索引结构的 profile，避免通过 `enable` 在同一个 yaml 里切换会影响索引结构的组件。

**Architecture:** `local.yaml`、`docker-cpu.yaml`、`docker-gpu.yaml` 保持运行入口；评估 profile 按 store + dense + vector sparse 组合拆分。每个 yaml 只声明当前启用组件，`sparse.app` 永远存在，`sparse.vector` 只在该 profile 需要写入向量库 sparse 索引时存在。

**Tech Stack:** YAML 配置、`backend/loader.py`、`backend/schema.py`、pytest。

## Global Constraints

- 默认使用 `local.yaml`。
- `CONFIG_FILE` 可以是配置文件名或完整路径。
- Chroma local 不配置 vector sparse。
- `/api/config` 根据 `sparse.vector` 是否存在推导 `available_modes`。

---

### Task 1: Profile Inventory Tests

**Files:**
- Modify: `backend/tests/unit/test_config_profiles.py`

**Interfaces:**
- Consumes: `backend/config/*.yaml`
- Produces: 明确的 profile 文件清单和固定结构断言。

- [ ] 写失败测试，断言 profile 文件包含：
  - `local.yaml`
  - `docker-cpu.yaml`
  - `docker-gpu.yaml`
  - `qdrant-bge-base.yaml`
  - `qdrant-bge-m3.yaml`
  - `chroma-bge-base.yaml`
  - `chroma-bge-m3.yaml`
  - `milvus-bge-base.yaml`
  - `milvus-bge-m3.yaml`
  - `milvus-builtin-bm25.yaml`
- [ ] 写失败测试，断言这些 yaml 的 `dense`、`store`、`ocr` 都是单组件对象，不再是候选 map。
- [ ] 写失败测试，断言 rerank 只能是单组件对象或 `null`。

### Task 2: Loader Compatibility Cleanup

**Files:**
- Modify: `backend/loader.py`
- Modify: `backend/tests/unit/test_config_loader.py`

**Interfaces:**
- Consumes: 单组件 yaml 和历史测试内联候选 map
- Produces: 能加载单组件 yaml；测试内联样例迁移成单组件结构。

- [ ] 删除生产 profile 对多候选 `enable` 的依赖。
- [ ] 保留 loader 对临时测试配置的简单字符串写法支持。
- [ ] 更新测试里旧 profile 文件名的引用到拆分后的新文件名。

### Task 3: Config Files

**Files:**
- Rename/Delete/Create under `backend/config/`

**Interfaces:**
- Consumes: 当前 store、dense、sparse、rerank、ocr 配置字段
- Produces: 固定索引结构 profile。

- [ ] `qdrant-bge-base.yaml`：Qdrant + BGE-base dense + app BM25。
- [ ] `qdrant-bge-m3.yaml`：Qdrant + BGE-M3 dense + BGE-M3 vector sparse + app BM25。
- [ ] `chroma-bge-base.yaml`：Chroma + BGE-base dense + app BM25。
- [ ] `chroma-bge-m3.yaml`：Chroma + BGE-M3 dense + app BM25。
- [ ] `milvus-bge-base.yaml`：Milvus + BGE-base dense + app BM25。
- [ ] `milvus-bge-m3.yaml`：Milvus + BGE-M3 dense + BGE-M3 vector sparse + app BM25。
- [ ] `milvus-builtin-bm25.yaml`：Milvus + BGE-base dense + Milvus BM25 vector sparse + app BM25。
- [ ] `milvus-lite-bge-base.yaml`：Milvus Lite + BGE-base dense + app BM25。
- [ ] `milvus-lite-bge-m3.yaml`：Milvus Lite + BGE-M3 dense + BGE-M3 vector sparse + app BM25。
- [ ] `milvus-lite-builtin-bm25.yaml`：Milvus Lite + BGE-base dense + Milvus BM25 vector sparse + app BM25。

### Task 4: Docs

**Files:**
- Modify: `README.md`
- Modify: `docs/architecture.md`

**Interfaces:**
- Consumes: 新配置文件清单
- Produces: 文档说明固定 profile 与运行时可切换项的边界。

- [ ] README 配置表更新为新文件名。
- [ ] 架构文档配置目录和 Milvus 说明更新。
- [ ] 说明索引结构由 profile 固定，前端只切查询参数。

### Task 5: Verification

**Commands:**
- `backend/.venv/bin/python -m pytest backend/tests/unit/test_config_loader.py backend/tests/unit/test_config_profiles.py -q`
- `backend/.venv/bin/python -m pytest backend/tests/unit -q`
- `npm --prefix frontend run build`
