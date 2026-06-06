# OnePlanner

Manage Microsoft Project for the Web schedules via the OnePlanner local REST API running on port 3100. All operations use human-readable names — GUIDs are resolved internally for a seamless experience.

## Features

- Task management: create, update, and delete tasks
- Resource assignment to tasks
- Bucket management for task organization
- Schedule queries and timeline views
- Human-readable name resolution (no manual GUID handling)
- Local REST API integration on port 3100

## Usage

Trigger phrases: "oneplanner", "project schedule", "manage tasks", "project plan".

Examples:
- "Create a new task in the Design bucket"
- "Assign the review task to the test team"
- "Show the current project schedule"

## Prerequisites

- OnePlanner server running on port 3100 (`npm run dev:server`)
- Python >= 3.11
- Workspace at `C:\Projects\OnePlanner`
