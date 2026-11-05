"""Render every measured scenario, grouped by its responsible contract."""

import json
from pathlib import Path


GROUPS = {
    "FundingPool / via proxy": [
        ("contribute_new", "contribute()", "New contributor"),
        ("withdraw_partial", "withdraw()", "Partial withdrawal"),
        ("withdraw_final", "withdraw()", "Final withdrawal"),
        ("createLoanProposal", "createLoanProposal()", "New proposal"),
        ("voteOnProposal", "voteOnProposal()", "YES vote"),
        ("executeApprovedLoan_approved", "executeApprovedLoan()", "Approved"),
        ("executeApprovedLoan_rejected", "executeApprovedLoan()", "Rejected"),
        ("claimInterestGain", "claimInterestGain()", "Claim accrued gain"),
        ("requestCompensation_paid", "requestCompensation()", "Reserve pays claim"),
        ("requestCompensation_empty", "requestCompensation()", "Reserve empty"),
        ("upgradeToAndCall", "upgradeToAndCall()", "Compatible V2"),
        ("terminate", "terminate()", "No active loans"),
    ],
    "LoanContract": [
        ("repay_partial", "repay()", "Partial installment"),
        ("repay_final", "repay()", "Final installment"),
        ("repay_late", "repay()", "Late repayment"),
        ("markDefaulted", "markDefaulted()", "Overdue loan"),
    ],
    "BitcoinOracle": [
        ("requestUpdate", "requestUpdate()", "Paid request"),
        ("update_new_address", "update()", "First nonzero balance"),
        ("update_existing_address", "update()", "Existing balance"),
        ("withdrawFees", "withdrawFees()", "Operator collects fees"),
    ],
}


def main():
    root = Path(__file__).resolve().parent
    operations = json.loads((root / "gas-measurements.json").read_text())["operations"]
    scenario_ids = [key for rows in GROUPS.values() for key, _, _ in rows]
    if len(scenario_ids) != len(set(scenario_ids)) or set(scenario_ids) != set(operations):
        raise ValueError("Gas table groups must include every measured scenario exactly once")

    lines = [
        r"\begingroup\fontsize{9}{11}\selectfont",
        r"\renewcommand{\arraystretch}{1.08}",
        r"\par\noindent\begin{tabularx}{\linewidth}{@{}lXr@{}}",
        r"\toprule",
        r"\textbf{Operation} & \textbf{Scenario} & \textbf{Gas units} \\",
        r"\midrule",
    ]
    for group, rows in GROUPS.items():
        lines.extend([
            r"\addlinespace[2pt]",
            r"\multicolumn{3}{l}{\cellcolor{Mist}\textbf{\color{Navy}" + group + r"}} \\",
        ])
        for key, function, scenario in rows:
            lines.append(
                r"\texttt{" + function + "} & " + scenario + " & "
                + f"{int(operations[key]):,}" + r" \\"
            )
    lines.extend([r"\bottomrule", r"\end{tabularx}\par", r"\endgroup"])
    (root / "gas-table.tex").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
