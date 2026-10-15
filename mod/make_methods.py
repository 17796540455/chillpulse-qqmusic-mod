"""Rewrite the mod's top-level GML functions into instance-variable methods.

The GameMaker runner only exposes script-asset functions under names derived
from the script asset, so new global functions injected by UTMT end up as
`gml_Script_<fn>@<script>` and cannot be called by their plain name.  Defining
them as methods on obj_controller instead (`qqm_step = function() {...};`)
sidesteps script registration entirely: every caller lives in one of
obj_controller's own events.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(os.path.dirname(HERE), "mods", "patch", "gml_Script_qqm_mod.gml")
DST = os.path.join(os.path.dirname(HERE), "mods", "patch", "qqm_methods.gml")


def main():
    lines = open(SRC, encoding="utf-8").read().splitlines()
    out = []
    converted = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r"^function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", line)
        if not m:
            out.append(line)
            i += 1
            continue
        name = m.group(1)
        out.append(re.sub(r"^function\s+" + name, name + " = function", line))
        # find the matching closing brace at column 0
        depth = 0
        j = i
        closed = False
        while j < len(lines):
            depth += lines[j].count("{") - lines[j].count("}")
            if j > i and depth == 0:
                out.append(lines[j] + ";")
                closed = True
                break
            if j > i:
                out.append(lines[j])
            j += 1
        if not closed:
            print(f"!! unbalanced braces for {name}")
            return 1
        converted.append(name)
        i = j + 1

    text = "\n".join(out)
    with open(DST, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print(f"converted {len(converted)} functions -> {DST}")
    print("  " + ", ".join(converted))
    left = re.findall(r"^function\s+\w+", text, re.M)
    if left:
        print("!! still contains top-level function declarations:", left)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
