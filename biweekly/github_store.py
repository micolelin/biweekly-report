"""GitHub Git Data API 封裝。

這是整個系統唯一碰 GitHub 的地方。用 Git Data API 而不是 Contents API，
是因為 Contents API 以 base64 寫入時實務上限約 1 MB，PPT 附件一定超過；
而且 Git Data API 可以把多個檔案包成單一 commit，不會留下一堆零碎提交。
"""
import base64
import os

import requests

API_ROOT = "https://api.github.com"
MAX_FILE_BYTES = 100 * 1024 * 1024
BLOB_MODE = "100644"


class FileTooLargeError(Exception):
    """檔案超過 GitHub 單檔上限。"""


class GitHubStore:
    def __init__(
        self,
        token: str,
        repo: str = "micolelin/biweekly-report",
        branch: str = "main",
        session=None,
    ):
        self.repo = repo
        self.branch = branch
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )

    def _url(self, path: str) -> str:
        return f"{API_ROOT}/repos/{self.repo}/{path}"

    @staticmethod
    def _json(response):
        response.raise_for_status()
        return response.json()

    def _commit_tree(self, tree_items: list[dict], message: str) -> str:
        """共用的提交流程：讀 ref → 讀 commit → 建 tree → 建 commit → 移 ref。"""
        ref = self._json(self.session.get(self._url(f"git/ref/heads/{self.branch}")))
        base_commit_sha = ref["object"]["sha"]

        base_commit = self._json(
            self.session.get(self._url(f"git/commits/{base_commit_sha}"))
        )
        base_tree_sha = base_commit["tree"]["sha"]

        tree = self._json(
            self.session.post(
                self._url("git/trees"),
                json={"base_tree": base_tree_sha, "tree": tree_items},
            )
        )
        commit = self._json(
            self.session.post(
                self._url("git/commits"),
                json={
                    "message": message,
                    "tree": tree["sha"],
                    "parents": [base_commit_sha],
                },
            )
        )
        self._json(
            self.session.patch(
                self._url(f"git/refs/heads/{self.branch}"), json={"sha": commit["sha"]}
            )
        )
        return commit["sha"]

    def commit_files(self, files: dict[str, bytes], message: str) -> str:
        """把多個檔案寫進 repo，包成單一 commit。回傳新 commit 的 sha。

        任何檔案超過上限就整批拒絕，不做部分寫入 —— 寫一半比全部失敗更難收拾。
        """
        for path, data in files.items():
            if len(data) > MAX_FILE_BYTES:
                raise FileTooLargeError(
                    f"{path} 大小為 {len(data) / 1024 / 1024:.1f} MB，"
                    f"超過 GitHub 單檔 100 MB 上限，無法上傳"
                )

        tree_items = []
        for path, data in files.items():
            blob = self._json(
                self.session.post(
                    self._url("git/blobs"),
                    json={
                        "content": base64.b64encode(data).decode("ascii"),
                        "encoding": "base64",
                    },
                )
            )
            tree_items.append(
                {
                    "path": path,
                    "mode": BLOB_MODE,
                    "type": "blob",
                    "sha": blob["sha"],
                }
            )
        return self._commit_tree(tree_items, message)

    def delete_files(self, paths: list[str], message: str) -> str:
        """刪除檔案。在 tree 中把 sha 設為 None 就代表刪除。"""
        tree_items = [
            {"path": path, "mode": BLOB_MODE, "type": "blob", "sha": None}
            for path in paths
        ]
        return self._commit_tree(tree_items, message)

    def read_file(self, path: str) -> bytes:
        """讀取單一檔案的原始內容。"""
        response = self.session.get(
            self._url(f"contents/{path}"),
            headers={"Accept": "application/vnd.github.raw"},
            params={"ref": self.branch},
        )
        if response.status_code == 404:
            raise FileNotFoundError(path)
        response.raise_for_status()
        return response.content

    def _list(self, path: str) -> list[dict]:
        """列出目錄內容。目錄不存在時回傳空清單（這是正常狀況，不是錯誤）。"""
        response = self.session.get(
            self._url(f"contents/{path}"), params={"ref": self.branch}
        )
        if response.status_code == 404:
            return []
        response.raise_for_status()
        return response.json()

    def list_dir(self, path: str) -> list[str]:
        """列出目錄下的檔案路徑（不含子目錄）。"""
        return [item["path"] for item in self._list(path) if item["type"] == "file"]

    def list_subdirs(self, path: str) -> list[str]:
        """列出目錄下的子目錄名稱（不含前綴路徑）。

        `data/published/` 底下每一期是一個資料夾，要靠這個列出所有期別。
        """
        return [
            item["path"].rsplit("/", 1)[-1]
            for item in self._list(path)
            if item["type"] == "dir"
        ]


def from_env(session=None) -> GitHubStore:
    """從環境變數建立 GitHubStore。"""
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError(
            "找不到 GITHUB_TOKEN。請確認 /Users/admin/Documents/m-agent/.env 已載入。"
        )
    return GitHubStore(token=token, session=session)
