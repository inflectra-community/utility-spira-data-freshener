# SpiraFreshener

A config-driven Python tool that injects freshly generated project artifacts into a Spira demo project via the REST API v7. Run one command before a customer demo and your dashboard widgets light up with recent activity.

## What It Does

SpiraFreshener generates realistic, recent artifacts and POSTs them into your target Spira product:

| Artifact | What gets created |
|---|---|
| **Test Runs** | Automated test executions against existing test cases, dated within the last N days |
| **Incidents** | Bugs/enhancements with realistic names, descriptions, priorities, and statuses |
| **Tasks** | Work items linked to existing requirements, with effort estimates and date ranges |

All artifacts are assigned to real team members and associated with existing releases in the project. Statuses and priorities follow configurable weighted distributions so the data looks like a healthy (or unhealthy — your choice) project.

## Prerequisites

- Python 3.11+
- A Spira instance (SpiraTest, SpiraTeam, or SpiraPlan) with API access
- A Spira user with sufficient permissions (Product Owner or System Admin recommended)

## Setup

1. **Clone the repo**

```
git clone https://github.com/dermotcanniffe/SpiraFreshener.git
cd SpiraFreshener
```

2. **Install dependencies**

```
pip install -r requirements.txt
```

3. **Configure credentials**

Copy the example env file and fill in your Spira details:

```
cp .env.example .env
```

Edit `.env`:

```
SPIRA_BASE_URL=https://your-instance.spiraservice.net/
SPIRA_USERNAME=your-username
SPIRA_API_KEY={your-api-key}
```

Your API key is your Spira RSS token. Find it under your user profile in Spira — include the curly braces.

4. **Configure generation parameters**

Copy the example config and set your target product ID:

```
cp freshener-config.example.json freshener-config.json
```

Edit `freshener-config.json` — at minimum, set `project_id` to the Spira product you want to freshen.

5. **Run it**

```
python main.py
```

## Usage

```bash
# Generate and inject (the normal demo-prep workflow)
python main.py

# Preview what would be injected without touching Spira
python main.py --dry-run

# Use a specific config file (e.g. per-customer configs)
python main.py acme-config.json

# Save the payload to a specific file
python main.py --output my-payload.json

# Enable verbose logging (full HTTP request/response details)
python main.py --verbose

# Write logs to a file in addition to stdout
python main.py --log-file run.log
```

## How It Works

1. **Loads credentials** from `.env` and generation parameters from `freshener-config.json`
2. **Fetches project context** — existing test cases, requirements, releases, and active team members from the target product
3. **Generates artifacts** — randomised but realistic data using configured counts and weighted distributions
4. **Writes a JSON payload** — a complete record of everything generated (timestamped, replayable)
5. **Injects into Spira** — POSTs each artifact to the REST API, logging successes and skipping failures
6. **Prints a summary** — per-type created/failed counts

In `--dry-run` mode, steps 1–4 execute normally but step 5 is skipped.

## Configuration Reference

```json
{
  "project_id": 45,
  "recency_window_days": 30,
  "dry_run": false,
  "test_runs": {
    "count": 20,
    "status_weights": {
      "Passed": 60,
      "Failed": 20,
      "Blocked": 10,
      "Caution": 10
    }
  },
  "incidents": {
    "count": 10,
    "types": ["Bug", "Enhancement", "Issue", "Risk"],
    "priority_weights": {
      "Critical": 10,
      "High": 25,
      "Medium": 45,
      "Low": 20
    },
    "statuses": ["Open", "In Progress", "Resolved", "Closed"]
  },
  "tasks": {
    "count": 10,
    "status_weights": {
      "Not Started": 20,
      "In Progress": 40,
      "Completed": 25,
      "Blocked": 10,
      "Deferred": 5
    },
    "min_effort_hours": 1.0,
    "max_effort_hours": 16.0
  },
  "allocations": {
    "min_allocation_hours": 20.0,
    "max_allocation_hours": 40.0,
    "time_entry_count": 20,
    "min_time_entry_hours": 0.5,
    "max_time_entry_hours": 8.0
  }
}
```

| Field | Required | Description |
|---|---|---|
| `project_id` | Yes | The Spira product ID to inject artifacts into |
| `recency_window_days` | No | How far back to date artifacts (default: 30) |
| `dry_run` | No | Skip injection when `true` (default: false) |
| `test_runs.count` | No | Number of test runs to generate (default: 20) |
| `test_runs.status_weights` | No | Weighted distribution for pass/fail/blocked/caution |
| `incidents.count` | No | Number of incidents to generate (default: 10) |
| `incidents.types` | No | List of incident type names |
| `incidents.priority_weights` | No | Weighted distribution for priorities |
| `incidents.statuses` | No | List of incident status names |
| `tasks.count` | No | Number of tasks to generate (default: 10) |
| `tasks.status_weights` | No | Weighted distribution for task statuses |
| `tasks.min_effort_hours` | No | Minimum effort estimate in hours (default: 1.0) |
| `tasks.max_effort_hours` | No | Maximum effort estimate in hours (default: 16.0) |

## Important Notes

- **SpiraFreshener does not create test cases or requirements.** It only creates *activity* (test runs, incidents, tasks) linked to whatever already exists in the product. Provision your demo product structure first using [SpiraProvisioner](https://github.com/dermotcanniffe/SpiraProvisioner) or the sample datasets.
- **Tasks require existing requirements.** If the target product has no requirements, task generation is skipped.
- **Test runs require existing test cases.** If the target product has no test cases, test run generation is skipped.
- **Resource allocations and time entries** are not yet supported via the Spira REST API (no create endpoint exists). These are generated in the payload file but skipped during injection.
- **The tool is safe to re-run.** Each execution creates new artifacts — it doesn't modify or delete existing ones.

## Project Structure

```
├── main.py                         # Entry point
├── freshener-config.json           # Your config (gitignored)
├── freshener-config.example.json   # Template to copy
├── .env                            # Your credentials (gitignored)
├── .env.example                    # Credential template
├── requirements.txt
└── spira_freshener/
    ├── client.py                   # HTTP client — auth, retries, error handling
    ├── config.py                   # Config loading and validation
    ├── models.py                   # Dataclasses for all artifact types
    ├── payload.py                  # JSON serialisation/deserialisation
    ├── runner.py                   # Orchestrates generation and injection
    └── services/
        ├── test_runs.py            # Test run generation and injection
        ├── incidents.py            # Incident generation and injection
        ├── tasks.py                # Task generation and injection
        └── allocations.py          # Resource allocation and time entry generation
```

## Multiple Demo Products

You can maintain multiple config files — one per customer, product, or demo scenario:

```bash
python main.py logistics-demo-config.json
python main.py healthcare-demo-config.json
python main.py stressed-project-config.json
```

Tune `status_weights` to tell different stories:
- **Healthy project**: Passed=80, Failed=10, Blocked=5, Caution=5
- **Project in trouble**: Passed=30, Failed=40, Blocked=20, Caution=10
- **Early-stage project**: Not Started=50, In Progress=30, Completed=10, Blocked=5, Deferred=5

## Authentication

Credentials are passed via query parameters on every request (`username` and `api-key`). They are never logged or printed. Keep your `.env` file out of source control — it is gitignored by default.
