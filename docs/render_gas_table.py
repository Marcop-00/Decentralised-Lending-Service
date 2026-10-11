"""Regenerate the report table from measured receipts, not manually copied figures."""
import json
from pathlib import Path
root = Path(__file__).resolve().parent
data = json.loads((root / "gas-measurements.json").read_text())
lines = [r"\begin{center}\small", r"\begin{tabular}{lr}", r"\toprule",
         r"Operation / scenario & Gas units \\", r"\midrule"]
for name, value in data["operations"].items():
    label = name.replace("_", r"\_")
    lines.append(r"\texttt{" + label + "} & " + f"{int(value):,}" + r" \\")
lines += [r"\bottomrule", r"\end{tabular}", r"\end{center}"]
(root / "gas-table.tex").write_text("\n".join(lines) + "\n")
