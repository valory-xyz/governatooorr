# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023 Valory AG
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
#
# ------------------------------------------------------------------------------

"""This package contains round behaviours of ProposalVoterAbciApp."""

import json
from abc import ABC
from copy import deepcopy
from dataclasses import asdict
from typing import Generator, Optional, Set, Tuple, Type, cast

from eth_account.messages import _hash_eip191_message, encode_structured_data

from packages.valory.contracts.delegate.contract import DelegateContract
from packages.valory.contracts.gnosis_safe.contract import (
    GnosisSafeContract,
    SafeOperation,
)
from packages.valory.contracts.sign_message_lib.contract import SignMessageLibContract
from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.skills.abstract_round_abci.base import AbstractRound
from packages.valory.skills.abstract_round_abci.behaviours import (
    AbstractRoundBehaviour,
    BaseBehaviour,
)
from packages.valory.skills.abstract_round_abci.common import (
    RandomnessBehaviour,
    SelectKeeperBehaviour,
)
from packages.valory.skills.proposal_voter_abci.models import (
    MechCalls,
    Params,
    SharedState,
)
from packages.valory.skills.proposal_voter_abci.payloads import (
    DecisionMakingPayload,
    EstablishVotePayload,
    MechCallCheckPayload,
    PostTxDecisionMakingPayload,
    PostVoteDecisionMakingPayload,
    PrepareMechRequestPayload,
    PrepareVoteTransactionsPayload,
    SnapshotAPISendPayload,
    SnapshotAPISendRandomnessPayload,
    SnapshotAPISendSelectKeeperPayload,
)
from packages.valory.skills.proposal_voter_abci.rounds import (
    DecisionMakingRound,
    EstablishVoteRound,
    MechCallCheckRound,
    MechMetadata,
    PostTxDecisionMakingRound,
    PostVoteDecisionMakingRound,
    PrepareMechRequestRound,
    PrepareVoteTransactionsRound,
    ProposalVoterAbciApp,
    SnapshotAPISendRandomnessRound,
    SnapshotAPISendRound,
    SnapshotAPISendSelectKeeperRound,
    SynchronizedData,
)
from packages.valory.skills.transaction_settlement_abci.payload_tools import (
    hash_payload_to_hex,
)
from packages.valory.skills.proposal_voter_abci.prompt import vote_evaluation_prompt


SAFE_TX_GAS = 0
ETHER_VALUE = 0

VOTING_OPTIONS = "For, Against, and Abstain"
VOTES_TO_CODE = {"FOR": 0, "AGAINST": 1, "ABSTAIN": 2}

HTTP_OK = 200
MAX_RETRIES = 3
MAX_VOTE_RETRIES = 3


def fix_data_for_encoding(data):
    """Add missing required fields before signing"""
    fixed_data = deepcopy(data)
    fixed_data["message"]["proposal"] = bytes.fromhex(data["message"]["proposal"][2:])
    return fixed_data


def parse_mech_response(data: str) -> str:
    """Parse the data from the Mech response"""
    print(f"Parsing the mech response: {data}")
    start = data.find("{")
    end = data.find("}")
    sub_string = data[start : end + 1]
    try:
        return json.loads(sub_string)["vote"]
    except Exception:
        return "error"


class ProposalVoterBaseBehaviour(BaseBehaviour, ABC):
    """Base behaviour for the proposal_voter_abci skill."""

    @property
    def synchronized_data(self) -> SynchronizedData:
        """Return the synchronized data."""
        return cast(SynchronizedData, super().synchronized_data)

    @property
    def params(self) -> Params:
        """Return the params."""
        return cast(Params, super().params)

    @property
    def mech_calls(self) -> MechCalls:
        """Return the params."""
        return self.params.mech_calls


class MechCallCheckBehaviour(ProposalVoterBaseBehaviour):
    """TwitterMentionsCollectionBehaviour"""

    matching_round: Type[AbstractRound] = MechCallCheckRound

    def async_act(self) -> Generator:
        """Do the act, supporting asynchronous execution."""
        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            current_time = cast(
                SharedState, self.context.state
            ).round_sequence.last_round_transition_timestamp.timestamp()
            # Reset the window if the window expired before checking
            self.mech_calls.reset(current_time=current_time)
            if self.mech_calls.max_calls_reached():
                content = None
            else:
                content = MechCallCheckRound.CALLS_REMAINING
        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(
                payload=MechCallCheckPayload(
                    sender=self.context.agent_address,
                    content=content,
                )
            )
            yield from self.wait_until_round_end()
        self.set_done()


class PrepareMechRequestBehaviour(ProposalVoterBaseBehaviour):
    """PrepareMechRequestBehaviour"""

    matching_round: Type[AbstractRound] = PrepareMechRequestRound

    def async_act(self) -> Generator:
        """Do the act, supporting asynchronous execution."""

        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            (
                expiring_tally_proposals,
                mech_requests_tally,
            ) = self._get_expiring_tally_proposals()
            (
                expiring_snapshot_proposals,
                mech_requests_snapshot,
            ) = self._get_expiring_snapshot_proposals()

            expiring_proposals = {
                "tally": expiring_tally_proposals,
                "snapshot": expiring_snapshot_proposals,
            }

            mech_requests = mech_requests_tally
            mech_requests.extend(mech_requests_snapshot)

            sender = self.context.agent_address
            payload = PrepareMechRequestPayload(
                sender=sender,
                content=json.dumps(
                    {
                        "expiring_proposals": expiring_proposals,
                        "mech_requests": mech_requests,
                    },
                    sort_keys=True,
                ),
            )

        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()

        self.set_done()

    def _get_expiring_tally_proposals(self) -> Tuple[dict, list]:
        """Generate proposal votes"""

        target_proposals = self.synchronized_data.target_proposals["tally"]
        previous_expiring_proposals = self.synchronized_data.expiring_proposals["tally"]

        # Sort by expiration block
        sorted_target_proposals = list(
            sorted(target_proposals.values(), key=lambda ap: ap["remaining_blocks"])
        )

        # Get expiring proposals
        expiring_proposals = {
            ap["id"]: {"vote": None}
            for ap in sorted_target_proposals
            if ap["remaining_blocks"] <= self.params.voting_block_threshold
        }

        self.context.logger.info(
            f"There are {len(expiring_proposals)} finishing Tally proposals (erc20)"
        )

        # Get the proposals' vote intention
        mech_requests = []
        for proposal_id in expiring_proposals.keys():
            self.context.logger.info(
                f"Getting vote intention for proposal {proposal_id}"
            )

            proposal_token = target_proposals[proposal_id]["governor"]["tokens"][0][
                "id"
            ].split(":")[-1]

            # Get the service aggregated vote intention
            vote_intention = (
                self._get_service_vote_intention(  # either GOOD, EVIL or None
                    proposal_token
                )
            )
            self.context.logger.info(f"Vote intention: {vote_intention}")

            # Do not update the vote if the vote intention has not changed
            if (
                proposal_id in previous_expiring_proposals
                and "vote_intention" in previous_expiring_proposals[proposal_id]
                and previous_expiring_proposals[proposal_id]["vote_intention"]
                == vote_intention
            ):
                self.context.logger.info(
                    "Vote intention has not changed. Skipping proposal."
                )
                continue

            target_proposals[proposal_id]["vote_intention"] = vote_intention

            # Do not call the LLM until we have delegations for this proposal. FIXME: redundant?
            if not vote_intention:
                self.context.logger.info("No vote intention. Skipping proposal.")
                continue

            # Mech call preparation
            voting_intention_snippet = (
                "cause chaos to the protocol"
                if vote_intention == "evil"
                else "contribute positively to the protocol"
            )
            prompt_values = {
                "proposal": target_proposals[proposal_id]["title"]
                + "\n"
                + target_proposals[proposal_id]["description"],
                "voting_intention_snippet": voting_intention_snippet,
                "voting_options": VOTING_OPTIONS,
            }

            prompt = vote_evaluation_prompt.format(**prompt_values)

            self.context.logger.info(f"Sending LLM request...\n{prompt}")

            mech_requests.append(
                asdict(
                    MechMetadata(
                        nonce=proposal_id,
                        tool="openai-gpt-3.5-turbo",
                        prompt=prompt,
                    )
                )
            )
        return expiring_proposals, mech_requests

    def _get_service_vote_intention(self, token_address) -> Optional[str]:
        """Aggregate all the users' vote intentions to find the service's vote intention"""

        vote_preference_counts = {"GOOD": 0, "EVIL": 0}

        current_delegations = self.synchronized_data.ceramic_db["delegations"]
        current_delegations = list(
            filter(lambda d: token_address in d["token_address"], current_delegations)
        )

        # Do not express intention if we have no delegations
        if not current_delegations:
            self.context.logger.info(
                f"There are no delegations for token {token_address}"
            )
            return None

        # Count votes
        for delegation in current_delegations:
            if delegation["voting_preference"] in vote_preference_counts:
                vote_preference_counts[delegation["voting_preference"]] += int(
                    delegation["delegated_amount"]
                )

        # Sort the voring count by value
        sorted_preferences = sorted(
            vote_preference_counts.items(), key=lambda i: i[1], reverse=True
        )

        self.context.logger.info(
            f"_get_service_vote_intention = {sorted_preferences[0][0]}"
        )

        # Return the option with most votes
        return sorted_preferences[0][0]

    def _get_expiring_snapshot_proposals(
        self,
    ) -> Tuple[dict, list]:
        """Get votable snapshot proposals"""
        target_proposals = self.synchronized_data.target_proposals["snapshot"]

        # Sort by expiration block
        sorted_target_proposals = list(
            sorted(target_proposals.values(), key=lambda ap: ap["remaining_seconds"])
        )

        # Get expiring proposals
        expiring_proposals = {
            ap["id"]: {
                "id": ap["id"],
                "vote": None,
                "sent": False,
                "expiration": ap["end"],
                "space_id": ap["space"]["id"],
            }
            for ap in sorted_target_proposals
            if ap["remaining_seconds"] <= self.params.voting_seconds_threshold
        }

        self.context.logger.info(
            f"There are {len(expiring_proposals)} finishing snapshot proposals (erc20)"
        )

        # Mech call preparation
        mech_requests = []
        for proposal_id in expiring_proposals:
            proposal = target_proposals[proposal_id]
            prompt_values = {
                "proposal": proposal["title"] + "\n" + proposal["body"],
                "voting_options": ", ".join(proposal["choices"]),
                "voting_intention_snippet": "contribute positively to the protocol"
            }

            # Can't use .format() here because the prompt contains a json object
            prompt = vote_evaluation_prompt.replace(
                "{proposal}", prompt_values["proposal"]
            ).replace(
                "{voting_options}", prompt_values["voting_options"]
            ).replace(
                "{voting_intention_snippet}", prompt_values["voting_intention_snippet"]
            )

            self.context.logger.info(f"Sending LLM request: {prompt}")

            mech_requests.append(
                asdict(
                    MechMetadata(
                        nonce=proposal_id,
                        tool="openai-gpt-3.5-turbo",
                        prompt=prompt,
                    )
                )
            )

        return expiring_proposals, mech_requests


class EstablishVoteBehaviour(ProposalVoterBaseBehaviour):
    """EstablishVoteBehaviour"""

    matching_round: Type[AbstractRound] = EstablishVoteRound

    def async_act(self) -> Generator:
        """Do the act, supporting asynchronous execution."""
        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            mech_responses = self.synchronized_data.mech_responses
            expiring_proposals = self.synchronized_data.expiring_proposals
            tally_pending_proposal_ids = list(expiring_proposals["tally"].keys())
            snapshot_pending_proposal_ids = list(expiring_proposals["snapshot"].keys())

            for response in mech_responses:
                self.context.logger.info(
                    f"Processing mech response with nonce {response.nonce}"
                )

                # The request has not been responded
                if not response.result:
                    self.context.logger.info("No result. Skipping...")
                    continue

                # We cannot find the original proposal
                platform = None
                if response.nonce in tally_pending_proposal_ids:
                    platform = "tally"
                if response.nonce in snapshot_pending_proposal_ids:
                    platform = "snapshot"

                if not platform:
                    self.context.logger.info(
                        "Nonce not in pending proposals. Skipping..."
                    )
                    continue

                vote = parse_mech_response(response.result)

                # Tally
                if platform == "tally":
                    vote = vote.upper()
                    if vote not in VOTES_TO_CODE:
                        if self.params.default_tally_vote_on_error:
                            self.context.logger.info(
                                f"Invalid vote: {vote}. Using first vote option as fallback."
                            )
                            vote = list(VOTES_TO_CODE.keys())[0]
                        else:
                            self.context.logger.error(
                                f"Invalid vote: {vote}. Skipping proposal."
                            )
                            continue

                    self.context.logger.info(f"Vote: {vote}")

                    expiring_proposals["tally"][response.nonce]["vote"] = vote

                # Snapshot
                else:
                    proposal = self.synchronized_data.target_proposals["snapshot"][response.nonce]
                    if vote not in proposal["choices"]:
                        if self.params.default_snapshot_vote_on_error:
                            self.context.logger.info(
                                f"Invalid vote: {vote}. Using first vote option as fallback."
                            )
                            vote = proposal["choices"][0]
                        else:
                            self.context.logger.error(
                                f"Invalid vote: {vote}. Skipping proposal."
                            )
                            continue

                    self.context.logger.info(f"Vote: {vote}")

                    expiring_proposals["snapshot"][response.nonce]["vote"] = (
                        proposal["choices"].index(vote) + 1
                    )  # choices are 1-based indices

        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(
                payload=EstablishVotePayload(
                    sender=self.context.agent_address,
                    expiring_proposals=json.dumps(
                        {"expiring_proposals": expiring_proposals}, sort_keys=True
                    ),
                )
            )
            yield from self.wait_until_round_end()
        self.set_done()


class PrepareVoteTransactionsBehaviour(ProposalVoterBaseBehaviour):
    """PrepareVoteTransactionsBehaviour"""

    matching_round: Type[AbstractRound] = PrepareVoteTransactionsRound

    def _get_tally_tx_hash(
        self,
        governor_address: str,
        proposal_id: str,
        vote_code: int,
        safe_nonce: Optional[int],
    ) -> Generator[None, None, Optional[str]]:
        """Get the transaction hash of the Safe tx."""
        # Get the raw transaction from the Bravo Delegate contract
        contract_api_msg = yield from self.get_contract_api_response(
            performative=ContractApiMessage.Performative.GET_STATE,  # type: ignore
            contract_address=governor_address,
            contract_id=str(DelegateContract.contract_id),
            contract_callable="get_cast_vote_data",
            proposal_id=int(proposal_id),
            support=vote_code,
            chain_id="ethereum"
        )
        if (
            contract_api_msg.performative != ContractApiMessage.Performative.STATE
        ):  # pragma: nocover
            self.context.logger.warning(
                f"get_cast_vote_data unsuccessful!: {contract_api_msg}"
            )
            return None
        data = cast(bytes, contract_api_msg.state.body["data"])

        # Get the safe transaction hash
        ether_value = ETHER_VALUE
        safe_tx_gas = SAFE_TX_GAS

        contract_api_msg = yield from self.get_contract_api_response(
            performative=ContractApiMessage.Performative.GET_STATE,  # type: ignore
            contract_address=self.synchronized_data.safe_contract_address,
            contract_id=str(GnosisSafeContract.contract_id),
            contract_callable="get_raw_safe_transaction_hash",
            to_address=governor_address,
            value=ether_value,
            data=data,
            safe_tx_gas=safe_tx_gas,
            safe_nonce=safe_nonce,
            chain_id="ethereum"
        )
        if (
            contract_api_msg.performative != ContractApiMessage.Performative.STATE
        ):  # pragma: nocover
            self.context.logger.warning(
                f"get_raw_safe_transaction_hash unsuccessful!: {contract_api_msg}"
            )
            return None

        safe_tx_hash = cast(str, contract_api_msg.state.body["tx_hash"])
        safe_tx_hash = safe_tx_hash[2:]
        self.context.logger.info(f"Hash of the Safe transaction: {safe_tx_hash}")

        # temp hack:
        payload_string = hash_payload_to_hex(
            safe_tx_hash, ether_value, safe_tx_gas, governor_address, data
        )

        return payload_string

    def _get_snapshot_vote_data(self, proposal) -> dict:
        """Get the data for the EIP-712 signature"""

        now_timestamp = cast(
            SharedState, self.context.state
        ).round_sequence.last_round_transition_timestamp.timestamp()

        message = {
            "space": proposal["space_id"],
            "proposal": proposal["id"],
            "choice": proposal["vote"],
            "reason": "",
            "app": "Governatooorr",
            "metadata": "{}",
            "from": self.synchronized_data.safe_contract_address,
            "timestamp": int(now_timestamp),
        }

        # Build the data structure for the EIP712 signature
        data = {
            "domain": {"name": "snapshot", "version": "0.1.4"},
            "types": {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                ],
                "Vote": [
                    {"name": "from", "type": "address"},
                    {"name": "space", "type": "string"},
                    {"name": "timestamp", "type": "uint64"},
                    {"name": "proposal", "type": "bytes32"},
                    {"name": "choice", "type": "uint32"},
                    {"name": "reason", "type": "string"},
                    {"name": "app", "type": "string"},
                    {"name": "metadata", "type": "string"},
                ],
            },
            "primaryType": "Vote",
            "message": message,
        }

        return data

    def _get_snapshot_tx_hash(
        self, proposal, safe_nonce
    ) -> Generator[None, None, Tuple[Optional[str], dict]]:
        """Get the safe hash for the EIP-712 signature"""

        vote_data = self._get_snapshot_vote_data(proposal)
        snapshot_data_for_encoding = fix_data_for_encoding(vote_data)

        snapshot_api_data = {
            "address": self.synchronized_data.safe_contract_address,
            "data": vote_data,
            "sig": "0x",  # Snapshot retrieves the signature for votes performed by a safe
        }

        self.context.logger.info(f"Encoding snapshot message: {snapshot_api_data}")

        encoded_proposal_data = encode_structured_data(snapshot_data_for_encoding)
        safe_message = _hash_eip191_message(encoded_proposal_data)
        self.context.logger.info(f"Safe message: {safe_message.hex()}")
        signmessagelib_address = self.params.signmessagelib_address

        # Get the raw transaction from the SignMessageLib contract
        contract_api_msg = yield from self.get_contract_api_response(
            performative=ContractApiMessage.Performative.GET_STATE,  # type: ignore
            contract_address=signmessagelib_address,
            contract_id=str(SignMessageLibContract.contract_id),
            contract_callable="sign_message",
            data=safe_message,
            chain_id="ethereum"
        )
        if (
            contract_api_msg.performative != ContractApiMessage.Performative.STATE
        ):  # pragma: nocover
            self.context.logger.warning(
                f"sign_message unsuccessful!: {contract_api_msg}"
            )
            return None, snapshot_api_data
        data = cast(str, contract_api_msg.state.body["signature"])[2:]
        tx_data = bytes.fromhex(data)

        self.context.logger.info(f"Sign transaction tx_data: {tx_data}")

        # Get the safe transaction hash
        ether_value = ETHER_VALUE
        safe_tx_gas = SAFE_TX_GAS

        contract_api_msg = yield from self.get_contract_api_response(
            performative=ContractApiMessage.Performative.GET_STATE,  # type: ignore
            contract_address=self.synchronized_data.safe_contract_address,
            contract_id=str(GnosisSafeContract.contract_id),
            contract_callable="get_raw_safe_transaction_hash",
            to_address=signmessagelib_address,
            value=ether_value,
            data=tx_data,
            safe_tx_gas=safe_tx_gas,
            operation=SafeOperation.DELEGATE_CALL.value,
            safe_nonce=safe_nonce,
            chain_id="ethereum"
        )
        if (
            contract_api_msg.performative != ContractApiMessage.Performative.STATE
        ):  # pragma: nocover
            self.context.logger.warning(
                f"get_raw_safe_transaction_hash unsuccessful!: {contract_api_msg}"
            )
            return None, snapshot_api_data

        safe_tx_hash = cast(str, contract_api_msg.state.body["tx_hash"])
        safe_tx_hash = safe_tx_hash[2:]
        self.context.logger.info(f"Hash of the Safe transaction: {safe_tx_hash}")

        # temp hack:
        payload_string = hash_payload_to_hex(
            safe_tx_hash,
            ether_value,
            safe_tx_gas,
            signmessagelib_address,
            tx_data,
            SafeOperation.DELEGATE_CALL.value,
        )

        return payload_string, snapshot_api_data

    def _get_safe_nonce(
        self,
    ) -> Generator[None, None, Optional[int]]:
        """Get the safe nonce"""

        contract_api_msg = yield from self.get_contract_api_response(
            performative=ContractApiMessage.Performative.GET_STATE,  # type: ignore
            contract_address=self.synchronized_data.safe_contract_address,
            contract_id=str(GnosisSafeContract.contract_id),
            contract_callable="get_safe_nonce",
            chain_id="ethereum"
        )
        if (
            contract_api_msg.performative != ContractApiMessage.Performative.STATE
        ):  # pragma: nocover
            self.context.logger.warning(
                f"get_raw_safe_transaction_hash unsuccessful!: {contract_api_msg}"
            )
            return None

        safe_nonce = cast(str, contract_api_msg.state.body["safe_nonce"])
        self.context.logger.info(f"Safe nonce: {safe_nonce}")

        return int(safe_nonce)

    def async_act(self) -> Generator:
        """Do the act, supporting asynchronous execution."""

        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            expiring_proposals = self.synchronized_data.expiring_proposals
            pending_transactions = self.synchronized_data.pending_transactions

            safe_nonce = None
            if expiring_proposals["tally"] or expiring_proposals["snapshot"]:
                safe_nonce = yield from self._get_safe_nonce()

            # Tally
            for proposal_id, expiring_proposal in expiring_proposals["tally"].items():
                if proposal_id in pending_transactions["tally"]:
                    continue

                proposal = self.synchronized_data.target_proposals["tally"][proposal_id]

                if expiring_proposal["vote"] is None:
                    continue

                governor_address = proposal["governor"]["id"].split(":")[-1]
                vote_code = VOTES_TO_CODE[expiring_proposal["vote"]]

                self.context.logger.info(
                    f"Preparing transaction for Tally proposal {proposal_id} [governor={governor_address}]: vote_code={vote_code}"
                )

                tx_hash = yield from self._get_tally_tx_hash(
                    governor_address, proposal_id, vote_code, safe_nonce
                )

                if safe_nonce:
                    safe_nonce += 1

                pending_transactions["tally"][proposal_id] = {
                    "tx_hash": tx_hash,
                    "retries": 0,
                }

            # Snapshot
            for proposal_id, expiring_proposal in expiring_proposals[
                "snapshot"
            ].items():
                if proposal_id in pending_transactions["snapshot"]:
                    continue

                if expiring_proposal["vote"] is None:
                    continue

                self.context.logger.info(
                    f"Preparing transaction for Snapshot proposal {proposal_id}: {expiring_proposal}"
                )

                tx_hash, api_data = yield from self._get_snapshot_tx_hash(
                    expiring_proposal, safe_nonce
                )

                if safe_nonce:
                    safe_nonce += 1

                pending_transactions["snapshot"][proposal_id] = {
                    "tx_hash": tx_hash,
                    "api_data": api_data,
                    "retries": 0,
                }

            payload = PrepareVoteTransactionsPayload(
                sender=self.context.agent_address,
                content=json.dumps(
                    {"pending_transactions": pending_transactions}, sort_keys=True
                ),
            )

            with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
                yield from self.send_a2a_transaction(payload)
                yield from self.wait_until_round_end()

            self.set_done()


class DecisionMakingBehaviour(ProposalVoterBaseBehaviour):
    """DecisionMakingBehaviour"""

    matching_round: Type[AbstractRound] = DecisionMakingRound

    def async_act(self) -> Generator:
        """Do the act, supporting asynchronous execution."""

        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            pending_transactions = self.synchronized_data.pending_transactions

            # Remove proposals with too many retries
            pending_transactions["snapshot"] = {
                k: v
                for k, v in pending_transactions["snapshot"].items()
                if v["retries"] < MAX_VOTE_RETRIES
            }
            pending_transactions["tally"] = {
                k: v
                for k, v in pending_transactions["tally"].items()
                if v["retries"] < MAX_VOTE_RETRIES
            }

            payload_data = {"pending_transactions": pending_transactions}

            # Snapshot proposals
            for proposal_id, vote_data in pending_transactions["snapshot"].items():
                if vote_data["retries"] < MAX_VOTE_RETRIES:
                    payload_data["selected_proposal"] = {
                        "proposal_id": proposal_id,
                        "platform": "snapshot",
                    }
                    self.context.logger.info(
                        f"Selected Snapshot proposal {proposal_id}"
                    )
                    break

            # Tally proposals: processed only after Snapshot transactions
            if not pending_transactions["snapshot"]:
                for proposal_id, vote_data in pending_transactions["tally"].items():
                    if vote_data["retries"] < MAX_VOTE_RETRIES:
                        payload_data["selected_proposal"] = {
                            "proposal_id": proposal_id,
                            "platform": "tally",
                        }
                        self.context.logger.info(
                            f"Selected Tally proposal {proposal_id}"
                        )
                        break

            payload = DecisionMakingPayload(
                sender=self.context.agent_address,
                content=json.dumps(payload_data, sort_keys=True),
            )

            with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
                yield from self.send_a2a_transaction(payload)
                yield from self.wait_until_round_end()

            self.set_done()


class PostTxDecisionMakingBehaviour(ProposalVoterBaseBehaviour):
    """PostTxDecisionMakingBehaviour"""

    matching_round: Type[AbstractRound] = PostTxDecisionMakingRound

    def async_act(self) -> Generator:
        """Do the act, supporting asynchronous execution."""

        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            payload = PostTxDecisionMakingPayload(
                sender=self.context.agent_address,
                event=self.synchronized_data.current_path,
            )

            with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
                yield from self.send_a2a_transaction(payload)
                yield from self.wait_until_round_end()

            self.set_done()


class PostVoteDecisionMakingBehaviour(ProposalVoterBaseBehaviour):
    """PostVoteDecisionMakingBehaviour"""

    matching_round: Type[AbstractRound] = PostVoteDecisionMakingRound

    def async_act(self) -> Generator:
        """Do the act, supporting asynchronous execution."""

        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            if not self.synchronized_data.is_vote_verified:
                payload_content = PostVoteDecisionMakingRound.RETRY_PAYLOAD
            elif self.synchronized_data.selected_proposal["platform"] == "snapshot":
                payload_content = PostVoteDecisionMakingRound.CALL_PAYLOAD
            else:
                payload_content = PostVoteDecisionMakingRound.SKIP_PAYLOAD

            sender = self.context.agent_address
            payload = PostVoteDecisionMakingPayload(
                sender=sender,
                content=payload_content,
            )

        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()

        self.set_done()


class SnapshotAPISendRandomnessBehaviour(RandomnessBehaviour):
    """Retrieve randomness."""

    matching_round = SnapshotAPISendRandomnessRound
    payload_class = SnapshotAPISendRandomnessPayload


class SnapshotAPISendSelectKeeperBehaviour(
    SelectKeeperBehaviour, ProposalVoterBaseBehaviour
):
    """Select the keeper agent."""

    matching_round = SnapshotAPISendSelectKeeperRound
    payload_class = SnapshotAPISendSelectKeeperPayload


class SnapshotAPISendBehaviour(ProposalVoterBaseBehaviour):
    """SnapshotAPISendBehaviour"""

    matching_round: Type[AbstractRound] = SnapshotAPISendRound

    def _i_am_not_sending(self) -> bool:
        """Indicates if the current agent is the sender or not."""
        return (
            self.context.agent_address
            != self.synchronized_data.most_voted_keeper_address
        )

    def async_act(self) -> Generator[None, None, None]:
        """Do the action"""
        if self._i_am_not_sending():
            yield from self._not_sender_act()
        else:
            yield from self._sender_act()

    def _not_sender_act(self) -> Generator:
        """Do the non-sender action."""
        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            self.context.logger.info(
                f"Waiting for the keeper to do its keeping: {self.synchronized_data.most_voted_keeper_address}"
            )
            yield from self.wait_until_round_end()
        self.set_done()

    def _sender_act(self) -> Generator:
        """Do the sender action"""

        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            success = yield from self._call_snapshot_api()
            sender = self.context.agent_address
            payload = SnapshotAPISendPayload(sender=sender, success=success)

        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()

        self.set_done()

    def _call_snapshot_api(self):
        """Send the vote to Snapshot's API"""

        proposal_id = self.synchronized_data.selected_proposal["proposal_id"]
        api_data = self.synchronized_data.pending_transactions["snapshot"][proposal_id][
            "api_data"
        ]

        retries = 0
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        while retries < MAX_RETRIES:
            self.context.logger.info(
                f"Sending vote data to Snapshot API [{self.params.snapshot_vote_endpoint}]: {api_data}"
            )

            # Avoid calling too quicly
            yield from self.sleep(self.params.tally_api_call_sleep_seconds)

            # Make the request
            response = yield from self.get_http_response(
                method="POST",
                url=self.params.snapshot_vote_endpoint,
                content=json.dumps(api_data).encode("utf-8"),
                headers=headers,
            )

            if response.status_code != HTTP_OK:
                retries += 1
                self.context.logger.error(
                    f"Could not send the vote to Snapshot API [{retries} retries]. "
                    f"Received status code {response.status_code}: {response.json()}."
                )
                continue

            else:
                self.context.logger.info("Succesfully submitted the vote.")
                return True

        return False


class ProposalVoterRoundBehaviour(AbstractRoundBehaviour):
    """ProposalVoterRoundBehaviour"""

    initial_behaviour_cls = EstablishVoteBehaviour
    abci_app_cls = ProposalVoterAbciApp  # type: ignore
    behaviours: Set[Type[BaseBehaviour]] = [
        MechCallCheckBehaviour,
        DecisionMakingBehaviour,
        PrepareMechRequestBehaviour,
        EstablishVoteBehaviour,
        PrepareVoteTransactionsBehaviour,
        PostTxDecisionMakingBehaviour,
        PostVoteDecisionMakingBehaviour,
        SnapshotAPISendRandomnessBehaviour,
        SnapshotAPISendSelectKeeperBehaviour,
        SnapshotAPISendBehaviour,
    ]
