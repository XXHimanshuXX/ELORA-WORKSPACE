"""Throwaway: dump the full generated CSS so the frontend uses real names."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from elora.core.aesthetic import css_variables, current_tokens  # noqa: E402

tokens = current_tokens()
css = css_variables(tokens)
print(css)
print()
print("=== non-colour token groups ===")
for group in ("typography", "space", "radius", "motion", "elevation", "density"):
    print(f"{group}: {tokens[group]}")
print()
print("traits:", tokens["traits"])
