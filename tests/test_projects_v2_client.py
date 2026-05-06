from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from murloc.github_client import ProjectsV2Client


def _make_client(dry_run: bool = False) -> ProjectsV2Client:
    client = ProjectsV2Client.__new__(ProjectsV2Client)
    client._token = "tok"
    client._gh = MagicMock()
    client._repo = MagicMock()
    client._base_branch = "main"
    client._project_owner = "alice"
    client._project_number = 3
    client._status_field = "Status"
    client._dry_run = dry_run
    client._project_id = "PVT_id"
    client._status_field_id = "PVTSSF_id"
    client._status_options = {
        "Todo": "opt_todo",
        "In Progress": "opt_inprogress",
        "In Review": "opt_inreview",
        "Failed": "opt_failed",
    }
    client._item_cache = {}
    return client


def _item_node(
    item_id: str,
    issue_number: int,
    status_option_id: str,
    title: str = "Fix thing",
    body: str = "body",
    labels: list[str] | None = None,
) -> dict:
    return {
        "id": item_id,
        "fieldValues": {
            "nodes": [
                {
                    "optionId": status_option_id,
                    "field": {"name": "Status"},
                }
            ]
        },
        "content": {
            "__typename": "Issue",
            "number": issue_number,
            "title": title,
            "body": body,
            "state": "OPEN",
            "url": f"https://github.com/alice/repo/issues/{issue_number}",
            "labels": {"nodes": [{"name": lbl} for lbl in (labels or [])]},
        },
    }


class TestListReady:
    def test_returns_todo_issues(self) -> None:
        client = _make_client()
        node = _item_node("PVTI_1", 42, "opt_todo", title="Do work", labels=["bug"])

        with patch.object(
            client,
            "_graphql",
            return_value={
                "user": {
                    "projectV2": {
                        "items": {
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                            "nodes": [node],
                        }
                    }
                }
            },
        ):
            results = client.list_ready()

        assert len(results) == 1
        ref = results[0]
        assert ref.number == 42
        assert ref.title == "Do work"
        assert ref.labels == ["bug"]
        assert client._item_cache[42] == "PVTI_1"

    def test_skips_non_todo_items(self) -> None:
        client = _make_client()
        nodes = [
            _item_node("PVTI_1", 10, "opt_inprogress"),
            _item_node("PVTI_2", 11, "opt_todo"),
        ]

        with patch.object(
            client,
            "_graphql",
            return_value={
                "user": {
                    "projectV2": {
                        "items": {
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                            "nodes": nodes,
                        }
                    }
                }
            },
        ):
            results = client.list_ready()

        assert [r.number for r in results] == [11]

    def test_skips_draft_and_pr_items(self) -> None:
        client = _make_client()
        draft_node = {
            "id": "PVTI_draft",
            "fieldValues": {
                "nodes": [{"optionId": "opt_todo", "field": {"name": "Status"}}]
            },
            "content": {"__typename": "DraftIssue", "title": "Draft"},
        }
        pr_node = {
            "id": "PVTI_pr",
            "fieldValues": {
                "nodes": [{"optionId": "opt_todo", "field": {"name": "Status"}}]
            },
            "content": {
                "__typename": "PullRequest",
                "number": 99,
                "title": "A PR",
                "state": "OPEN",
            },
        }

        with patch.object(
            client,
            "_graphql",
            return_value={
                "user": {
                    "projectV2": {
                        "items": {
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                            "nodes": [draft_node, pr_node],
                        }
                    }
                }
            },
        ):
            results = client.list_ready()

        assert results == []

    def test_skips_closed_issues(self) -> None:
        client = _make_client()
        closed = _item_node("PVTI_c", 5, "opt_todo")
        closed["content"]["state"] = "CLOSED"

        with patch.object(
            client,
            "_graphql",
            return_value={
                "user": {
                    "projectV2": {
                        "items": {
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                            "nodes": [closed],
                        }
                    }
                }
            },
        ):
            results = client.list_ready()

        assert results == []

    def test_paginates_when_has_next_page(self) -> None:
        client = _make_client()
        page1 = {
            "user": {
                "projectV2": {
                    "items": {
                        "pageInfo": {"hasNextPage": True, "endCursor": "cursor1"},
                        "nodes": [_item_node("PVTI_1", 1, "opt_todo")],
                    }
                }
            }
        }
        page2 = {
            "user": {
                "projectV2": {
                    "items": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": [_item_node("PVTI_2", 2, "opt_todo")],
                    }
                }
            }
        }

        with patch.object(client, "_graphql", side_effect=[page1, page2]) as mock_gql:
            results = client.list_ready()

        assert [r.number for r in results] == [1, 2]
        assert mock_gql.call_count == 2
        second_vars = mock_gql.call_args_list[1][0][1]
        assert second_vars["after"] == "cursor1"


class TestClaim:
    def test_returns_true_when_still_todo(self) -> None:
        client = _make_client()
        client._item_cache[7] = "PVTI_7"

        status_resp = {
            "node": {
                "fieldValues": {
                    "nodes": [{"optionId": "opt_todo", "field": {"name": "Status"}}]
                }
            }
        }
        mutation_resp = {"updateProjectV2ItemFieldValue": {"projectV2Item": {"id": "PVTI_7"}}}

        with patch.object(client, "_graphql", side_effect=[status_resp, mutation_resp]) as mock_gql:
            result = client.claim(7)

        assert result is True
        assert mock_gql.call_count == 2

    def test_returns_false_when_no_longer_todo(self) -> None:
        client = _make_client()
        client._item_cache[7] = "PVTI_7"

        status_resp = {
            "node": {
                "fieldValues": {
                    "nodes": [{"optionId": "opt_inprogress", "field": {"name": "Status"}}]
                }
            }
        }

        with patch.object(client, "_graphql", return_value=status_resp):
            result = client.claim(7)

        assert result is False

    def test_returns_false_when_not_in_cache(self) -> None:
        client = _make_client()
        # issue 99 was never returned by list_ready, so not cached
        with patch.object(client, "_graphql") as mock_gql:
            result = client.claim(99)
        assert result is False
        mock_gql.assert_not_called()

    def test_dry_run_skips_mutation(self) -> None:
        client = _make_client(dry_run=True)
        client._item_cache[5] = "PVTI_5"

        status_resp = {
            "node": {
                "fieldValues": {
                    "nodes": [{"optionId": "opt_todo", "field": {"name": "Status"}}]
                }
            }
        }

        with patch.object(client, "_graphql", return_value=status_resp) as mock_gql:
            result = client.claim(5)

        assert result is True
        assert mock_gql.call_count == 1  # only the status read, no mutation


class TestMarkReviewAndFailed:
    def test_mark_review_sets_status_and_comments(self) -> None:
        client = _make_client()
        client._item_cache[3] = "PVTI_3"
        mutation_resp = {"updateProjectV2ItemFieldValue": {"projectV2Item": {"id": "PVTI_3"}}}

        fake_issue = MagicMock()
        client._repo.get_issue.return_value = fake_issue

        with patch.object(client, "_graphql", return_value=mutation_resp):
            client.mark_review(3, "https://github.com/pr/1", "looks good")

        fake_issue.create_comment.assert_called_once()
        comment_text = fake_issue.create_comment.call_args[0][0]
        assert "https://github.com/pr/1" in comment_text
        assert "looks good" in comment_text

    def test_mark_failed_sets_status_and_comments(self) -> None:
        client = _make_client()
        client._item_cache[8] = "PVTI_8"
        mutation_resp = {"updateProjectV2ItemFieldValue": {"projectV2Item": {"id": "PVTI_8"}}}

        fake_issue = MagicMock()
        client._repo.get_issue.return_value = fake_issue

        with patch.object(client, "_graphql", return_value=mutation_resp):
            client.mark_failed(8, "exit code 1\n```\nerror log\n```")

        fake_issue.create_comment.assert_called_once()
        comment_text = fake_issue.create_comment.call_args[0][0]
        assert "agent failed" in comment_text
        assert "exit code 1" in comment_text

    def test_mark_review_posts_comment_even_if_status_update_fails(self) -> None:
        client = _make_client()
        client._item_cache[3] = "PVTI_3"

        fake_issue = MagicMock()
        client._repo.get_issue.return_value = fake_issue

        with patch.object(client, "_graphql", side_effect=RuntimeError("boom")):
            client.mark_review(3, "https://github.com/pr/1", "looks good")

        fake_issue.create_comment.assert_called_once()

    def test_mark_failed_posts_comment_even_if_status_update_fails(self) -> None:
        client = _make_client()
        client._item_cache[8] = "PVTI_8"

        fake_issue = MagicMock()
        client._repo.get_issue.return_value = fake_issue

        with patch.object(client, "_graphql", side_effect=RuntimeError("boom")):
            client.mark_failed(8, "exit code 1")

        fake_issue.create_comment.assert_called_once()

    def test_current_status_returns_none_for_missing_node(self) -> None:
        client = _make_client()
        with patch.object(client, "_graphql", return_value={"node": None}):
            assert client._current_status_option_id("PVTI_missing") is None

    def test_dry_run_skips_writes(self) -> None:
        client = _make_client(dry_run=True)
        client._item_cache[2] = "PVTI_2"

        with patch.object(client, "_graphql") as mock_gql:
            client.mark_review(2, "https://pr", "summary")
            client.mark_failed(2, "oops")

        mock_gql.assert_not_called()
        client._repo.get_issue.assert_not_called()


class TestEnsureProjectMeta:
    def test_parses_project_id_and_options(self) -> None:
        client = ProjectsV2Client.__new__(ProjectsV2Client)
        client._token = "tok"
        client._gh = MagicMock()
        client._repo = MagicMock()
        client._base_branch = "main"
        client._project_owner = "alice"
        client._project_number = 3
        client._status_field = "Status"
        client._dry_run = False
        client._project_id = None
        client._status_field_id = None
        client._status_options = {}
        client._item_cache = {}

        meta_resp = {
            "user": {
                "projectV2": {
                    "id": "PVT_xyz",
                    "fields": {
                        "nodes": [
                            {},  # non-single-select field returns empty object
                            {
                                "id": "PVTSSF_abc",
                                "name": "Status",
                                "options": [
                                    {"id": "opt1", "name": "Todo"},
                                    {"id": "opt2", "name": "In Progress"},
                                    {"id": "opt3", "name": "In Review"},
                                    {"id": "opt4", "name": "Failed"},
                                ],
                            },
                        ]
                    },
                }
            }
        }

        with patch.object(client, "_graphql", return_value=meta_resp):
            client._ensure_project_meta()

        assert client._project_id == "PVT_xyz"
        assert client._status_field_id == "PVTSSF_abc"
        assert client._status_options["Todo"] == "opt1"
        assert client._status_options["Failed"] == "opt4"

    def test_raises_clear_error_when_project_not_found(self) -> None:
        client = ProjectsV2Client.__new__(ProjectsV2Client)
        client._project_id = None
        client._status_field_id = None
        client._status_options = {}
        client._project_owner = "alice"
        client._project_number = 99
        client._status_field = "Status"

        with patch.object(
            client,
            "_graphql",
            return_value={"user": {"projectV2": None}},
        ), pytest.raises(RuntimeError, match="could not be found"):
            client._ensure_project_meta()

    def test_refetches_when_partially_initialized(self) -> None:
        client = ProjectsV2Client.__new__(ProjectsV2Client)
        client._project_id = "PVT_xyz"
        client._status_field_id = None  # partial state
        client._status_options = {}
        client._project_owner = "alice"
        client._project_number = 3
        client._status_field = "Status"

        meta_resp = {
            "user": {
                "projectV2": {
                    "id": "PVT_xyz",
                    "fields": {
                        "nodes": [
                            {
                                "id": "PVTSSF_abc",
                                "name": "Status",
                                "options": [{"id": "opt1", "name": "Todo"}],
                            }
                        ]
                    },
                }
            }
        }

        with patch.object(client, "_graphql", return_value=meta_resp) as mock_gql:
            client._ensure_project_meta()

        assert mock_gql.call_count == 1
        assert client._status_field_id == "PVTSSF_abc"

    def test_raises_if_status_field_missing(self) -> None:
        client = ProjectsV2Client.__new__(ProjectsV2Client)
        client._project_id = None
        client._status_field_id = None
        client._status_options = {}
        client._item_cache = {}
        client._project_owner = "alice"
        client._project_number = 3
        client._status_field = "Status"

        meta_resp = {
            "user": {
                "projectV2": {
                    "id": "PVT_xyz",
                    "fields": {"nodes": []},
                }
            }
        }

        with patch.object(client, "_graphql", return_value=meta_resp), pytest.raises(
            RuntimeError, match="Status field"
        ):
            client._ensure_project_meta()
