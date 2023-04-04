# governatooorr

The Governatooorr is an autonomous, AI-powered delegate that votes on on-chain governance proposals on the Ethereum mainnet (and later off-chain governance proposals on Snapshot).

- Clone the repository:

      git clone https://github.com/valory-xyz/governatooorr.git

- System requirements:

    - Python `>= 3.7`
    - [Tendermint](https://docs.tendermint.com/v0.34/introduction/install.html) `==0.34.19`
    - [IPFS node](https://docs.ipfs.io/install/command-line/#official-distributions) `==v0.6.0`
    - [Pipenv](https://pipenv.pypa.io/en/latest/installation/) `>=2021.x.xx`
    - [Docker Engine](https://docs.docker.com/engine/install/)
    - [Docker Compose](https://docs.docker.com/compose/install/)

- Pull pre-built images:

      docker pull valory/autonolas-registries:latest
      docker pull valory/safe-contract-net:latest

- Create development environment:

      make new_env && pipenv shell

- Configure command line:

      autonomy init --reset --author valory --remote --ipfs --ipfs-node "/dns/registry.autonolas.tech/tcp/443/https"

- Pull packages:

      autonomy packages sync --update-packages

## Development

### Testing service locally against a local mainnet fork

Install Ganache, curl and (optionally) jq:
- `sudo npm install ganache@7.7.7 --global`
- `sudo apt install curl jq`

Ensure that the packages are hashed and configured:
- `autonomy analyse service --public-id valory/governatooorr:0.1.0`
- `autonomy hash all`
- `autonomy packages lock`
- `autonomy push-all --remote`

Deploy a Safe setting your agent's address as owner:
- Create an Ethereum private key - public key pair for your agent
- Go to the [Safe web app](https://app.safe.global/) and click on "Create new safe".
- You'll be asked to connect your wallet (i.e., Metamask).
- Set your agent's public address as the safe owner.
- Sign the transaction with your wallet.

Then run the following commands:
1. `autonomy fetch valory/governatooorr:0.1.0 --service --local`
2. `cd governatooorr/`
3. `autonomy build-image`
4. `touch keys.json`
5. copy keys: https://docs.autonolas.network/open-autonomy/guides/deploy_service/#local-deployment

6. Prepare a `.env` file containing the following variables:
      ```
      OPENAI_API_KEY=<your_api_key>
      ETHEREUM_LEDGER_RPC=http://host.docker.internal:8545
      ETHEREUM_LEDGER_CHAIN_ID=1
      ALL_PARTICIPANTS='["<your_agent_public_address>"]'
      RESET_PAUSE_DURATION=10
      TALLY_API_KEY=<your_api_key>
      SAFE_CONTRACT_ADDRESS=<your_service_safe_address>
      ```
7. `autonomy deploy build keys.json -ltm`
8. Run a Ganache fork of mainnet. Your agent address will have a balance of 1ETH:

      `ganache --fork.network mainnet --wallet.deterministic=true --chain.chainId 1 --fork.blockNumber 16968287 --wallet.accounts <your_agent_private_key>,1000000000000000000 --server.host 0.0.0.0`

9. `autonomy deploy run --build-dir abci_build/`
10. in separate terminal: `docker logs abci0 --follow`

11. Test the service endpoints (in another terminal):
      ```bash
      # Get the current active proposals
      curl localhost:8000/proposals | jq

      # Get a specific proposal
      curl localhost:8000/proposal/76163227102829400813905636249925382285747891719849601732821246533951559697126 | jq

      # Post a delegation (the delegatedToken and governorAddress need to match a valid active proposal)
      curl --request POST localhost:8000/delegate --header 'Content-Type: application/json' --data-raw '{"address": "0x999999cf1046e68e36E1aA2E0E07105eDDD1f08E","delegatedToken": "0x610210AA5D51bf26CBce146A5992D2FEeBc27dB1","votingPreference": "EVIL","governorAddress": "0x1C9a7ced4CAdb9c5a65E564e73091912aaec7494","tokenBalance": 100}'

      # Get the delegations for a specific wallet address
      curl localhost:8000/delegations/0x999999cf1046e68e36E1aA2E0E07105eDDD1f08E | jq
      ```