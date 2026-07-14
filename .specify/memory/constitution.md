<!--
Sync Impact Report
- Version change: template -> 1.0.0
- Added principles:
  - I. Hardware Safety Is Non-Negotiable
  - II. Single Writer at the Motion Boundary
  - III. Canonical Topic and TF Ownership
  - IV. Incremental Gates Before Physical Progression
  - V. Foxy Runtime Fidelity
  - VI. Observable and Recoverable Failures
  - VII. Preserve Secrets and User Work
- Added sections:
  - Hardware and Runtime Constraints
  - Delivery Workflow and Quality Gates
- Removed sections: none
- Templates updated:
  - ✅ .specify/templates/plan-template.md
  - ✅ .specify/templates/spec-template.md
  - ✅ .specify/templates/tasks-template.md
- Runtime guidance reviewed:
  - ✅ AGENTS.md
  - ✅ docs/AI_CAR_CONNECTION_AND_DEVELOPMENT.md
- Deferred items: none
-->
# Smart Car ROS2 Navigation Constitution

## Core Principles

### I. Hardware Safety Is Non-Negotiable
Every motion-affecting change or test MUST be treated as a physical hardware action.
No agent or developer may send a non-zero motion command until the user explicitly
confirms that the wheels are lifted or the operating area is clear. The first test
MUST use no more than 0.05 m/s linear and 0.20 rad/s angular speed, later tests MUST
remain at or below 0.10 m/s and 0.40 rad/s until the preceding safety gate passes,
and every motion test MUST end with an explicit zero Twist. Emergency-stop and
fault handling MUST override all manual and autonomous behavior.

### II. Single Writer at the Motion Boundary
`/cmd_vel` with type `geometry_msgs/msg/Twist` is the final hardware command
boundary. Exactly one normal runtime component, the velocity arbiter, MUST publish
to it. Manual and autonomous producers MUST publish to distinct upstream topics.
The chassis driver MUST enforce independent finite-value checks, hard limits, a
300 ms command watchdog, and zero output on timeout and graceful termination.
Direct zero publication to `/cmd_vel` is permitted only as a documented emergency
fallback when the normal safety chain is unavailable.

### III. Canonical Topic and TF Ownership
Every safety-critical topic and transform MUST have one documented owner. The
canonical transform tree is `map -> odom -> base_footprint -> base_link -> sensor`.
The EKF alone publishes `/odom` and `odom -> base_footprint`; the URDF owns static
robot-to-sensor transforms; Cartographer owns `map -> odom` only in mapping mode;
AMCL owns it only in navigation mode. Mapping and localization modes MUST NOT run
simultaneously. Frame IDs, timestamps, units, QoS, and publisher counts MUST be
validated before SLAM or navigation work proceeds.

### IV. Incremental Gates Before Physical Progression
Work MUST progress through safe base, mapping, navigation, then fault/return-home
gates. A later gate MUST NOT start while a prior gate has an unresolved failure.
Each user story MUST be independently testable, and motion-control work MUST include
tests before or alongside implementation plus measurable acceptance evidence.
Failed checks MUST remain visible in tasks and reports rather than being waived by
parameter changes or disabled safety logic.

### V. Foxy Runtime Fidelity
The physical target is the car's installed ROS 2 Foxy Docker environment. Designs
MUST use the action, message, parameter, launch, and plugin interfaces actually
available there; post-Foxy fields or packages MUST NOT be assumed. Pure logic may
be tested locally, but ROS packages MUST build and be validated in the target Foxy
overlay before deployment. Dependency or API drift MUST fail fast with a clear
diagnostic and remediation note.

### VI. Observable and Recoverable Failures
Command timeout, emergency stop, serial loss, lidar/odometry/TF loss, navigation
failure, cancellation, low voltage, and graceful process exit MUST each produce a
deterministic safe state, zero command, structured alarm, and documented recovery
path. Faults that can cause motion MUST latch until health is restored and an
explicit reset is accepted. Verification records MUST include trigger, expected
behavior, observed behavior, stop latency, and recovery result.

### VII. Preserve Secrets and User Work
`smart-car-console/local-config.json`, SSH credentials, host keys, raw runtime logs,
and device-specific secrets MUST remain local and untracked. Existing uncommitted
user changes MUST NOT be reset, overwritten, reformatted, staged, or committed as
part of unrelated work. Edits to already-modified files MUST be minimal and tested
against the recorded baseline. Generated maps and concise verification summaries
may be delivered; raw rosbag data MUST remain in an ignored artifact directory.

## Hardware and Runtime Constraints

- The target platform is Jetson Orin Nano in the existing `icar/ros-foxy:1.0.2`
  container with the X3 mecanum base and SLLIDAR A1.
- Autonomous navigation MUST use a differential model with `linear.y = 0`; manual
  X3 control may retain bounded lateral motion.
- Driver hard limits MUST NOT exceed 0.35 m/s for linear axes or 0.80 rad/s for yaw.
- Real low-battery return MUST default to disabled until the battery specification
  is confirmed; the state machine MUST be testable through a controlled simulation.
- Cartographer is the primary SLAM implementation; fallback mapping cannot silently
  replace it and MUST be documented as a degraded result.

## Delivery Workflow and Quality Gates

1. Record the dirty-worktree baseline and preserve all unrelated changes.
2. Specify user stories, measurable outcomes, safety boundaries, and failure cases.
3. Resolve all high-impact ambiguities before technical planning.
4. Plan against the target Foxy interfaces and re-check every constitutional gate.
5. Validate requirement quality with checklists, then generate dependency-ordered
   tasks that include tests and exact paths.
6. Run cross-artifact analysis. Implementation is blocked until there are no
   CRITICAL or HIGH findings and every buildable requirement maps to a task.
7. Implement in task order, mark only verified tasks complete, and stop at the first
   failed non-parallel task.
8. Run local tests, Foxy build/tests, and non-motion runtime checks before requesting
   the user's physical-test safety confirmation.

## Governance

This constitution supersedes conflicting project practices for the ROS2 navigation
feature. Amendments require an explicit rationale, a synchronization review of
dependent templates and guidance, and semantic versioning: MAJOR for incompatible
principle changes, MINOR for new or materially expanded principles, and PATCH for
clarifications. Every specification, implementation plan, task list, review, and
physical-test record MUST demonstrate compliance. Safety exceptions cannot be
approved implicitly; they require an explicit constitution amendment and user
authorization. `AGENTS.md` and the current feature plan provide operational context
but cannot weaken these rules.

**Version**: 1.0.0 | **Ratified**: 2026-07-12 | **Last Amended**: 2026-07-12
