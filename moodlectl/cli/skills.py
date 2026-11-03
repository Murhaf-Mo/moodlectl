"""Discover bundled agent instructions without requiring a Moodle session."""
from pathlib import Path

import typer
import yaml

app = typer.Typer(help="Discover and read bundled AI agent skills.")
_ROOT = Path(__file__).resolve().parents[1] / "agent_skills"


def _available() -> dict[str, Path]:
    return {p.name: p for p in sorted(_ROOT.iterdir()) if (p / "SKILL.md").is_file()}


def _resolve(name: str) -> Path:
    folder = _available().get(name)
    if folder is None:
        raise typer.BadParameter(f"Unknown skill {name!r}. Run moodlectl skills list.")
    return folder


@app.command("list")
def list_skills() -> None:
    """List bundled skill names and when to use them."""
    for name, folder in _available().items():
        content = (folder / "SKILL.md").read_text(encoding="utf-8")
        metadata = yaml.safe_load(content.split("---", 2)[1])
        typer.echo(f"{name}\t{metadata['description']}")


@app.command("show")
def show_skill(name: str = typer.Argument(..., help="Name from skills list.")) -> None:
    """Print a skill's complete Markdown instructions."""
    typer.echo((_resolve(name) / "SKILL.md").read_text(encoding="utf-8"), nl=False)


@app.command("path")
def skill_path(name: str = typer.Argument(..., help="Name from skills list.")) -> None:
    """Print the skill folder containing SKILL.md and its supporting references."""
    typer.echo(str(_resolve(name)))
