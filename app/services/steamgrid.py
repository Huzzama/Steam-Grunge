"""
steamgrid.py — SteamGridDB API client with full filter + pagination support.
"""
import requests
import os
from typing import List, Dict, Optional, Tuple
from app.config import STEAMGRIDDB_API_BASE, CACHE_FOLDER


class SteamGridDBClient:
    def __init__(self, api_key: str = ""):
        self.api_key = api_key
        self.session = requests.Session()
        if api_key:
            self.session.headers.update({"Authorization": f"Bearer {api_key}"})

    def set_api_key(self, key: str):
        self.api_key = key
        self.session.headers.update({"Authorization": f"Bearer {key}"})

    def search_games(self, query: str) -> List[Dict]:
        if not self.api_key:
            return self._mock_search(query)
        try:
            url  = f"{STEAMGRIDDB_API_BASE}/search/autocomplete/{requests.utils.quote(query)}"
            resp = self.session.get(url, timeout=10)
            resp.raise_for_status()
            return resp.json().get("data", [])
        except Exception as e:
            print(f"Search error: {e}")
            return []

    def get_grids(self, game_id: int,
                  asset_type: str = "grids",
                  styles: List[str] = None,
                  dimensions: List[str] = None,
                  nsfw: str = "false",
                  humor: str = "false",
                  page: int = 0,
                  limit: int = 20) -> Tuple[List[Dict], int]:
        """
        Fetch artwork with filters.
        asset_type: 'grids' | 'heroes' | 'logos' | 'icons'
        Returns (items, total_count)
        """
        if not self.api_key:
            return [], 0
        try:
            url    = f"{STEAMGRIDDB_API_BASE}/{asset_type}/game/{game_id}"
            params: Dict = {"nsfw": nsfw, "humor": humor,
                            "limit": limit, "page": page}
            if styles:
                params["styles"] = ",".join(styles)
            if dimensions:
                params["dimensions"] = ",".join(dimensions)

            resp = self.session.get(url, params=params, timeout=15)
            resp.raise_for_status()
            data  = resp.json()
            items = data.get("data", [])
            total = data.get("total", len(items))
            return items, total
        except Exception as e:
            print(f"Grid fetch error: {e}")
            return [], 0

    def download_image(self, url: str, local_path: str) -> Optional[str]:
        """Download image to local_path. Returns path or None. Cleans up on failure."""
        if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
            return local_path
        try:
            resp = self.session.get(url, timeout=30, stream=True)
            resp.raise_for_status()
            with open(local_path, "wb") as f:
                for chunk in resp.iter_content(8192):
                    f.write(chunk)
            # Verify file is non-empty
            if os.path.getsize(local_path) == 0:
                os.remove(local_path)
                return None
            return local_path
        except Exception as e:
            print(f"Download error: {e}")
            # Remove partial/failed file so it doesn't get cached as corrupt
            if os.path.exists(local_path):
                try: os.remove(local_path)
                except: pass
            return None

    def _mock_search(self, query: str) -> List[Dict]:
        mock = [
            {"id": 1,     "name": "Silent Hill 2"},
            {"id": 2,     "name": "Resident Evil 4"},
            {"id": 3,     "name": "Cyberpunk 2077"},
            {"id": 4,     "name": "Dark Souls III"},
            {"id": 5,     "name": "Bloodborne"},
            {"id": 6,     "name": "The Last of Us"},
            {"id": 37030, "name": "Dead by Daylight"},
        ]
        return [g for g in mock if query.lower() in g["name"].lower()]


client = SteamGridDBClient()