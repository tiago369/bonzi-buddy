"""
Todoist integration - task reading, creation, and due-date reminders.

Reads TODOIST_API_TOKEN from the environment (or a local `.env` file, kept
out of git - see .gitignore). Get a token from Todoist: Settings ->
Integrations -> Developer -> API token.
"""
import os

import requests

API_BASE = "https://api.todoist.com/api/v1"
REQUEST_TIMEOUT = 10

# Maps a friendly "when" bucket to a Todoist filter query
# (https://todoist.com/help/articles/introduction-to-filters).
WHEN_FILTERS = {
    "today": "today",
    "overdue": "overdue",
    "today_or_overdue": "today | overdue",
    "upcoming": "due before: +7 days",
    "all": "",
}


def load_env_file(path=".env"):
    """Tiny hand-rolled .env loader (avoids adding python-dotenv as a
    dependency for just one file)."""
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


LIST_TASKS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "list_tasks",
        "description": "Lists the user's active Todoist tasks for a given time range.",
        "parameters": {
            "type": "object",
            "properties": {
                "when": {
                    "type": "string",
                    "enum": list(WHEN_FILTERS.keys()),
                    "description": (
                        "Which tasks to fetch: 'today', 'overdue', "
                        "'today_or_overdue', 'upcoming' (next 7 days), or 'all'."
                    ),
                }
            },
            "required": ["when"],
        },
    },
}

ADD_TASK_SCHEMA = {
    "type": "function",
    "function": {
        "name": "add_task",
        "description": "Creates a new Todoist task for the user.",
        "parameters": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "Only the task's action/text - do NOT include any date, time, or project name in it, those go in 'due'/'project' instead.",
                },
                "due": {
                    "type": "string",
                    "description": (
                        "Optional due date/time in natural Portuguese, "
                        "e.g. 'amanha as 10h' or 'toda sexta'."
                    ),
                },
                "project": {
                    "type": "string",
                    "description": (
                        "Optional project name to file the task under (matched "
                        "case-insensitively against the user's existing Todoist "
                        "projects). Leave empty for the default Inbox."
                    ),
                },
            },
            "required": ["content"],
        },
    },
}


MOVE_TASK_SCHEMA = {
    "type": "function",
    "function": {
        "name": "move_task_to_project",
        "description": (
            "Moves a task to a different Todoist project. If the user just "
            "told you which task (e.g. right after you asked which project "
            "a newly-created task should go in), you can omit task_content "
            "and it will apply to the most recently created/mentioned task."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": "The project name to move the task into.",
                },
                "task_content": {
                    "type": "string",
                    "description": (
                        "Optional: text to find the task by (matched against "
                        "existing task content). Leave empty to use the most "
                        "recently created/referenced task."
                    ),
                },
            },
            "required": ["project"],
        },
    },
}


class TodoistClient:
    def __init__(self, token=None):
        load_env_file()
        self.token = token or os.environ.get("TODOIST_API_TOKEN")
        self.last_task_id = None

    def is_configured(self):
        return bool(self.token)

    def _headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    def list_tasks(self, when="today_or_overdue"):
        """Returns a list of active tasks for the given bucket
        ("today", "overdue", "today_or_overdue", "upcoming", "all").
        Note: Todoist's newer unified API (api/v1) ignores a plain
        `filter` param on GET /tasks - filter queries need the dedicated
        /tasks/filter endpoint with a `query` param instead."""
        if not self.is_configured():
            raise RuntimeError("Todoist isn't configured (missing TODOIST_API_TOKEN).")

        filter_query = WHEN_FILTERS.get(when, when)
        if filter_query:
            url = f"{API_BASE}/tasks/filter"
            params = {"query": filter_query}
        else:
            url = f"{API_BASE}/tasks"
            params = {}

        response = requests.get(url, headers=self._headers(), params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        tasks = response.json()["results"]
        return [
            {
                "id": task["id"],
                "content": task["content"],
                "due": (task.get("due") or {}).get("string"),
                "priority": task.get("priority"),
            }
            for task in tasks
        ]

    def list_projects(self):
        """Returns the user's Todoist projects as a list of {id, name}."""
        if not self.is_configured():
            raise RuntimeError("Todoist isn't configured (missing TODOIST_API_TOKEN).")
        response = requests.get(f"{API_BASE}/projects", headers=self._headers(), timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return [{"id": p["id"], "name": p["name"]} for p in response.json()["results"]]

    def _resolve_project_id(self, project_name):
        """Case-insensitively matches a project name to its id. Also
        strips a leading 'projeto '/'project ' since a user (or the model
        relaying what they said) may include that word as part of the
        name, e.g. 'projeto trabalho' when the real project is 'trabalho'.
        Returns (project_id_or_None, note_or_None)."""
        cleaned = project_name.strip()
        for prefix in ("projeto ", "project "):
            if cleaned.lower().startswith(prefix):
                cleaned = cleaned[len(prefix):].strip()

        projects = self.list_projects()
        for project in projects:
            if project["name"].strip().lower() == cleaned.lower():
                return project["id"], None

        available = ", ".join(p["name"] for p in projects)
        return None, f"no project named '{project_name}' found (available: {available}); used Inbox instead"

    def add_task(self, content, due=None, project=None):
        """Creates a new task. `due` accepts natural language (in
        Portuguese - e.g. "amanha as 10h", "toda sexta") thanks to
        Todoist's own date parser. `project`, if given, is matched
        case-insensitively against the user's existing projects."""
        if not self.is_configured():
            raise RuntimeError("Todoist isn't configured (missing TODOIST_API_TOKEN).")

        payload = {"content": content}
        if due:
            payload["due_string"] = due
            payload["due_lang"] = "pt"

        project_note = None
        if project:
            project_id, project_note = self._resolve_project_id(project)
            if project_id:
                payload["project_id"] = project_id

        response = requests.post(
            f"{API_BASE}/tasks", headers=self._headers(), json=payload, timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        task = response.json()
        self.last_task_id = task["id"]
        result = {
            "id": task["id"],
            "content": task["content"],
            "due": (task.get("due") or {}).get("string"),
            "project_id": task.get("project_id"),
        }
        if project_note:
            result["note"] = project_note
        return result

    def move_task_to_project(self, project, task_content=None):
        """Moves a task (found by content match, or the last created/
        touched task if task_content is omitted) into a different project.
        Uses the dedicated /tasks/{id}/move endpoint - Todoist's regular
        task-update endpoint rejects project_id as a field."""
        if not self.is_configured():
            raise RuntimeError("Todoist isn't configured (missing TODOIST_API_TOKEN).")

        task_id = None
        if task_content:
            for task in self.list_tasks(when="all"):
                if task_content.strip().lower() in task["content"].lower():
                    task_id = task["id"]
                    break
        if task_id is None:
            task_id = self.last_task_id
        if task_id is None:
            return {"error": "no task specified and none created/referenced yet this session"}

        project_id, project_note = self._resolve_project_id(project)
        if project_id is None:
            return {"error": project_note}

        response = requests.post(
            f"{API_BASE}/tasks/{task_id}/move",
            headers=self._headers(), json={"project_id": project_id}, timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        task = response.json()
        self.last_task_id = task["id"]
        return {"id": task["id"], "content": task["content"], "project_id": task["project_id"]}
