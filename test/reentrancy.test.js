import { expect } from "chai";
import assert from "assert";
import hre from "hardhat";
import helpers from "@nomicfoundation/hardhat-network-helpers";

const { ethers, network } = hre;
const { time } = helpers;

describe("Reentrancy vulnerability demo", function () {
  it("shows a reentrancy exploit against the vulnerable contract", async function () {
    const [owner] = await ethers.getSigners();

    const Vulnerable = await ethers.getContractFactory("ReentrancyVulnerableLoan");
    const vulnerable = await Vulnerable.deploy();
    await vulnerable.waitForDeployment();

    const attackerOwner = await ethers.getSigners();
    const attacker = attackerOwner[1];

    await vulnerable.connect(owner).deposit({ value: ethers.parseEther("10") });

    const Attacker = await ethers.getContractFactory("ReentrancyAttacker");
    const attackerContract = await Attacker.deploy(await vulnerable.getAddress());
    await attackerContract.waitForDeployment();

    const before = await ethers.provider.getBalance(await vulnerable.getAddress());
    await attackerContract.attack({ value: ethers.parseEther("1") });
    const after = await ethers.provider.getBalance(await vulnerable.getAddress());

    assert.ok(after < before, "Victim contract should lose funds during reentrancy");
    assert.ok(before > after + ethers.parseEther("1"), "The reentrancy attack should drain more than one deposit");
  });
});
