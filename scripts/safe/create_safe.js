/*global process*/

const { ethers } = require("ethers");

async function main() {
    const url = "http://localhost:8545";
    const provider = new ethers.providers.JsonRpcProvider(url);
    await provider.getBlockNumber().then((result) => {
        console.log("Current block number: " + result);
    });

    const fs = require("fs");
    const globalsFile = "keys.json";
    const dataFromJSON = fs.readFileSync(globalsFile, "utf8");
    const parsedData = JSON.parse(dataFromJSON);

    const safeContracts = require("@gnosis.pm/safe-contracts");
    // The default Safe address for the majority of networks
    const safeAddress = "0xd9Db270c1B5E3Bd161E8c8503c55cEABeE709552";
    const safeJSON = "scripts/safe/node_modules/@gnosis.pm/safe-contracts/build/artifacts/contracts/GnosisSafe.sol/GnosisSafe.json";
    let contractFromJSON = fs.readFileSync(safeJSON, "utf8");
    let parsedFile = JSON.parse(contractFromJSON);
    const safeABI = parsedFile["abi"];
    const gnosisSafe = new ethers.Contract(safeAddress, safeABI, provider);
    //await ethers.getContractAt(safeABI, safeAddress);

    // Get the account information from the JSON file
    const account = parsedData[0].address;
    const threshold = 1;
    const AddressZero = ethers.constants.AddressZero;
    // The default compatibility fallback handler address for the majority of networks
    const callbackHandlerAddress = "0xf48f2B2d2a534e402487b3ee7C18c33Aec0Fe5e4";

    // Set up safe creation data
    const setupData = gnosisSafe.interface.encodeFunctionData(
        "setup",
        // signers, threshold, to_address, data, fallback_handler, payment_token, payment, payment_receiver
        [[account], threshold, AddressZero, "0x", callbackHandlerAddress, AddressZero, 0, AddressZero]
    );

    // Get the safe proxy factory
    const factoryJSON = "scripts/safe/node_modules/@gnosis.pm/safe-contracts/build/artifacts/contracts/proxies/GnosisSafeProxyFactory.sol/GnosisSafeProxyFactory.json";
    contractFromJSON = fs.readFileSync(factoryJSON, "utf8");
    parsedFile = JSON.parse(contractFromJSON);
    const factoryABI = parsedFile["abi"];

    // The default Safe address for the majority of networks
    const factoryAddress = "0xa6B71E26C5e0845f74c812102Ca7114b6a896AB2";
        // Get the gnosis safe proxy factory instance
    const gnosisSafeProxyFactory = new ethers.Contract(factoryAddress, factoryABI, provider);//await ethers.getContractAt(factoryABI, factoryAddress);

    // Create a safe contract
    const signer = await provider.getSigner();
    const proxyAddress = await safeContracts.calculateProxyAddress(gnosisSafeProxyFactory, safeAddress, setupData, 0);
    // Use the timestamp as a nonce / salt of the created safe contract, use it instead of zero, if needed
    // const salt = Math.floor(Date.now() / 1000);
    const salt = 0;
    await gnosisSafeProxyFactory.connect(signer).createProxyWithNonce(safeAddress, setupData, salt).then((tx) => tx.wait());

    // Checked the address of the deployed
    const multisig = new ethers.Contract(proxyAddress, safeABI, provider);
    //await ethers.getContractAt(safeABI, proxyAddress);
    if (multisig.address == proxyAddress) {
        console.log("Deployed Safe contract at:", proxyAddress);
    }
}

main()
    .then(() => process.exit(0))
    .catch((error) => {
        console.error(error);
        process.exit(1);
    });
