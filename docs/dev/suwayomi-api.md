# Suwayomi GraphQL API 参考

本文档记录插件实际使用的 Suwayomi-Server GraphQL API，基于实际测试验证（非文档推断）。

## 端点

- **GraphQL**: `POST /api/graphql`
- **Playground**: `GET /api/graphql`（浏览器访问可交互式探索）

## 认证

由 `serverConfig.authMode` 决定：

| 模式 | 行为 |
|------|------|
| `NONE` | 无需认证 |
| `BASIC_AUTH` | HTTP Basic 认证（`Authorization: Basic base64(user:pass)`） |
| `UI_LOGIN` | JWT 认证，通过 `login` mutation 获取 token |

## 插件使用的查询和变更

### sources — 列出所有源

```graphql
query {
  sources {
    nodes {
      id            # LongString (返回为字符串)
      name
      lang
      displayName
      supportsLatest
    }
  }
}
```

### fetchSourceManga — 搜索/浏览源

```graphql
mutation($sid: LongString!, $q: String!, $p: Int!) {
  fetchSourceManga(input: {
    source: $sid      # 必须是字符串，如 "524579092615598717"
    type: SEARCH       # SEARCH / POPULAR / LATEST
    page: $p
    query: $q
  }) {
    mangas {
      id title url sourceId status thumbnailUrl
      inLibrary author artist description genre
    }
    hasNextPage
  }
}
```

**注意**：`source` 的 GraphQL 类型是 `LongString`，不是 `Long`。变量声明必须用 `$sid:LongString!`，JSON 值必须是字符串。

### manga — 获取单个漫画

```graphql
query($id: Int!) {
  manga(id: $id) {
    id title url sourceId status thumbnailUrl
    inLibrary author artist description genre
    chapters { totalCount }
  }
}
```

### mangas — 按标题搜索库内漫画

```graphql
query($t: String!, $n: Int!) {
  mangas(
    filter: { title: { includes: $t } }   # 子串匹配
    first: $n
  ) {
    nodes {
      id title url sourceId status thumbnailUrl
      inLibrary author artist description genre
    }
  }
}
```

**注意**：使用 `filter` + `includes`，不是 `condition` + `ilike`。`includes` 是大小写敏感的子串匹配。

### mangas — 获取书库漫画

```graphql
query {
  mangas(condition: { inLibrary: true }) {
    nodes {
      id title url sourceId status thumbnailUrl
      inLibrary author artist description genre
    }
  }
}
```

### manga.chapters — 获取章节列表

```graphql
query($id: Int!) {
  manga(id: $id) {
    chapters {
      nodes {
        id url name chapterNumber uploadDate
        isRead isDownloaded isBookmarked
        lastPageRead sourceOrder mangaId pageCount
      }
    }
  }
}
```

**注意**：所有数字字段（`id`, `chapterNumber`, `mangaId` 等）在 JSON 中返回为字符串，需要显式 `int()` / `float()` 转换。

### fetchChapterPages — 获取章节页面 URL

```graphql
mutation($cid: Int!) {
  fetchChapterPages(input: { chapterId: $cid }) {
    pages     # List[String] — 相对路径，如 "/api/v1/manga/42/chapter/5/page/0"
  }
}
```

页面完整 URL = `server_url` + 相对路径。

### enqueueChapterDownloads — 加入下载队列

```graphql
mutation($ids: [Int!]!) {
  enqueueChapterDownloads(input: { ids: $ids }) {
    downloadStatus { state }
  }
}
```

### updateLibrary — 触发书库更新

```graphql
mutation {
  updateLibrary(input: { categories: null }) {
    updateStatus { isRunning }
  }
}
```

`categories: null` 表示更新所有分类。

### login — JWT 认证

```graphql
mutation($u: String!, $p: String!) {
  login(input: { username: $u, password: $p }) {
    accessToken
    refreshToken
  }
}
```

### refreshToken — 刷新 JWT

```graphql
mutation($r: String!) {
  refreshToken(input: { refreshToken: $r }) {
    accessToken
  }
}
```

## 关键数据类型

### MangaType

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | Int | 漫画 ID |
| `sourceId` | Long | 所属源 ID |
| `url` | String | 源内 URL |
| `title` | String | 标题 |
| `status` | MangaStatus | `ONGOING` / `COMPLETED` / `LICENSED` / `PUBLISHING_FINISHED` / `CANCELLED` / `ON_HIATUS` / `UNKNOWN` |
| `thumbnailUrl` | String? | 缩略图 URL |
| `inLibrary` | Boolean | 是否在书库中 |
| `author` | String? | 作者 |
| `artist` | String? | 画师 |
| `description` | String? | 简介 |
| `genre` | [String] | 标签列表 |

### ChapterType

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | Int | 章节 ID |
| `url` | String | 源内 URL |
| `name` | String | 章节名称 |
| `chapterNumber` | Float | 章节编号（可能有小数，如 38.2） |
| `uploadDate` | Long | 上传时间戳 |
| `isRead` | Boolean | 已读 |
| `isDownloaded` | Boolean | 已下载 |
| `isBookmarked` | Boolean | 已收藏 |
| `mangaId` | Int | 所属漫画 ID |
| `pageCount` | Int | 页数 |

### SourceType

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | Long | 源 ID（大整数，如 `524579092615598717`） |
| `name` | String | 源标识名 |
| `lang` | String | 语言代码（如 `zh`, `en`） |
| `displayName` | String | 显示名称 |
| `supportsLatest` | Boolean | 是否支持「最新」列表 |

## 已知的 API 兼容性问题

| 问题 | 表现 | 插件处理 |
|------|------|----------|
| `Long` 类型不存在 | `Unknown type 'Long'` 错误 | 使用 `LongString` 声明变量，传字符串值 |
| `condition.title` 不接受过滤器 | 类型错误 | 使用 `filter: { title: { includes: ... } }` |
| `ilike` 操作符不存在 | `Unknown field` 错误 | 使用 `includes`（大小写敏感） |
| 数字字段返回字符串 | `"id": "287"` 而非 `"id": 287` | `from_dict()` 中 `int()` / `float()` 强制转换 |
| source:0 (Local source) 搜索崩溃 | NullPointerException | 搜索时跳过 ID 为 `"0"` 的源 |

## 分页

GraphQL 使用 Relay 风格分页，但插件目前仅使用 `first` + `nodes` 简单分页：

```graphql
mangas(first: 10, after: null) {
  nodes { ... }
  pageInfo { hasNextPage endCursor }
  totalCount
}
```
