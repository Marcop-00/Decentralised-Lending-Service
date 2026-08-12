const hre = require("hardhat");

async function main() {
  const [deployer, contributor, borrower] = await hre.ethers.getSigners();
  const minFee = hre.ethers.parseEther("0.001");

  const Oracle = await hre.ethers.getContractFactory("BitcoinOracle");
  const oracle = await Oracle.deploy(minFee);
  await oracle.waitForDeployment();

  const Pool = await hre.ethers.getContractFactory("FundingPool");
  const pool = await Pool.deploy(await oracle.getAddress());
  await pool.waitForDeployment();

  const measurements = [];

  async function record(label, fn) {
    const tx = await fn();
    const receipt = await tx.wait();
    measurements.push({ label, gasUsed: Number(receipt.gasUsed) });
  }

  const depositAmount = hre.ethers.parseEther("2");
  await record("contribute", () => pool.connect(contributor).contribute({ value: depositAmount }));

  await record("createProposal", () => pool.connect(borrower).createLoanProposal(
    borrower.address,
    "tb1qgasmeasure",
    hre.ethers.parseEther("1"),
    500,
    3600,
    30,
  ));

  await record("voteYes", () => pool.connect(contributor).voteOnProposal(1, true));

  await oracle.connect(deployer).updateBalance("tb1qgasmeasure", 100_000_000n, { value: minFee });

  await hre.network.provider.send("evm_increaseTime", [35]);
  await hre.network.provider.send("evm_mine");

  await record("executeLoan", () => pool.connect(borrower).executeApprovedLoan(1));

  const proposal = await pool.proposals(1);
  const loan = await hre.ethers.getContractAt("LoanContract", proposal.loanContract);
  const due = await loan.dueAmount();
  await record("repayLoan", () => loan.connect(borrower).repay({ value: due }));

  console.log("Gas measurements:");
  for (const m of measurements) {
    console.log(`${m.label}: ${m.gasUsed}`);
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
