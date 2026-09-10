"""Контрактные проверки защитных сценариев Postman-коллекции."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).parents[3]


def _collection() -> dict[str, Any]:
    payload = json.loads((ROOT / "postman/triema-masker.postman_collection.json").read_text())
    return cast(dict[str, Any], payload)


def _environment() -> dict[str, str]:
    payload = json.loads((ROOT / "postman/triema-masker.postman_environment.json").read_text())
    values = cast(list[dict[str, str]], payload["values"])
    return {value["key"]: value["value"] for value in values}


def _item(node: dict[str, Any], name: str) -> dict[str, Any]:
    for item in node["item"]:
        if item["name"] == name:
            return cast(dict[str, Any], item)
    raise AssertionError(f"Не найден элемент Postman-коллекции: {name}")


def _script(node: dict[str, Any], listen: str) -> str:
    for event in node.get("event", []):
        if event["listen"] == listen:
            return "\n".join(event["script"]["exec"])
    raise AssertionError(f"У {node['name']} нет {listen}-скрипта")


def test_create_user_uses_a_fresh_email_for_each_run() -> None:
    collection = _collection()
    create_user = _item(_item(collection, "Users (admin only)"), "Create User")
    script = _script(create_user, "prerequest")

    assert _environment()["new_user_email_template"] == "newuser@example.com"
    assert "pm.variables.replaceIn('{{$guid}}')" in script
    assert "pm.environment.set('new_user_email'" in script


def test_failed_prerequisites_stop_the_runner_with_an_actionable_message() -> None:
    collection = _collection()
    folders_and_variables = {
        "E2E - Mask document": "input_file",
        "Run questions and answers": "question_run_id",
        "Operator review edits": "review_run_id",
    }

    for folder_name, variable in folders_and_variables.items():
        script = _script(_item(collection, folder_name), "prerequest")
        assert variable in script
        assert "pm.execution.skipRequest()" in script
        assert "pm.execution.setNextRequest(null)" in script
        assert "pm.expect.fail" in script

    history = _item(collection, "Run history and negative cases")
    foreign_run = _item(history, "Get another user's run (404)")
    assert "foreign_run_id" in _script(foreign_run, "prerequest")


def test_login_and_user_creation_fail_once_and_stop_dependents() -> None:
    collection = _collection()
    admin_login = _item(_item(collection, "Auth"), "Login (Admin)")
    create_user = _item(_item(collection, "Users (admin only)"), "Create User")
    e2e_login = _item(_item(collection, "E2E - Mask document"), "E2E - Login")

    for node in (admin_login, create_user, e2e_login):
        script = _script(node, "test")
        assert "pm.execution.setNextRequest(null)" in script
        assert "pm.expect.fail" in script
