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

### Testing agent locally

### Testing service locally

Ensure that the packages are hashed and configured:
- `autonomy analyse service --public-id valory/governatooorr:0.1.0`
- `autonomy hash all`
- `autonomy packages lock`
- `autonomy push-all --remote`

Then run the following commands:
1. `autonomy fetch valory/governatooorr:0.1.0 --service --local`
2. `cd governatooorr/`
3. `autonomy build-image`
4. `touch keys.json`
5. copy keys: https://docs.autonolas.network/open-autonomy/guides/deploy_service/#local-deployment
6. `autonomy deploy build keys.json -ltm`
7. `cd abci_build`
8. `chmod 755 persistent_data`
9. `sed -i '' 's/SKILL_GOVERNATOOORR_ABCI_MODELS_PARAMS_ARGS_SETUP_ALL_PARTICIPANTS=\[\]/SKILL_GOVERNATOOORR_ABCI_MODELS_PARAMS_ARGS_SETUP_ALL_PARTICIPANTS=\["0x15d34AAf54267DB7D7c367839AAf71A00a2C6A65"\]/g' docker-compose.yaml`
10. `autonomy deploy run`
11. in separate terminal: `docker logs abci0 --follow`
