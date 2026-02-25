"""Netease Cloud Music controller powered by NeteaseCloudMusicApi."""

import asyncio
import json
from typing import Any
from urllib import error, parse, request


class NeteaseCloudController:
    """Encapsulate Netease Cloud control capabilities."""

    def __init__(
        self,
        api_base_url: str,
        cookie: str,
        user_id: str,
        favorite_playlist_id: str,
        timeout_seconds: int = 15,
    ) -> None:
        # Keep constructor lightweight; connectivity is validated in connect().
        self._api_base_url = api_base_url.rstrip("/")
        self._cookie = cookie
        self._user_id = user_id
        self._favorite_playlist_id = favorite_playlist_id
        self._timeout_seconds = timeout_seconds
        self._connected = False

    def _build_url(self, path: str, params: dict[str, Any] | None = None) -> str:
        """Build one request URL and append cookie when configured."""
        query: dict[str, Any] = params.copy() if params else {}
        if self._cookie:
            query["cookie"] = self._cookie
        query_string = parse.urlencode(query)
        if query_string:
            return f"{self._api_base_url}{path}?{query_string}"
        return f"{self._api_base_url}{path}"

    def _request_json_sync(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute one HTTP GET request and decode JSON response."""
        url = self._build_url(path, params=params)
        req = request.Request(url, method="GET")
        try:
            with request.urlopen(req, timeout=self._timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            return {"ok": False, "error": f"HTTP error: {exc.code}", "url": url}
        except error.URLError as exc:
            return {"ok": False, "error": f"Connection error: {exc.reason}", "url": url}
        except json.JSONDecodeError:
            return {"ok": False, "error": "Invalid JSON response", "url": url}

    async def _request_json(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Async wrapper for blocking HTTP requests."""
        return await asyncio.to_thread(self._request_json_sync, path, params)

    async def connect(self) -> None:
        """Validate Netease API availability."""
        ping_result = await self._request_json("/banner", {"type": 0})
        self._connected = bool(ping_result) and "error" not in ping_result

    async def play(self, song_id: str) -> dict[str, Any]:
        """Trigger playback for a target song by fetching playable URL."""
        return await self.play_music(song_id)

    async def pause(self) -> dict[str, Any]:
        """Return pause action as client-side playback control signal."""
        return {"ok": True, "action": "pause"}

    async def get_login_qrcode(self) -> dict[str, Any]:
        """Generate Netease login QR code metadata."""
        if not self._connected:
            return {"ok": False, "error": "Netease API is not available"}
        key_result = await self._request_json("/login/qr/key")
        if "error" in key_result:
            return {"ok": False, "error": key_result["error"]}
        unikey = (
            key_result.get("data", {}).get("unikey")
            or key_result.get("unikey")
            or ""
        )
        if not unikey:
            return {"ok": False, "error": "Failed to get login unikey"}
        qr_result = await self._request_json("/login/qr/create", {"key": unikey, "qrimg": "true"})
        if "error" in qr_result:
            return {"ok": False, "error": qr_result["error"]}
        qr_data = qr_result.get("data", {})
        return {
            "ok": True,
            "action": "get_login_qrcode",
            "unikey": unikey,
            "qrurl": qr_data.get("qrurl", ""),
            "qrimg": qr_data.get("qrimg", ""),
        }

    async def check_login_status(self, unikey: str) -> dict[str, Any]:
        """Check current QR login status."""
        if not self._connected:
            return {"ok": False, "error": "Netease API is not available"}
        if not unikey:
            return {"ok": False, "error": "unikey is required"}
        status_result = await self._request_json("/login/qr/check", {"key": unikey, "timestamp": "1"})
        if "error" in status_result:
            return {"ok": False, "error": status_result["error"]}
        return {
            "ok": True,
            "action": "check_login_status",
            "code": status_result.get("code"),
            "message": status_result.get("message", ""),
            "cookie": status_result.get("cookie", ""),
        }

    async def like_music(self, song_id: str) -> dict[str, Any]:
        """Like one song by id."""
        if not self._connected:
            return {"ok": False, "error": "Netease API is not available"}
        if not song_id:
            return {"ok": False, "error": "song_id is required"}
        like_result = await self._request_json("/like", {"id": song_id, "like": "true"})
        if "error" in like_result:
            return {"ok": False, "error": like_result["error"]}
        return {
            "ok": like_result.get("code") == 200,
            "action": "like_music",
            "song_id": song_id,
            "code": like_result.get("code"),
            "raw": like_result,
        }

    async def favorite_music(self, song_id: str) -> dict[str, Any]:
        """Add one song into favorites collection."""
        if not self._connected:
            return {"ok": False, "error": "Netease API is not available"}
        if not song_id:
            return {"ok": False, "error": "song_id is required"}
        if not self._favorite_playlist_id:
            return {"ok": False, "error": "NETEASE_FAVORITE_PLAYLIST_ID is required"}
        favorite_result = await self._request_json(
            "/playlist/tracks",
            {"op": "add", "pid": self._favorite_playlist_id, "tracks": song_id},
        )
        if "error" in favorite_result:
            return {"ok": False, "error": favorite_result["error"]}
        return {
            "ok": favorite_result.get("code") == 200,
            "action": "favorite_music",
            "song_id": song_id,
            "code": favorite_result.get("code"),
            "raw": favorite_result,
        }

    async def search_music(self, keywords: str) -> dict[str, Any]:
        """Search songs by keywords."""
        if not self._connected:
            return {"ok": False, "error": "Netease API is not available"}
        if not keywords:
            return {"ok": False, "error": "keywords is required"}
        search_result = await self._request_json("/cloudsearch", {"keywords": keywords, "limit": "5"})
        if "error" in search_result:
            return {"ok": False, "error": search_result["error"]}
        songs = search_result.get("result", {}).get("songs", []) or []
        candidates = []
        for song in songs:
            artists = song.get("ar", []) or []
            artist_names = [artist.get("name", "") for artist in artists if artist.get("name")]
            candidates.append(
                {
                    "song_id": str(song.get("id", "")),
                    "name": song.get("name", ""),
                    "artist": "/".join(artist_names),
                }
            )
        return {"ok": True, "action": "search_music", "keywords": keywords, "candidates": candidates}

    async def play_music(self, song_id: str) -> dict[str, Any]:
        """Resolve playable URL for one song."""
        if not self._connected:
            return {"ok": False, "error": "Netease API is not available"}
        if not song_id:
            return {"ok": False, "error": "song_id is required"}
        url_result = await self._request_json("/song/url/v1", {"id": song_id, "level": "standard"})
        if "error" in url_result:
            return {"ok": False, "error": url_result["error"]}
        data = url_result.get("data", []) or []
        first = data[0] if data else {}
        return {
            "ok": bool(first.get("url")),
            "action": "play_music",
            "song_id": song_id,
            "url": first.get("url", ""),
            "raw": url_result,
        }

    async def get_user_playlist(self, playlist_type: str) -> dict[str, Any]:
        """Get playlist metadata and entries for the user."""
        if not self._connected:
            return {"ok": False, "error": "Netease API is not available"}
        if not self._user_id:
            return {"ok": False, "error": "NETEASE_USER_ID is required"}
        normalized_type = (playlist_type or "liked").strip().lower() or "liked"
        playlists_result = await self._request_json("/user/playlist", {"uid": self._user_id, "limit": "30"})
        if "error" in playlists_result:
            return {"ok": False, "error": playlists_result["error"]}
        playlist_items = playlists_result.get("playlist", []) or []
        if not playlist_items:
            return {"ok": False, "error": "No playlists found"}
        target = playlist_items[0]
        if normalized_type in {"favorite", "collected", "收藏"}:
            for item in playlist_items:
                if item.get("subscribed"):
                    target = item
                    break
        tracks_result = await self._request_json("/playlist/track/all", {"id": str(target.get("id", "")), "limit": "20"})
        if "error" in tracks_result:
            return {"ok": False, "error": tracks_result["error"]}
        tracks = tracks_result.get("songs", []) or []
        simplified_tracks = [{"song_id": str(track.get("id", "")), "name": track.get("name", "")} for track in tracks]
        return {
            "ok": True,
            "action": "get_user_playlist",
            "type": normalized_type,
            "playlist_id": str(target.get("id", "")),
            "playlist_name": target.get("name", ""),
            "playlist": simplified_tracks,
        }
