rm -r governatooorr_solana
find . -empty -type d -delete  # remove empty directories to avoid wrong hashes
autonomy packages lock
autonomy fetch --local --agent valory/governatooorr_solana && cd governatooorr_solana
autonomy generate-key ethereum
autonomy add-key ethereum ethereum_private_key.txt
autonomy generate-key solana
autonomy add-key solana solana_private_key.txt
autonomy issue-certificates
aea -s run