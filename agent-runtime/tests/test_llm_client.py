import json

from car_agent.clients.llm_client import _normalize_plan_payload


def test_normalize_plan_payload_accepts_common_model_aliases() -> None:
    content = json.dumps(
        {
            "task_name": "home_round_trip_patrol",
            "start_location_id": "home",
            "end_location_id": "home",
            "waypoints": [
                {
                    "location_id": "home",
                    "action": "record",
                    "duration": 5,
                }
            ],
            "task_summary": "从起点出发，仅巡检起点后返回起点。",
        },
        ensure_ascii=False,
    )

    plan = _normalize_plan_payload(content, user_request="巡检 home 后返回起点")

    assert plan == {
        "name": "home_round_trip_patrol",
        "waypoints": ["home"],
        "event_policy": {},
        "return_home": True,
        "summary": "从起点出发，仅巡检起点后返回起点。",
    }


def test_normalize_plan_payload_strips_markdown_json_fence() -> None:
    content = """```json
{"name":"测试任务","waypoints":["home"],"return_home":false,"summary":"ok"}
```"""

    plan = _normalize_plan_payload(content, user_request="巡检 home")

    assert plan["name"] == "测试任务"
    assert plan["waypoints"] == ["home"]
