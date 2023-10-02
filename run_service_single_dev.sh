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

autonomy fetch --local --service valory/governatooorr_local && cd governatooorr_local

# Build the image
autonomy build-image --dev

# Copy keys and build the deployment
cp $KEY_DIR/governatooorr_1_key.json ./keys.json

autonomy deploy build --dev --packages-dir /home/david/Valory/repos/governatooorr/packages --open-autonomy-dir /home/david/Valory/repos/open-autonomy/ --open-aea-dir /home/david/Valory/repos/open-aea/ -ltm

# Run the deployment
autonomy deploy run --build-dir abci_build/