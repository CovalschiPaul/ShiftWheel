"""Read build metadata without importing Qt or starting Windows hooks."""
import ast
from pathlib import Path
import re


def app_version():
    tree = ast.parse(Path(__file__).with_name("shiftwheel.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "VERSION" for t in node.targets):
            value = ast.literal_eval(node.value)
            if not isinstance(value, str) or not re.fullmatch(r"\d+\.\d+(?:\.\d+)?", value):
                raise ValueError("Invalid application version")
            return value
    raise ValueError("Missing application version")


if __name__ == "__main__":
    print(app_version())
