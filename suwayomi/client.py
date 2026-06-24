from __future__ import annotations

import base64
from typing import Any

import aiohttp

from astrbot.api import logger

from .models import Chapter, Manga, SearchResult, Source


class SuwayomiError(Exception):
    pass


class SuwayomiClient:
    def __init__(self, server_url: str, auth_mode: str, username: str, password: str):
        self.server_url = server_url.rstrip("/")
        self.auth_mode = auth_mode
        self._session: aiohttp.ClientSession | None = None

        self._headers: dict[str, str] = {"Content-Type": "application/json"}

        if auth_mode == "basic" and username:
            cred = base64.b64encode(f"{username}:{password}".encode()).decode()
            self._headers["Authorization"] = f"Basic {cred}"

        self._jwt_access_token: str | None = None
        self._jwt_refresh_token: str | None = None
        self._username = username
        self._password = password

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    def build_image_url(self, relative_path: str) -> str:
        return f"{self.server_url}{relative_path}"

    async def _ensure_jwt(self):
        if self.auth_mode != "jwt" or self._jwt_access_token:
            return
        result = await self._raw_query(
            'mutation($u:String!,$p:String!){login(input:{username:$u,password:$p}){accessToken refreshToken}}',
            {"u": self._username, "p": self._password},
        )
        login_data = result["login"]
        self._jwt_access_token = login_data["accessToken"]
        self._jwt_refresh_token = login_data["refreshToken"]

    async def _raw_query(self, query: str, variables: dict | None = None) -> dict[str, Any]:
        await self._ensure_jwt()

        headers = dict(self._headers)
        if self._jwt_access_token:
            headers["Authorization"] = f"Bearer {self._jwt_access_token}"

        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables

        session = await self._get_session()
        url = f"{self.server_url}/api/graphql"

        async with session.post(url, json=payload, headers=headers) as resp:
            if resp.status == 401 and self.auth_mode == "jwt" and self._jwt_refresh_token:
                await self._refresh_jwt()
                headers["Authorization"] = f"Bearer {self._jwt_access_token}"
                async with session.post(url, json=payload, headers=headers) as retry_resp:
                    data = await retry_resp.json()
            else:
                data = await resp.json()

        if "errors" in data and data["errors"]:
            raise SuwayomiError(data["errors"][0].get("message", "Unknown GraphQL error"))

        return data.get("data", {})

    async def _refresh_jwt(self):
        result = await self._raw_query(
            'mutation($r:String!){refreshToken(input:{refreshToken:$r}){accessToken}}',
            {"r": self._jwt_refresh_token},
        )
        self._jwt_access_token = result["refreshToken"]["accessToken"]

    async def get_sources(self) -> list[Source]:
        data = await self._raw_query(
            'query{sources{nodes{id name lang displayName supportsLatest}}}'
        )
        return [Source.from_dict(s) for s in data["sources"]["nodes"]]

    async def search_manga(self, source_id: int, query: str, page: int = 1) -> SearchResult:
        data = await self._raw_query(
            'mutation($sid:Long!,$q:String!,$p:Int!){fetchSourceManga(input:{source:$sid,type:SEARCH,page:$p,query:$q}){mangas{id title url sourceId status thumbnailUrl inLibrary author artist description genre}hasNextPage}}',
            {"sid": source_id, "q": query, "p": page},
        )
        return SearchResult.from_dict(data["fetchSourceManga"])

    async def get_popular(self, source_id: int, page: int = 1) -> SearchResult:
        data = await self._raw_query(
            'mutation($sid:Long!,$p:Int!){fetchSourceManga(input:{source:$sid,type:POPULAR,page:$p}){mangas{id title url sourceId status thumbnailUrl inLibrary author artist description genre}hasNextPage}}',
            {"sid": source_id, "p": page},
        )
        return SearchResult.from_dict(data["fetchSourceManga"])

    async def get_manga(self, manga_id: int) -> Manga:
        data = await self._raw_query(
            'query($id:Int!){manga(id:$id){id title url sourceId status thumbnailUrl inLibrary author artist description genre chapters{totalCount}}}',
            {"id": manga_id},
        )
        return Manga.from_dict(data["manga"])

    async def get_chapters(self, manga_id: int) -> list[Chapter]:
        data = await self._raw_query(
            'query($id:Int!){manga(id:$id){chapters{nodes{id url name chapterNumber uploadDate isRead isDownloaded isBookmarked lastPageRead sourceOrder mangaId pageCount}}}}',
            {"id": manga_id},
        )
        return [Chapter.from_dict(c) for c in data["manga"]["chapters"]["nodes"]]

    async def fetch_chapter_pages(self, chapter_id: int) -> list[str]:
        data = await self._raw_query(
            'mutation($cid:Int!){fetchChapterPages(input:{chapterId:$cid}){pages}}',
            {"cid": chapter_id},
        )
        return data["fetchChapterPages"]["pages"]

    async def enqueue_download(self, chapter_ids: list[int]) -> None:
        await self._raw_query(
            'mutation($ids:[Int!]!){enqueueChapterDownloads(input:{ids:$ids}){downloadStatus{state}}}',
            {"ids": chapter_ids},
        )

    async def update_library(self) -> None:
        await self._raw_query(
            'mutation{updateLibrary(input:{categories:null}){updateStatus{isRunning}}}'
        )

    async def get_library_mangas(self) -> list[Manga]:
        data = await self._raw_query(
            'query{mangas(condition:{inLibrary:true}){nodes{id title url sourceId status thumbnailUrl inLibrary author artist description genre}}}'
        )
        return [Manga.from_dict(m) for m in data["mangas"]["nodes"]]
