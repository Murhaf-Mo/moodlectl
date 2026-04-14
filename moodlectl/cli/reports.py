"""Student reports CLI. (COMING SOON)"""
from __future__ import annotations

import typer

app = typer.Typer(help="Report commands (coming soon)")


@app.command("student")
def student_report(
    name: str = typer.Option(..., "--name", help="Student name"),
):
    """Generate a comprehensive report for a student. (Coming soon)"""
    typer.echo("Student reports coming soon.")
