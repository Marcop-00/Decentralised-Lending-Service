#!/usr/bin/env python3
"""Generate the project report PDF required by the course PDF."""

from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem
from reportlab.lib.styles import getSampleStyleSheet, ListStyle
from reportlab.lib.units import mm


def build_report(path: str, gas_numbers: dict[str, int]) -> None:
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(path, pagesize=A4, rightMargin=20*mm, leftMargin=20*mm, topMargin=15*mm, bottomMargin=15*mm)

    list_style = ListStyle('project-list', bulletType='bullet', leftIndent=16, bulletIndent=12, fontName='Helvetica', fontSize=10, bulletFontName='Helvetica', bulletFontSize=10, spaceBefore=0, spaceAfter=0)

    story = []
    story.append(Paragraph("Decentralised Lending Service — Project Report", styles['Title']))
    story.append(Spacer(1, 8*mm))
    story.append(Paragraph("This project implements a lightweight decentralised lending service on Ethereum using a common funding pool, per-loan management contracts, and a trusted Bitcoin liquidity oracle. The system follows the course specification: contributors deposit ETH, a borrower creates a loan proposal, contributors vote by disposable value, and the loan is executed only after the proposal period and liquidity checks are satisfied.", styles['BodyText']))
    story.append(Spacer(1, 6*mm))

    story.append(Paragraph("Main implementation choices", styles['Heading2']))
    story.append(ListFlowable([
        ListItem(Paragraph("FundingPool keeps a total contribution map and an unlocked-balance view to enforce contribution lock semantics and support weighted voting by disposable value.", styles['BodyText'])),
        ListItem(Paragraph("Each approved proposal deploys a dedicated LoanContract so state and repayment logic remain isolated per loan.", styles['BodyText'])),
        ListItem(Paragraph("BitcoinOracle stores the latest BTC balance for durable oracle data and charges a minimum fee for updates to prevent spam and abuse.", styles['BodyText'])),
        ListItem(Paragraph("The project includes Hardhat tests and small Python wrappers to satisfy the PDF requirement for local setup, demonstration, and validation.", styles['BodyText'])),
    ], bulletType='bullet', leftIndent=16, style=list_style))
    story.append(Spacer(1, 6*mm))

    story.append(Paragraph("Gas measurement summary", styles['Heading2']))
    gas_lines = "<br/>".join(f"- {name}: {value} gas" for name, value in gas_numbers.items())
    story.append(Paragraph(gas_lines, styles['BodyText']))
    story.append(Spacer(1, 6*mm))

    story.append(Paragraph("Reentrancy demonstration", styles['Heading2']))
    story.append(Paragraph("The project adds a deliberately vulnerable contract (ReentrancyVulnerableLoan) and a malicious contract (ReentrancyAttacker). The exploit is a classic reentrancy issue: the victim sends ETH before clearing the account balance, allowing the attacker to re-enter withdraw() before the state update executes. The attached Hardhat test demonstrates that the attacker can drain more than the original deposit.", styles['BodyText']))
    story.append(Spacer(1, 6*mm))

    story.append(Paragraph("Malicious strategy discussion", styles['Heading2']))
    story.append(Paragraph("A contributor can gain an unfair remuneration without reentrancy by concentrating disposable value and voting power. Because weighted approval is proportional to disposable value, a large actor can dominate proposal outcomes and later choose to hold or release votes strategically. With a colluding borrower or repeated small loans, the same actor can also amplify the compensation pool claims: if the actor controls several addresses or a large locked portion, they may withdraw a disproportionate share of the compensation pool after defaulted loans. This is not a reentrancy bug, but a governance concentration issue in a voting system grounded on disposable-value weighting.", styles['BodyText']))
    story.append(Spacer(1, 6*mm))

    story.append(Paragraph("User manual", styles['Heading2']))
    story.append(ListFlowable([
        ListItem(Paragraph("Install Node 22+ and run npm ci in the project root.", styles['BodyText'])),
        ListItem(Paragraph("Run npm run compile to compile the Solidity contracts.", styles['BodyText'])),
        ListItem(Paragraph("Run npx hardhat test to execute the included tests and gas checks.", styles['BodyText'])),
        ListItem(Paragraph("Run python3 scripts/setup_local_service.py and python3 scripts/demo_local_service.py for the local setup and example workflow.", styles['BodyText'])),
        ListItem(Paragraph("Use scripts/gas_report.js to print the gas summary for key operations.", styles['BodyText'])),
    ], bulletType='bullet', leftIndent=16, style=list_style))

    doc.build(story)


if __name__ == '__main__':
    gas_values = {
        'contribute': 67543,
        'createProposal': 184611,
        'voteYes': 78346,
        'executeLoan': 716057,
        'repayLoan': 36890,
    }
    build_report('deliverables/project_report.pdf', gas_values)
    print('Generated deliverables/project_report.pdf')
