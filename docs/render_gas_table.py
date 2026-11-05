"""Render every measured scenario, grouped by its responsible contract."""

import argparse
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


SCENARIOS_IT = {
    "contribute_new": "Nuovo contributore",
    "withdraw_partial": "Prelievo parziale",
    "withdraw_final": "Prelievo finale",
    "createLoanProposal": "Nuova proposta",
    "voteOnProposal": "Voto favorevole",
    "executeApprovedLoan_approved": "Proposta approvata",
    "executeApprovedLoan_rejected": "Proposta respinta",
    "claimInterestGain": "Riscossione del guadagno",
    "requestCompensation_paid": "Compensazione pagata",
    "requestCompensation_empty": "Riserva vuota",
    "upgradeToAndCall": "V2 compatibile",
    "terminate": "Nessun prestito attivo",
    "repay_partial": "Rata parziale",
    "repay_final": "Rata finale",
    "repay_late": "Rimborso in ritardo",
    "markDefaulted": "Prestito scaduto",
    "requestUpdate": "Richiesta a pagamento",
    "update_new_address": "Primo saldo non nullo",
    "update_existing_address": "Saldo già presente",
    "withdrawFees": "Riscossione delle commissioni",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", choices=("en", "it"), default="en",
                        help="Table language; defaults to the original English output")
    language = parser.parse_args().language
    root = Path(__file__).resolve().parent
    operations = json.loads((root / "gas-measurements.json").read_text())["operations"]
    scenario_ids = [key for rows in GROUPS.values() for key, _, _ in rows]
    if len(scenario_ids) != len(set(scenario_ids)) or set(scenario_ids) != set(operations):
        raise ValueError("Gas table groups must include every measured scenario exactly once")
    if language == "it" and set(SCENARIOS_IT) != set(operations):
        raise ValueError("Italian labels must include every measured scenario exactly once")

    lines = [
        r"\begingroup\fontsize{9}{11}\selectfont",
        r"\renewcommand{\arraystretch}{1.08}",
        r"\par\noindent\begin{tabularx}{\linewidth}{@{}lXr@{}}",
        r"\toprule",
        (r"\textbf{Operazione} & \textbf{Scenario} & \textbf{Unità di gas} \\" if language == "it"
         else r"\textbf{Operation} & \textbf{Scenario} & \textbf{Gas units} \\"),
        r"\midrule",
    ]
    for group, rows in GROUPS.items():
        title = "FundingPool / tramite proxy" if language == "it" and group == "FundingPool / via proxy" else group
        lines.extend([
            r"\addlinespace[2pt]",
            r"\multicolumn{3}{l}{\cellcolor{Mist}\textbf{\color{Navy}" + title + r"}} \\",
        ])
        for key, function, scenario in rows:
            label = SCENARIOS_IT[key] if language == "it" else scenario
            value = f"{int(operations[key]):,}"
            if language == "it":
                value = value.replace(",", ".")
            lines.append(
                r"\texttt{" + function + "} & " + label + " & " + value + r" \\"
            )
    lines.extend([r"\bottomrule", r"\end{tabularx}\par", r"\endgroup"])
    filename = "gas-table-it.tex" if language == "it" else "gas-table.tex"
    (root / filename).write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
