import hre from "hardhat";

const { ethers } = hre;

/** Deploys the production topology: oracle, UUPS implementation and proxy. */
export async function deployProtocol() {
  const OracleFactory = await ethers.getContractFactory("BitcoinOracle");
  const oracle = await OracleFactory.deploy();
  await oracle.waitForDeployment();

  const PoolFactory = await ethers.getContractFactory("FundingPool");
  const implementation = await PoolFactory.deploy();
  await implementation.waitForDeployment();

  const ProxyFactory = await ethers.getContractFactory("FundingPoolProxy");
  const proxy = await ProxyFactory.deploy(
    await implementation.getAddress(),
    await oracle.getAddress(),
  );
  await proxy.waitForDeployment();

  const pool = await ethers.getContractAt("FundingPool", await proxy.getAddress());
  return { pool, oracle, implementation, proxy };
}
