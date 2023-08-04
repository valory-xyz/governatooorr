# Governatooorr

The Governatooorr is an autonomous, AI-powered delegate that votes on on-chain governance proposals on both the Ethereum and Solana networks (and later off-chain governance proposals on Snapshot on the Ethereum network).

- Clone the repository:

      git clone https://github.com/valory-xyz/governatooorr.git

- System requirements:

    - Python `>= 3.7`
    - [Tendermint](https://docs.tendermint.com/v0.34/introduction/install.html) `==0.34.19`
    - [IPFS node](https://docs.ipfs.io/install/command-line/#official-distributions) `==v0.6.0`
    - [Pipenv](https://pipenv.pypa.io/en/latest/installation/) `>=2021.x.xx`
    - [Docker Engine](https://docs.docker.com/engine/install/)
    - [Docker Compose](https://docs.docker.com/compose/install/)
    - [Node](https://nodejs.org/en) `>=18.6.0`
    - [Yarn](https://yarnpkg.com/getting-started/install) `>=1.22.19`

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

### Testing service locally against a local Ethereum mainnet fork

Install Ganache, curl and (optionally) jq:
- `sudo npm install ganache@7.7.7 --global`
- `sudo apt install curl jq`

Ensure that the packages are hashed and configured:
- `autonomy analyse service --public-id valory/governatooorr_local:0.1.0`
- `autonomy hash all`
- `autonomy packages lock`
- `autonomy push-all --remote`

Then run the following commands:
1. `autonomy fetch valory/governatooorr_local:0.1.0 --service --local`
2. `cd governatooorr_local/`
3. `autonomy build-image`
4. Create the agent's key:
    ```bash
    autonomy generate-key -n 1 ethereum
    ```
5. Create a `key::did` and a Ceramic stream using Ceramic's [JS client](https://developers.ceramic.network/build/javascript/installation/#js-http-client). The service will use this stream to store delegations.
6. Run a Ganache fork of mainnet. You need to use the agent's generated private key. Your agent address will have a balance of 1 ETH:

    ```bash
    ganache --fork.network mainnet --wallet.deterministic=true --chain.chainId 1 --fork.blockNumber 16968287 --wallet.accounts <agent_private_key>,1000000000000000000 --server.host 0.0.0.0
    ```
7. In a different terminal window deploy a [Safe](https://safe.global/) setting your agent's address as owner:
    ```bash
    yarn install --cwd scripts/safe
    node scripts/safe/create_safe.js
    ```
8. Prepare an `.env` file containing the following variables:
    ```text
    OPENAI_API_KEY=<your_api_key>
    TALLY_API_KEY=<your_api_key>
    ALL_PARTICIPANTS='["<your_agent_address>"]'
    SAFE_CONTRACT_ADDRESS=<your_safe_address>
    CERAMIC_DID_STR=<your_did_without_the_did:key_part>
    CERAMIC_DID_SEED=<your_did_seed>
    CERAMIC_STREAM_ID=<your_stream_id>
    ```
9. Execute `autonomy deploy build keys.json -ltm`
10. Execute `autonomy deploy run --build-dir abci_build/`
11. In a separate terminal, execute `docker logs abci0 -f`
12. Test the service endpoints (in another terminal):
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

### Running a single agent instance

You can run a single agent using `run_agent.sh` or `run_agent_solana.sh` scripts just run:

```
bash run_agent.sh
```

and in a separate terminal run:

```
bash run_tm.sh
```

**Note:** Fill in all of the API keys required by you agent in the `aea-config.yaml` file for the agent you're running before running the scripts.


