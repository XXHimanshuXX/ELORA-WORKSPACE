import os

with open('scratch/deck_funcs_exact.js', 'r', encoding='utf-8') as f:
    old_deck = f.read()

with open('overlay/app.js', 'r', encoding='utf-8') as f:
    app_js = f.read()

assert old_deck in app_js, "old_deck not found in overlay/app.js"
print("Exact match for old_deck confirmed!")
