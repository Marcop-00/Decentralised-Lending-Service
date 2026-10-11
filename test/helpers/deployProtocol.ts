import assert from "node:assert/strict";
import { network } from "hardhat";
import { parseEther, zeroAddress, type Hash } from "viem";

/** Each test gets a fresh Berlin chain, using the production proxy topology. */
export async function deployProtocol() {
  const connection = await network.create();
  const { viem, networkHelpers } = connection;
  const publicClient = await viem.getPublicClient();
  const wallets = await viem.getWalletClients();
  const [owner, contributor, smallContributor, borrower] = wallets;
  const oracle = await viem.deployContract("BitcoinOracle");
  const implementation = await viem.deployContract("FundingPool");
  const proxy = await viem.deployContract("FundingPoolProxy", [implementation.address, oracle.address]);
  const pool = await viem.getContractAt("FundingPool", proxy.address);

  async function receipt(hash: Hash) {
    const result = await publicClient.waitForTransactionReceipt({ hash });
    assert.equal(result.status, "success");
    // Berlin uses legacy transactions; some RPCs omit effectiveGasPrice from
    // their receipts, so read the price actually signed into that transaction.
    const effectiveGasPrice = result.effectiveGasPrice ?? (await publicClient.getTransaction({ hash })).gasPrice;
    if (effectiveGasPrice === undefined) throw new Error(`Missing transaction gas price: ${hash}`);
    return { ...result, effectiveGasPrice };
  }

  async function proposal(id: bigint) {
    const p = await pool.read.proposals([id]);
    return {
      borrower: p[0], btcAddress: p[1], principal: p[2], interestRate: p[3],
      durationBlocks: p[4], votingDeadlineBlock: p[5], yesVotes: p[6],
      noVotes: p[7], executed: p[8], loanContract: p[9],
    };
  }

  async function loanFor(id: bigint) {
    const { loanContract } = await proposal(id);
    assert.notEqual(loanContract, zeroAddress, "The proposal must produce a loan");
    return viem.getContractAt("LoanContract", loanContract);
  }

  async function createProposal(
    principal: bigint,
    options: { rate?: bigint; duration?: bigint; btcAddress?: string } = {},
  ) {
    const { rate = 10n, duration = 100n, btcAddress = "1TestLiquidityAddress" } = options;
    await receipt(await pool.write.createLoanProposal([
      borrower.account.address, btcAddress, principal, rate, duration, 12n,
    ], { account: borrower.account }));
    return pool.read.proposalCount();
  }

  async function updateOracle(btcAddress = "1TestLiquidityAddress", sats = 100n * 100_000_000n) {
    await receipt(await oracle.write.requestUpdate([btcAddress], {
      account: borrower.account, value: await oracle.read.minFee(),
    }));
    await receipt(await oracle.write.update([btcAddress, sats]));
  }

  async function approveLoan(
    principal: bigint,
    options: { rate?: bigint; duration?: bigint; voters?: typeof wallets } = {},
  ) {
    const id = await createProposal(principal, options);
    for (const voter of options.voters ?? [contributor]) {
      await receipt(await pool.write.voteOnProposal([id, true], { account: voter.account }));
    }
    await updateOracle();
    await networkHelpers.mine(12);
    await receipt(await pool.write.executeApprovedLoan([id], { account: borrower.account }));
    return { id, loan: await loanFor(id) };
  }

  return {
    ...connection, publicClient, wallets, owner, contributor, smallContributor, borrower,
    oracle, implementation, proxy, pool, receipt, proposal, loanFor,
    createProposal, updateOracle, approveLoan,
  };
}

export { parseEther, zeroAddress };
