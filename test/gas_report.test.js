const { ethers, network } = require("hardhat");
const assert = require("assert");

describe("Gas report sanity checks", function () {
  it("runs the main operations and stores gas data", async function () {
    const [deployer, contributor, borrower] = await ethers.getSigners();
    const minFee = ethers.parseEther("0.001");

    const Oracle = await ethers.getContractFactory("BitcoinOracle");
    const oracle = await Oracle.deploy(minFee);
    await oracle.waitForDeployment();

    const Pool = await ethers.getContractFactory("FundingPool");
    const pool = await Pool.deploy(await oracle.getAddress());
    await pool.waitForDeployment();

    const depositAmount = ethers.parseEther("2");
    const tx1 = await pool.connect(contributor).contribute({ value: depositAmount });
    await tx1.wait();

    const tx2 = await pool.connect(borrower).createLoanProposal(
      borrower.address,
      "tb1qgasmeasure",
      ethers.parseEther("1"),
      500,
      3600,
      30,
    );
    await tx2.wait();

    const tx3 = await pool.connect(contributor).voteOnProposal(1, true);
    await tx3.wait();

    await oracle.connect(deployer).updateBalance("tb1qgasmeasure", 100_000_000n, { value: minFee });
    await network.provider.send("evm_increaseTime", [35]);
    await network.provider.send("evm_mine");

    const tx4 = await pool.connect(borrower).executeApprovedLoan(1);
    await tx4.wait();

    const proposal = await pool.proposals(1);
    const loan = await ethers.getContractAt("LoanContract", proposal.loanContract);
    const due = await loan.dueAmount();
    const tx5 = await loan.connect(borrower).repay({ value: due });
    await tx5.wait();

    assert.ok(tx1.gasLimit > 0n);
    assert.ok(tx2.gasLimit > 0n);
    assert.ok(tx3.gasLimit > 0n);
    assert.ok(tx4.gasLimit > 0n);
    assert.ok(tx5.gasLimit > 0n);
  });
});
