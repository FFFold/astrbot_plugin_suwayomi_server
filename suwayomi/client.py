from __future__ import annotations

import asyncio
import base64
import json
import time
from typing import Any

import aiohttp

from astrbot.api import logger

from .models import Chapter, Manga, SearchResult, Source


class SuwayomiError(Exception):
    pass


_SOURCES_CACHE_TTL = 60


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
        self._jwt_lock = asyncio.Lock()
        self._sources_cache: tuple[float, list[Source]] | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    @property
    def auth_headers(self) -> dict[str, str]:
        h = {}
        if "Authorization" in self._headers:
            h["Authorization"] = self._headers["Authorization"]
        elif self.auth_mode == "jwt" and self._jwt_access_token:
            h["Authorization"] = f"Bearer {self._jwt_access_token}"
        return h

    def build_image_url(self, relative_path: str) -> str:
        return f"{self.server_url}{relative_path}"

    async def _ensure_jwt(self):
        if self.auth_mode != "jwt" or self._jwt_access_token:
            return

        async with self._jwt_lock:
            if self._jwt_access_token:
                return
            await self._login_jwt()

    async def _login_jwt(self):
        status, response = await self._post_graphql(
            'mutation($u:String!,$p:String!){login(input:{username:$u,password:$p}){accessToken refreshToken}}',
            {"u": self._username, "p": self._password},
        )
        result = self._response_data(status, response)
        login_data = result.get("login")
        if not isinstance(login_data, dict):
            raise SuwayomiError("JWT login response is missing login data")
        access_token = login_data.get("accessToken")
        refresh_token = login_data.get("refreshToken")
        if not access_token or not refresh_token:
            raise SuwayomiError("JWT login response is missing accessToken or refreshToken")
        self._jwt_access_token = access_token
        self._jwt_refresh_token = refresh_token

    async def _post_graphql(
        self,
        query: str,
        variables: dict | None = None,
        *,
        access_token: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        headers = dict(self._headers)
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"

        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables

        session = await self._get_session()
        url = f"{self.server_url}/api/graphql"

        try:
            async with session.post(url, json=payload, headers=headers) as resp:
                text = await resp.text()
                try:
                    data = json.loads(text) if text else {}
                except json.JSONDecodeError:
                    detail = text.strip()[:300] or resp.reason or "empty response"
                    message = f"HTTP {resp.status}: invalid JSON response: {detail}"
                    data = {"errors": [{"message": message}]}
                if not isinstance(data, dict):
                    data = {"errors": [{
                        "message": f"HTTP {resp.status}: invalid GraphQL response from Suwayomi",
                    }]}
                return resp.status, data
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise SuwayomiError(f"Unable to connect to Suwayomi-Server: {exc}") from exc

    @staticmethod
    def _is_unauthorized(status: int, response: dict[str, Any]) -> bool:
        if status == 401:
            return True
        errors = response.get("errors")
        if not isinstance(errors, list):
            return False
        return any(
            isinstance(error, dict)
            and "unauthorized" in str(error.get("message", "")).lower()
            for error in errors
        )

    @staticmethod
    def _response_data(status: int, response: dict[str, Any]) -> dict[str, Any]:
        errors = response.get("errors")
        if errors:
            first_error = errors[0] if isinstance(errors, list) else errors
            if isinstance(first_error, dict):
                message = first_error.get("message", "Unknown GraphQL error")
            else:
                message = str(first_error) or "Unknown GraphQL error"
            raise SuwayomiError(message)
        if status >= 400:
            raise SuwayomiError(f"Suwayomi request failed with HTTP {status}")

        data = response.get("data")
        if not isinstance(data, dict):
            raise SuwayomiError("Suwayomi GraphQL response is missing data")
        return data

    async def _raw_query(self, query: str, variables: dict | None = None) -> dict[str, Any]:
        await self._ensure_jwt()

        access_token = self._jwt_access_token if self.auth_mode == "jwt" else None
        status, response = await self._post_graphql(
            query,
            variables,
            access_token=access_token,
        )

        if self.auth_mode == "jwt" and self._is_unauthorized(status, response):
            await self._renew_jwt(access_token)
            status, response = await self._post_graphql(
                query,
                variables,
                access_token=self._jwt_access_token,
            )

        return self._response_data(status, response)

    async def _renew_jwt(self, failed_access_token: str | None):
        async with self._jwt_lock:
            if self._jwt_access_token and self._jwt_access_token != failed_access_token:
                return

            if self._jwt_refresh_token:
                try:
                    await self._refresh_jwt()
                    return
                except SuwayomiError:
                    self._jwt_access_token = None
                    self._jwt_refresh_token = None

            await self._login_jwt()

    async def _refresh_jwt(self):
        status, response = await self._post_graphql(
            'mutation($r:String!){refreshToken(input:{refreshToken:$r}){accessToken}}',
            {"r": self._jwt_refresh_token},
        )
        result = self._response_data(status, response)
        refresh_data = result.get("refreshToken")
        if not isinstance(refresh_data, dict):
            raise SuwayomiError("JWT refresh response is missing refreshToken data")
        access_token = refresh_data.get("accessToken")
        if not access_token:
            raise SuwayomiError("JWT refresh response is missing accessToken")
        self._jwt_access_token = access_token

    async def get_sources(self) -> list[Source]:
        now = time.time()
        if self._sources_cache and now - self._sources_cache[0] < _SOURCES_CACHE_TTL:
            return self._sources_cache[1]
        data = await self._raw_query(
            'query{sources{nodes{id name lang displayName supportsLatest}}}'
        )
        sources = [Source.from_dict(s) for s in data["sources"]["nodes"]]
        self._sources_cache = (now, sources)
        return sources

    async def search_manga(self, source_id: str | int, query: str, page: int = 1) -> SearchResult:
        # Multi-word titles are joined with '+' on the command side (AstrBot
        # splits args by spaces); sources expect a space-separated query.
        query = query.replace("+", " ")
        data = await self._raw_query(
            'mutation($sid:LongString!,$q:String!,$p:Int!){fetchSourceManga(input:{source:$sid,type:SEARCH,page:$p,query:$q}){mangas{id title url sourceId status thumbnailUrl inLibrary author artist description genre}hasNextPage}}',
            {"sid": str(source_id), "q": query, "p": page},
        )
        return SearchResult.from_dict(data["fetchSourceManga"])

    async def get_popular(self, source_id: str | int, page: int = 1) -> SearchResult:
        data = await self._raw_query(
            'mutation($sid:LongString!,$p:Int!){fetchSourceManga(input:{source:$sid,type:POPULAR,page:$p}){mangas{id title url sourceId status thumbnailUrl inLibrary author artist description genre}hasNextPage}}',
            {"sid": str(source_id), "p": page},
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
            'query($id:Int!){manga(id:$id){chapters{nodes{id url name chapterNumber uploadDate isDownloaded sourceOrder mangaId pageCount}}}}',
            {"id": manga_id},
        )
        return [Chapter.from_dict(c) for c in data["manga"]["chapters"]["nodes"]]

    async def fetch_chapter_pages(self, chapter_id: int) -> list[str]:
        data = await self._raw_query(
            'mutation($cid:Int!){fetchChapterPages(input:{chapterId:$cid}){pages}}',
            {"cid": chapter_id},
        )
        return data["fetchChapterPages"]["pages"]

    async def fetch_chapters(self, manga_id: int) -> list[Chapter]:
        """Fetch chapters from source (triggers network request to manga source)."""
        data = await self._raw_query(
            'mutation($mid:Int!){fetchChapters(input:{mangaId:$mid}){chapters{id url name chapterNumber uploadDate isDownloaded sourceOrder mangaId pageCount}}}',
            {"mid": manga_id},
        )
        return [Chapter.from_dict(c) for c in data["fetchChapters"]["chapters"]]

    async def enqueue_download(self, chapter_ids: list[int]) -> None:
        await self._raw_query(
            'mutation($ids:[Int!]!){enqueueChapterDownloads(input:{ids:$ids}){downloadStatus{state}}}',
            {"ids": chapter_ids},
        )

    async def update_library(self) -> None:
        await self._raw_query(
            'mutation{updateLibrary(input:{categories:null}){updateStatus{jobsInfo{isRunning}}}}'
        )

    async def get_library_mangas(self) -> list[Manga]:
        data = await self._raw_query(
            'query{mangas(condition:{inLibrary:true}){nodes{id title url sourceId status thumbnailUrl inLibrary author artist description genre}}}'
        )
        return [Manga.from_dict(m) for m in data["mangas"]["nodes"]]

    async def search_manga_by_title(self, title: str, limit: int = 10) -> list[Manga]:
        data = await self._raw_query(
            'query($t:String!,$n:Int!){mangas(filter:{title:{includes:$t}},first:$n){nodes{id title url sourceId status thumbnailUrl inLibrary author artist description genre}}}',
            {"t": title, "n": limit},
        )
        return [Manga.from_dict(m) for m in data["mangas"]["nodes"]]
