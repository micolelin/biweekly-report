import base64

import pytest

from biweekly import github_store
from biweekly.tests.conftest import FakeResponse, FakeSession


def _happy_routes():
    return {
        ("GET", "git/ref/heads/main"): FakeResponse({"object": {"sha": "舊commit"}}),
        ("GET", "git/commits/舊commit"): FakeResponse({"tree": {"sha": "舊tree"}}),
        ("POST", "git/blobs"): FakeResponse({"sha": "新blob"}),
        ("POST", "git/trees"): FakeResponse({"sha": "新tree"}),
        ("POST", "git/commits"): FakeResponse({"sha": "新commit"}),
        ("PATCH", "git/refs/heads/main"): FakeResponse({}),
    }


def _store(session):
    return github_store.GitHubStore(token="假token", session=session)


def test_寫入檔案會回傳新的_commit_sha():
    session = FakeSession(_happy_routes())
    sha = _store(session).commit_files({"data/a.md": b"hello"}, "test")
    assert sha == "新commit"


def test_檔案內容以_base64_送出():
    session = FakeSession(_happy_routes())
    _store(session).commit_files({"data/a.md": "中文內容".encode()}, "test")
    blob_body = session.json_bodies("POST", "git/blobs")[0]
    assert blob_body["encoding"] == "base64"
    assert base64.b64decode(blob_body["content"]) == "中文內容".encode()


def test_多個檔案包成同一次提交():
    session = FakeSession(_happy_routes())
    _store(session).commit_files(
        {"data/a.md": b"a", "data/b.pptx": b"b"}, "test"
    )
    assert len(session.json_bodies("POST", "git/blobs")) == 2
    assert len(session.json_bodies("POST", "git/commits")) == 1
    tree_body = session.json_bodies("POST", "git/trees")[0]
    assert tree_body["base_tree"] == "舊tree"
    assert {item["path"] for item in tree_body["tree"]} == {
        "data/a.md",
        "data/b.pptx",
    }
    assert all(item["mode"] == "100644" for item in tree_body["tree"])


def test_新_commit_的_parent_是舊_commit():
    session = FakeSession(_happy_routes())
    _store(session).commit_files({"data/a.md": b"a"}, "提交訊息")
    commit_body = session.json_bodies("POST", "git/commits")[0]
    assert commit_body["parents"] == ["舊commit"]
    assert commit_body["tree"] == "新tree"
    assert commit_body["message"] == "提交訊息"


def test_ref_會被移到新_commit():
    session = FakeSession(_happy_routes())
    _store(session).commit_files({"data/a.md": b"a"}, "test")
    assert session.json_bodies("PATCH", "git/refs/heads/main")[0] == {"sha": "新commit"}


def test_超過一百MB的檔案在送出前就被擋下():
    session = FakeSession(_happy_routes())
    oversized = b"x" * (github_store.MAX_FILE_BYTES + 1)
    with pytest.raises(github_store.FileTooLargeError, match="100 MB"):
        _store(session).commit_files({"data/big.mp4": oversized}, "test")
    assert session.calls == []  # 完全沒有送出任何請求


def test_刪除檔案時_tree_項目的_sha_為_None():
    session = FakeSession(_happy_routes())
    _store(session).delete_files(["data/a.md"], "刪除")
    tree_body = session.json_bodies("POST", "git/trees")[0]
    assert tree_body["tree"] == [
        {"path": "data/a.md", "mode": "100644", "type": "blob", "sha": None}
    ]


def test_讀取檔案回傳原始位元組():
    session = FakeSession(
        {("GET", "contents/data/a.md"): FakeResponse(content="內容".encode())}
    )
    assert _store(session).read_file("data/a.md") == "內容".encode()


def test_讀取不存在的檔案要拋_FileNotFoundError():
    session = FakeSession(
        {("GET", "contents/data/nope.md"): FakeResponse({}, status_code=404)}
    )
    with pytest.raises(FileNotFoundError):
        _store(session).read_file("data/nope.md")


def test_列出目錄只回傳檔案不含子目錄():
    session = FakeSession(
        {
            ("GET", "contents/data/entries/2026-08"): FakeResponse(
                [
                    {"path": "data/entries/2026-08/a.md", "type": "file"},
                    {"path": "data/entries/2026-08/sub", "type": "dir"},
                ]
            )
        }
    )
    assert _store(session).list_dir("data/entries/2026-08") == [
        "data/entries/2026-08/a.md"
    ]


def test_列出不存在的目錄回傳空清單():
    session = FakeSession(
        {("GET", "contents/data/nope"): FakeResponse({}, status_code=404)}
    )
    assert _store(session).list_dir("data/nope") == []


def test_列出子目錄只回傳目錄名稱不含前綴():
    session = FakeSession(
        {
            ("GET", "contents/data/published"): FakeResponse(
                [
                    {"path": "data/published/2026-08-14", "type": "dir"},
                    {"path": "data/published/2026-08-28", "type": "dir"},
                    {"path": "data/published/README.md", "type": "file"},
                ]
            )
        }
    )
    assert _store(session).list_subdirs("data/published") == [
        "2026-08-14",
        "2026-08-28",
    ]


def test_列出不存在目錄的子目錄回傳空清單():
    session = FakeSession(
        {("GET", "contents/data/nope"): FakeResponse({}, status_code=404)}
    )
    assert _store(session).list_subdirs("data/nope") == []


def test_API_回傳錯誤時要拋出例外不得吞掉():
    routes = _happy_routes()
    routes[("POST", "git/blobs")] = FakeResponse(
        {"message": "Bad credentials"}, status_code=401
    )
    session = FakeSession(routes)
    with pytest.raises(RuntimeError, match="401"):
        _store(session).commit_files({"data/a.md": b"a"}, "test")


def test_沒有_GITHUB_TOKEN_時_from_env_要明確報錯(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="GITHUB_TOKEN"):
        github_store.from_env()
