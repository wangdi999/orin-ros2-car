# CI/CD

This repository uses GitHub Actions for safe, non-motion validation and image
publishing.

## CI

`.github/workflows/ci.yml` runs on pushes and pull requests to `main` and
`devcp`.

It checks:

- Agent Runtime Python linting and tests.
- Agent Runtime Docker image build.
- Smart Car Console Node tests and Vite production build.
- ROS2 Foxy package compilation inside a `ros:foxy-ros-base-focal` container.

The ROS2 CI job only runs `colcon build`. It does not launch ROS nodes, publish
`/cmd_vel`, or connect to the physical car.

## CD

`.github/workflows/cd.yml` publishes the Agent Runtime container image to GitHub
Container Registry.

It runs on:

- Manual `workflow_dispatch`.
- Git tags matching `agent-runtime-v*`.

Published image:

```text
ghcr.io/<owner>/orin-car-agent-runtime:<tag>
```

The workflow builds both:

```text
linux/amd64
linux/arm64
```

The car deployment is intentionally not automatic. Deploying to the physical car
requires one of these controlled paths:

- A self-hosted GitHub Actions runner inside the car/VPN network.
- A manually triggered SSH deployment workflow with repository secrets for the
  SSH host, user, key, and known host.

Do not store car SSH credentials, WireGuard keys, Agent tokens, LLM API keys, or
console `local-config.json` in Git.
