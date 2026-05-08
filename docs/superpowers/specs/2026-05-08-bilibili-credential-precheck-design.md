# Bilibili 凭据缺失时的导入拦截

## 背景

用户在 `/import` 页面提交 B 站视频 URL 后，请求一路落到 Celery worker 才发现没有 Bilibili
SESSDATA，`bilibili_api.video.Video.get_player_info` 抛 `CredentialNoSessdataException`，
source 记录卡在 `failure` 状态。用户从前端看不到失败原因，也得不到"该去哪儿配置"的引导。

实际报错（节选）：

```
worker-1 | ERROR Ingestion failed for source ...: Credential 类未提供 sessdata 或者为空。
worker-1 |   File "/app/app/tools/extractors/bilibili.py", line 196, in _extract_single_page
worker-1 |     subtitle_info = await v.get_subtitle(cid=cid)
```

设置页 `/settings` 已经实现了完整的 B 站 QR 扫码登录流程，缺失的是**导入前的拦截 + 跳转引导**。

## 目标

- 用户在导入 B 站视频且未登录时，**导入按钮在提交前就被拦截**。
- 给出明确的 inline 提示 + "前往设置" 跳转按钮。
- 不再产生一条注定失败的 source 记录。
- 即便绕过前端（脚本/curl）也要兜得住，后端返回结构化错误码。

不在范围内：

- 修改 QR 码登录流程本身。
- YouTube 凭据拦截（YouTube 无对应凭据需求）。
- 无凭据时走 Whisper 兜底（产品决定走"明确告知"，而不是悄悄降级）。

## 架构

两层防护：

1. **前端预检**：`/import` 页面进入或切换到 B 站 tab 时调用 `getBilibiliStatus()`，未登录则渲染
   inline banner 并禁用"开始导入"。
2. **后端兜底**：`POST /api/v1/sources` 在判定 `source_type == "bilibili"` 后立即检查凭据，
   缺失则返回 `412` + 结构化错误码，**早于** source 写库和 Celery 派发。

凭据来源与 worker 保持完全一致：先查 DB (`BilibiliCredential.sessdata_encrypted`)，再回退到
env (`settings.bilibili_sessdata`)。

```
[用户在 /import 提交]
       │
       ▼
[前端 getBilibiliStatus()]──未登录──> [inline banner + 跳转按钮，禁用提交]
       │ 已登录
       ▼
[POST /api/v1/sources]
       │
       ├── source_type == "bilibili" ?
       │      ├── 有凭据 (DB or env) → 写库 + 派发 Celery
       │      └── 无凭据 → 412 {"code": "bilibili_credential_required"}
       │
       └── 其他类型 → 原流程
```

## 后端改动

### 新增 helper：`has_bilibili_credential`

放在 `backend/app/services/bilibili_credential.py`（新文件）。worker 中现有的
`_get_bilibili_credential` 也复用这个 helper 取凭据，避免两份判定逻辑漂移。

```python
# backend/app/services/bilibili_credential.py
async def has_bilibili_credential(db: AsyncSession) -> bool:
    """是否存在可用的 Bilibili 凭据（DB 或 env）。"""
    settings = get_settings()
    result = await db.execute(select(BilibiliCredential).limit(1))
    stored = result.scalar_one_or_none()
    if stored and stored.sessdata_encrypted:
        return True
    return bool(settings.bilibili_sessdata)
```

### 修改 `POST /api/v1/sources` (`create_source`)

在 `_detect_source_type` 之后、`extract_content_key` 之前插入拦截：

```python
if source_type == "bilibili":
    if not await has_bilibili_credential(db):
        raise HTTPException(
            status_code=412,
            detail={
                "code": "bilibili_credential_required",
                "message": "导入 B 站视频需要先登录 B 站账号才能抓取字幕。",
            },
        )
```

选择 `412 Precondition Failed`：语义贴切（前置条件未满足，非用户输入错误也非鉴权失败）。

### 修改 `GET /setup/bilibili/status`

让 `logged_in` 字段反映 worker 实际可用的凭据，而不只是 DB 状态：

```python
# 改动后
has_db = bool(credential and credential.sessdata_encrypted)
has_env = bool(get_settings().bilibili_sessdata)
return {
    "logged_in": has_db or has_env,
    "dedeuserid": credential.dedeuserid if credential else None,
    "source": "db" if has_db else ("env" if has_env else None),
}
```

新增的 `source` 字段帮助前端区分"用户登录的 DB 凭据"和"运维通过 env 注入的凭据"。本 spec
范围内只保证 `logged_in` 语义准确，settings 页 UI 不做调整（env-only 是少数运维场景，
现有"已登录"展示足够用，避免在本次改动里牵涉设置页交互）。

## 前端改动

### `lib/api.ts`

- `getBilibiliStatus` 返回类型加上可选的 `source` 字段，保持向后兼容。
- `apiFetch` / `responseError` 已能解析 detail，确认 412 错误能拿到 `detail.code`；如果当前
  `responseError` 把 detail 平铺到 `message`，需要让 import 页面能再次解析 `code`。

### `app/import/page.tsx`

新增状态：

```tsx
const [biliLoggedIn, setBiliLoggedIn] = useState<boolean | null>(null);
```

切换到 B 站 tab 时（含初始挂载且默认就是 bilibili）触发 `getBilibiliStatus()` 写入状态。
`null` 表示加载中，避免闪现 banner。

UI：

```tsx
{sourceType === "bilibili" && biliLoggedIn === false && (
  <div className="mb-6 flex items-start gap-2 p-3 rounded-lg bg-red-50 border border-red-200 text-sm text-red-700">
    <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
    <div className="flex-1">
      <div>导入 B 站视频需要先登录 B 站账号才能抓取字幕。</div>
      <button
        onClick={() => router.push("/settings")}
        className="mt-2 text-xs font-medium text-red-700 underline hover:no-underline bg-transparent border-none cursor-pointer p-0"
      >
        前往设置登录 →
      </button>
    </div>
  </div>
)}
```

按钮禁用：

```tsx
const disableSubmit =
  !canSubmit ||
  loading ||
  (sourceType === "bilibili" && biliLoggedIn === false);
```

`handleImport` 错误处理：

```tsx
catch (err) {
  if (err && typeof err === "object" && "code" in err && err.code === "bilibili_credential_required") {
    setBiliLoggedIn(false);  // 凭据被外部删除的边缘场景
    return;
  }
  setErrorMsg(err instanceof Error ? err.message : "导入失败...");
}
```

## 错误处理

- 前端 `getBilibiliStatus()` 调用本身失败（网络错）：`biliLoggedIn` 保持 `null`，banner 不展示，
  允许用户照常提交，由后端兜底返回 412。这个降级方向是有意的——状态接口不可用时不该硬卡死用户。
- 后端 412：前端解析 `detail.code` 切换 banner；老客户端也能从 `detail.message` 读到中文文案。
- env-only 凭据：前端 `logged_in: true`，导入正常；设置页保持现状（不在本次范围）。

## 测试

### 后端 (`backend/tests/`)

- `test_bilibili_credential_helper.py`（新）：
  - DB 有 sessdata → True
  - DB 无 但 env 有 → True
  - 都没有 → False
- `tests/api/test_sources.py`（已存在文件 or 新增）：
  - 提交 bilibili URL，无凭据 → 412 + `code: bilibili_credential_required`
  - 提交 bilibili URL，有 DB 凭据 → 201（task 派发，使用现有 mock）
  - 提交 youtube URL 不受影响
- `test_setup.py`：
  - `/setup/bilibili/status` 在 env-only 下返回 `logged_in: true, source: "env"`

### 前端 (`frontend/src/__tests__/`)

- `import-page.test.tsx`（新或扩展）：
  - 渲染时 `getBilibiliStatus` mock 返回 `logged_in: false` → banner 出现，按钮 disabled
  - mock 返回 `logged_in: true` → banner 不出现，可提交
  - 切换到 PDF tab → banner 不展示
  - 点击"前往设置登录"调用 `router.push("/settings")`

## 改动清单

| 文件 | 改动 |
|------|------|
| `backend/app/services/bilibili_credential.py` | 新增 helper |
| `backend/app/api/routes/sources.py` | `create_source` 内插入拦截 |
| `backend/app/api/routes/setup.py` | `bilibili_status` 纳入 env 检测，返回 `source` 字段 |
| `backend/app/worker/tasks/content_ingestion.py` | `_get_bilibili_credential` 复用新 helper（提取共享逻辑） |
| `backend/tests/...` | 凭据 helper 单测 + sources 路由 412 测试 |
| `frontend/src/lib/api.ts` | `getBilibiliStatus` 返回类型扩展 |
| `frontend/src/app/import/page.tsx` | 预检 + banner + 按钮禁用 + 412 处理 |
| `frontend/src/__tests__/import-page.test.tsx` | 预检 UX 单测 |

## 验收标准

1. 未配置 B 站凭据时打开 `/import`，B 站 tab 默认显示红色 banner，"开始导入"按钮 disabled。
2. 点击 banner 中的"前往设置登录"跳到 `/settings`，能完成 QR 扫码并返回 `/import` 后 banner 消失。
3. 直接 `curl POST /api/v1/sources` 一个 bilibili URL 在无凭据时返回 412 + 结构化 detail，不再
   产生 source 记录。
4. 已配置凭据（DB 或 env）时 `/import` 与之前完全一致地工作。
5. 后端单测和前端单测全部通过。
