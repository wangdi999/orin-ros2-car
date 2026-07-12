import uvicorn

from car_agent.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "car_agent.api.app:create_app",
        factory=True,
        host=settings.agent_host,
        port=settings.agent_port,
    )


if __name__ == "__main__":
    main()
