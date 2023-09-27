#!/usr/bin/env bash

# Load env vars
export $(grep -v '^#' .env | xargs)

# Remove previous builds
# if [ -d "governatooorr" ]; then
#     echo $PASSWORD | sudo -S sudo rm -Rf governatooorr;
# fi

# Push packages and fetch service
# make formatters
# make generators
make clean

autonomy push-all

autonomy fetch --local --service valory/governatooorr_solana_local && cd governatooorr_solana_local

# Build the image
autonomy build-image

# Copy keys and build the deployment
cp $KEY_DIR/governatooorr_1_key.json ./keys.json

autonomy deploy build -ltm

# Run the deployment
autonomy deploy run --build-dir abci_build/