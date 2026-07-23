"""Helper for not-yet-built pages (kept until each phase fills them in)."""
from flask import render_template


def placeholder(title: str, phase: str, icon: str = "🛠️"):
    return render_template("placeholder.html", title=title, phase=phase, icon=icon)
